from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from src.config.settings import get_settings
from src.utils.compliance import (
    CLEAN_ALLOWED_FIELDS,
    CLEAN_CORE_CSV_COLUMNS,
    CLEAN_FEATURE_CSV_COLUMNS,
    RAW_ALLOWED_FIELDS,
    RAW_OUTPUT_CSV_COLUMNS,
    assert_compliant_record,
    normalize_listing_url,
    sanitize_clean_listing_record,
    sanitize_raw_listing_record,
    sanitize_text,
)
from src.utils.db import get_connection
from src.utils.logger import get_logger, log_event


BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"
CLEAN_DIR = BASE_DIR / "data" / "clean"
CLEAN_DIR.mkdir(parents=True, exist_ok=True)

PRICE_MIN = Decimal("10000.00")
PRICE_MAX = Decimal("50000000.00")

SURFACE_MIN = Decimal("40.00")
SURFACE_MAX = Decimal("400.00")

BEDROOMS_MIN = 0
BEDROOMS_MAX = 8

BATHROOMS_MIN = 0
BATHROOMS_MAX = 5

FLOOR_MIN = 0
FLOOR_MAX = 20

PRICE_PER_M2_MIN = Decimal("1000.00")
PRICE_PER_M2_MAX = Decimal("30000.00")

REQUIRED_CLEAN_COLUMNS = CLEAN_CORE_CSV_COLUMNS
OPTIONAL_FEATURE_COLUMNS = [
    "surface_m2",
    "bedrooms",
    "bathrooms",
    "floor",
    "price_per_m2",
]
INTERNAL_OPTIONAL_COLUMNS = [
    *OPTIONAL_FEATURE_COLUMNS,
    "construction_year",
    "property_age",
]

TWO_PLACES = Decimal("0.01")
ZERO_PLACES = Decimal("1")

PRICE_NUMBER_PATTERN = (
    r"(?:\d{1,3}(?:[\s.]\d{3})+(?:[,.]\d{1,2})?"
    r"|\d{4,}(?:[,.]\d{1,2})?)"
)
PRICE_RE = re.compile(
    rf"(?P<number>{PRICE_NUMBER_PATTERN})\s*(?:dhs?|mad|dirhams?)\b",
    re.IGNORECASE,
)
MILLION_PRICE_RE = re.compile(
    r"\b(?P<number>\d+(?:[,.]\d+)?)\s*(?:million|millions)"
    r"\s*(?:dhs?|mad|dirhams?)?\b",
    re.IGNORECASE,
)
SURFACE_RE = re.compile(
    r"(?<!\d)(?P<number>\d{1,5}(?:[,.]\d{1,2})?)\s*(?:m2|m²|mÂ²|m\^2)\b",
    re.IGNORECASE,
)
SURFACE_KEYWORD_RE = re.compile(
    r"\b(?:surface|superficie)\D{0,24}(?P<number>\d{1,5}(?:[,.]\d{1,2})?)\b",
    re.IGNORECASE,
)
BEDROOM_RE = re.compile(
    r"(?<!\d)(?P<number>\d{1,2})\s*(?:chambres?|pieces?|pièces?)\b",
    re.IGNORECASE,
)
BATHROOM_RE = re.compile(
    r"(?<!\d)(?P<number>\d{1,2})\s*(?:sdbs?|bains?|salles?\s+de\s+bain)\b",
    re.IGNORECASE,
)
FLOOR_RE = re.compile(
    r"\b(?:étage|etage|niveau)\s*(?P<floor>-?\d{1,2})\b|"
    r"\b(?P<floor_before>-?\d{1,2})(?:er|eme|e|ème)?\s*(?:étage|etage|niveau)\b",
    re.IGNORECASE,
)
GROUND_FLOOR_RE = re.compile(
    r"\b(?:rdc|rez\s+de\s+chaussée|rez\s+de\s+chaussee)\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(18\d{2}|19\d{2}|20\d{2})\b")
CONSTRUCTION_YEAR_RE = re.compile(
    r"\b(?:construction|construit|année|annee)\D{0,24}(18\d{2}|19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
LOCATION_RE = re.compile(
    r"\b(?:appartements?|villas?\s+et\s+riads?|terrains?\s+et\s+fermes?|"
    r"locaux?|local|bureaux?|maisons?)\s+dans\s+"
    r"(?P<city>[A-Za-zÀ-ÿ\s'-]+)"
    r"(?:,\s*(?P<district>[A-Za-zÀ-ÿ0-9\s'/-]+?))?"
    r"(?=\s+(?:appartement|villa|terrain|bureau|magasin|local|studio|duplex|"
    r"riad|a vendre|à vendre|location|chambre|maison)|$)",
    re.IGNORECASE,
)
LOCATION_NOISE_RE = re.compile(
    r"\b(?:toute la ville|autre secteur|premium|star|contacter|vendeur|prix|mad|dh)\b",
    re.IGNORECASE,
)
ADDRESS_HINT_RE = re.compile(
    r"\b(?:rue|avenue|boulevard|bd|résidence|residence|immeuble|lot|numero|num|n°)\b",
    re.IGNORECASE,
)
TITLE_ACTION_RE = re.compile(
    r"\b(?:contacter\s+le\s+vendeur|demander\s+le\s+prix|prix\s+non\s+spécifié|"
    r"prix\s+non\s+specifie)\b.*$",
    re.IGNORECASE,
)
CATEGORY_LOCATION_PREFIX_RE = re.compile(
    r"^(?:appartements?|villas?\s+et\s+riads?|terrains?\s+et\s+fermes?|"
    r"locaux?|local|bureaux?|maisons?)\s+dans\s+"
    r"[A-Za-zÀ-ÿ\s'-]+(?:,\s*[A-Za-zÀ-ÿ0-9\s'/-]+?)?\s+"
    r"(?=(?:appartement|villa|terrain|bureau|magasin|local|studio|duplex|riad|maison)\b)",
    re.IGNORECASE,
)
SELLER_PREFIX_RE = re.compile(
    r"^.{0,100}?\bil\s+y\s+a\s+\d+\s+(?:minutes?|heures?|jours?|mois)\s+",
    re.IGNORECASE,
)
TRAILING_FEATURE_RE = re.compile(
    r"\b\d+\s+(?:personnes?|chambres?|pieces?|pièces?|sdbs?|"
    r"salles?\s+de\s+bain)\b.*$",
    re.IGNORECASE,
)

CATEGORY_SLUGS = {
    "appartements",
    "appartement",
    "villas_et_riads",
    "terrains_et_fermes",
    "bureaux",
    "locaux",
    "local",
    "maisons",
}
KNOWN_CITY_SLUGS = {
    "agadir",
    "beni_mellal",
    "bouskoura",
    "casablanca",
    "dar_bouazza",
    "el_jadida",
    "fes",
    "fès",
    "ifrane",
    "kenitra",
    "kénitra",
    "marrakech",
    "meknes",
    "mohammedia",
    "oujda",
    "rabat",
    "sale",
    "salé",
    "tanger",
    "temara",
    "témara",
    "tetouan",
    "tétouan",
}


@dataclass(frozen=True)
class CleanColumnProfile:
    columns_kept: list[str]
    columns_removed: list[str]
    missing_percentage_by_column: dict[str, float]
    required_null_counts: dict[str, int]
    optional_completeness_percent: dict[str, float]


@dataclass(frozen=True)
class CleanResult:
    batch_id: str
    clean_file: Path
    features_file: Path
    quality_report: Path
    clean_rows: int
    features_rows: int
    duplicates_removed: int
    invalid_reasons_count: dict[str, int]


@dataclass(frozen=True)
class CsvReadResult:
    records: list[dict[str, Any]]
    skipped_rows: int
    invalid_reasons_count: dict[str, int]


def latest_raw_file() -> Path:
    files = sorted(RAW_DIR.glob("avito_raw_batch_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        files = sorted(RAW_DIR.glob("avito_raw_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError("No raw Avito CSV found in data/raw")
    return files[0]


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = sanitize_text(value)
    if not text:
        return None
    if text.strip().lower() in {"nan", "none", "null", "na", "n/a", "-"}:
        return None
    return text


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _normal_key(value: Any) -> str:
    text = clean_text(value) or ""
    text = _strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_missing(value: Any) -> bool:
    return clean_text(value) is None


def _source_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if not _is_missing(value):
            return value
    return None


def _decimal_from_number_token(token: str, multiplier: Decimal = Decimal("1")) -> Decimal | None:
    if not token:
        return None
    text = token.strip().replace("\u202f", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", "", text)
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        decimals = text.rsplit(",", 1)[-1]
        text = text.replace(",", ".") if 0 < len(decimals) <= 2 else text.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:\.\d{1,2})?", text):
        text = text.replace(".", "")

    text = re.sub(r"[^0-9.]", "", text)
    if not text or text == ".":
        return None
    try:
        return (Decimal(text) * multiplier).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _is_monthly_price_context(text: str, end_index: int) -> bool:
    after = text[end_index : end_index + 40]
    return bool(re.match(r"\s*(?:/|par)?\s*mois\b", after, re.IGNORECASE))


def _price_candidates(text: Any) -> list[tuple[int, Decimal, bool]]:
    value = clean_text(text)
    if not value:
        return []
    if re.search(r"\b(?:prix non spécifié|prix non specifie|demander le prix)\b", value, re.IGNORECASE):
        return []

    candidates: list[tuple[int, Decimal, bool]] = []
    for match in MILLION_PRICE_RE.finditer(value):
        amount = _decimal_from_number_token(match.group("number"), Decimal("1000000"))
        if amount is not None:
            candidates.append((match.start(), amount, _is_monthly_price_context(value, match.end())))
    for match in PRICE_RE.finditer(value):
        amount = _decimal_from_number_token(match.group("number"))
        if amount is not None:
            candidates.append((match.start(), amount, _is_monthly_price_context(value, match.end())))
    return sorted(candidates, key=lambda item: item[0])


def parse_decimal(value: Any) -> Decimal | None:
    candidates = _price_candidates(value)
    if candidates:
        non_monthly = [candidate for candidate in candidates if not candidate[2]]
        return (non_monthly or candidates)[0][1]

    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"-?\d+(?:[\s.]\d{3})*(?:[,.]\d+)?", text)
    if not match:
        return None
    return _decimal_from_number_token(match.group(0))


def _first_valid_decimal(
    values: tuple[Any, ...],
    parser: Any,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal | None:
    for value in values:
        parsed = parser(value)
        if parsed is not None and minimum <= parsed <= maximum:
            return parsed
    return None


def parse_price(*values: Any) -> Decimal | None:
    for value in values:
        candidates = _price_candidates(value)
        non_monthly = [candidate for candidate in candidates if not candidate[2]]
        for _start, amount, _monthly in non_monthly or candidates:
            if PRICE_MIN <= amount <= PRICE_MAX:
                return amount
        text = clean_text(value)
        if text and re.fullmatch(r"\d+(?:[\s.]\d{3})*(?:[,.]\d{1,2})?", text):
            amount = parse_decimal(text)
            if amount is not None and PRICE_MIN <= amount <= PRICE_MAX:
                return amount
    return None


def _surface_candidates(text: Any) -> list[Decimal]:
    value = clean_text(text)
    if not value:
        return []

    candidates: list[Decimal] = []
    for pattern in (SURFACE_RE, SURFACE_KEYWORD_RE):
        for match in pattern.finditer(value):
            amount = _decimal_from_number_token(match.group("number"))
            if amount is not None:
                candidates.append(amount)
    return candidates


def parse_surface(*values: Any) -> Decimal | None:
    for value in values:
        for amount in _surface_candidates(value):
            if SURFACE_MIN <= amount <= SURFACE_MAX:
                return amount
        text = clean_text(value)
        if text and re.fullmatch(r"\d+(?:[,.]\d{1,2})?", text):
            amount = parse_decimal(text)
            if amount is not None and SURFACE_MIN <= amount <= SURFACE_MAX:
                return amount
    return None


def parse_int_feature(value: Any, min_value: int = 0, max_value: int = 20) -> int | None:
    number = parse_decimal(value)
    if number is None:
        return None
    integer = int(number)
    if Decimal(integer) != number:
        return None
    if min_value <= integer <= max_value:
        return integer
    return None


def _parse_count_from_pattern(
    pattern: re.Pattern[str],
    values: tuple[Any, ...],
    min_value: int,
    max_value: int,
) -> int | None:
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        match = pattern.search(text)
        if not match:
            continue
        count = int(match.group("number"))
        if min_value <= count <= max_value:
            return count
    return None


def parse_bedrooms(*values: Any) -> int | None:
    count = _parse_count_from_pattern(BEDROOM_RE, values, BEDROOMS_MIN, BEDROOMS_MAX)
    if count is not None:
        return count
    for value in values:
        text = clean_text(value)
        if text and re.search(r"\bstudio\b", text, re.IGNORECASE):
            return 0
    return None


def parse_bathrooms(*values: Any) -> int | None:
    return _parse_count_from_pattern(BATHROOM_RE, values, BATHROOMS_MIN, BATHROOMS_MAX)


def parse_floor(value: Any, *, focused: bool = False) -> int | None:
    text = clean_text(value)
    if not text:
        return None
    if GROUND_FLOOR_RE.search(text):
        return 0
    match = FLOOR_RE.search(text)
    if not match:
        return None
    floor_text = match.group("floor") or match.group("floor_before")
    if floor_text is None:
        return None
    floor = int(floor_text)
    if floor == 0:
        return None
    if FLOOR_MIN <= floor <= FLOOR_MAX:
        return floor
    return None


def parse_floor_from_values(*values: Any) -> int | None:
    for value in values:
        floor = parse_floor(value)
        if floor is not None:
            return floor
    return None


def parse_construction_year(*values: Any, current_year: int | None = None) -> int | None:
    year_limit = current_year or datetime.now(UTC).year
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        match = CONSTRUCTION_YEAR_RE.search(text) or YEAR_RE.search(text)
        if not match:
            continue
        year = int(match.group(1))
        if 1800 <= year <= year_limit and year_limit - year <= 150:
            return year
    return None


def _title_case_location(value: str) -> str:
    particles = {"de", "du", "des", "la", "le", "les", "el", "al", "et"}
    words = []
    for word in re.split(r"(\s+|-|')", value.lower()):
        if not word or word.isspace() or word in {"-", "'"}:
            words.append(word)
        elif word in particles:
            words.append(word)
        else:
            words.append(word[:1].upper() + word[1:])
    return "".join(words).strip()


def standardize_city(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = re.split(r"[,|-]", text, maxsplit=1)[0].strip()
    key = _normal_key(text)
    aliases = {
        "agadir": "Agadir",
        "beni mellal": "B\u00e9ni Mellal",
        "bouskoura": "Bouskoura",
        "casa": "Casablanca",
        "casablanca": "Casablanca",
        "dar bouazza": "Dar Bouazza",
        "el jadida": "El Jadida",
        "fes": "F\u00e8s",
        "f s": "F\u00e8s",
        "ifrane": "Ifrane",
        "kenitra": "K\u00e9nitra",
        "marrakech": "Marrakech",
        "marrakesh": "Marrakech",
        "meknes": "Mekn\u00e8s",
        "mohammedia": "Mohammedia",
        "oujda": "Oujda",
        "rabat": "Rabat",
        "sale": "Sal\u00e9",
        "tanger": "Tanger",
        "temara": "T\u00e9mara",
        "tetouan": "T\u00e9touan",
    }
    return aliases.get(key, _title_case_location(text))


def standardize_district(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"\b(?:Toute la ville|Autre secteur)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:Premium|Star)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+/\d+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,-")
    if not text or len(text) > 80:
        return None
    if LOCATION_NOISE_RE.search(text) or ADDRESS_HINT_RE.search(text):
        return None
    return _title_case_location(text)


def _location_from_text(value: Any) -> tuple[str | None, str | None]:
    text = clean_text(value)
    if not text:
        return None, None
    match = LOCATION_RE.search(text)
    if not match:
        return None, None
    return standardize_city(match.group("city")), standardize_district(match.group("district"))


def _slug_to_label(value: str | None) -> str | None:
    text = clean_text(unquote(value or ""))
    if not text:
        return None
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _title_case_location(text) if text else None


def _location_from_url(url: Any) -> tuple[str | None, str | None]:
    listing_url = normalize_listing_url(clean_text(url))
    if not listing_url:
        return None, None
    parts = [
        _slug_to_label(part)
        for part in unquote(urlparse(listing_url).path).split("/")
        if part and part.lower() not in {"fr", "ar"}
    ]
    useful = [
        part
        for part in parts[:-1]
        if part and part.lower().replace(" ", "_") not in CATEGORY_SLUGS
    ]
    if not useful:
        return None, None
    first = useful[0]
    first_slug = first.lower().replace(" ", "_")
    if first_slug in KNOWN_CITY_SLUGS:
        return standardize_city(first), None
    return None, standardize_district(first)


def _title_from_url(url: Any) -> str | None:
    listing_url = normalize_listing_url(clean_text(url))
    if not listing_url:
        return None
    slug = Path(unquote(urlparse(listing_url).path)).stem
    slug = re.sub(r"_[0-9]+$", "", slug)
    slug = re.sub(r"[_-]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    if not slug or slug.lower() in {"listing", "annonce"}:
        return None
    return slug[:1].upper() + slug[1:]


def clean_listing_title(value: Any, listing_url: Any | None = None) -> str | None:
    text = clean_text(value)
    if not text:
        return _title_from_url(listing_url)

    text = SELLER_PREFIX_RE.sub("", text)
    text = re.sub(r"\b(?:Premium|Star)\b|\b\d+/\d+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = CATEGORY_LOCATION_PREFIX_RE.sub("", text)
    category_match = re.search(CATEGORY_LOCATION_PREFIX_RE.pattern, text, re.IGNORECASE)
    if category_match:
        text = text[category_match.end() :]
    text = TITLE_ACTION_RE.sub("", text)
    text = re.sub(r"\b\d+(?:[\s.]\d{3})*(?:[,.]\d+)?\s*(?:dhs?|mad|dirhams?)\b.*$", "", text, flags=re.IGNORECASE)
    text = TRAILING_FEATURE_RE.sub("", text)
    text = re.sub(r"\b(?:étage|etage|niveau)\s*-?\d{1,2}\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:rdc|rez\s+de\s+chaussée|rez\s+de\s+chaussee)\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,-")

    fallback_title = _title_from_url(listing_url)
    if (
        not text
        or len(text) < 8
        or _normal_key(text) in {"appartement", "villa", "terrain", "maison", "bureau", "local"}
    ):
        return fallback_title or text or None
    return text[:220]


def build_listing_title_clean(row: dict[str, Any]) -> str | None:
    return clean_listing_title(
        _source_value(row, "listing_title_raw", "listing_title"),
        _source_value(row, "listing_url"),
    )


def _parse_scraped_at(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed.isoformat(timespec="seconds")


def _safe_price_per_m2(price: Decimal | None, surface: Decimal | None) -> Decimal | None:
    if price is None or surface is None or surface <= 0:
        return None
    value = (price / surface).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    if PRICE_PER_M2_MIN <= value <= PRICE_PER_M2_MAX:
        return value
    return None
def _validate_feature_row(row: dict[str, Any]) -> dict[str, Any]:
    surface = row.get("surface_m2")
    price_per_m2 = row.get("price_per_m2")

    if isinstance(surface, Decimal) and not (Decimal("40.00") <= surface <= Decimal("400.00")):
        row["surface_m2"] = None
        row["price_per_m2"] = None

    if isinstance(price_per_m2, Decimal) and not (
        Decimal("1000.00") <= price_per_m2 <= Decimal("30000.00")
    ):
        row["price_per_m2"] = None

    if row.get("bedrooms") is not None and row["bedrooms"] > 8:
        row["bedrooms"] = None

    if row.get("bathrooms") is not None and row["bathrooms"] > 5:
        row["bathrooms"] = None

    if row.get("floor") is not None and row["floor"] > 20:
        row["floor"] = None

    return row

def _resolve_location(row: dict[str, Any]) -> tuple[str | None, str | None]:
    title_raw = _source_value(row, "listing_title_raw", "listing_title")
    city = standardize_city(_source_value(row, "city_raw", "city"))
    district = standardize_district(_source_value(row, "district_raw", "district"))

    text_city, text_district = _location_from_text(title_raw)
    url_city, url_district = _location_from_url(_source_value(row, "listing_url"))

    city = city or text_city or url_city
    district = district or text_district or url_district
    if city and district and _normal_key(city) == _normal_key(district):
        district = district
    return city, district


def _clean_raw_row_with_reason(
    row: dict[str, Any],
    *,
    current_year: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    raw = sanitize_raw_listing_record(row)
    assert_compliant_record(raw, RAW_ALLOWED_FIELDS)

    listing_url = normalize_listing_url(raw.get("listing_url"))
    if not listing_url:
        return None, "missing_listing_url"

    title_raw = _source_value(raw, "listing_title_raw", "listing_title")
    price_raw = _source_value(raw, "price_raw", "price")
    surface_raw = _source_value(raw, "surface_raw", "surface_m2")
    bedrooms_raw = _source_value(raw, "bedrooms_raw", "bedrooms")
    bathrooms_raw = _source_value(raw, "bathrooms_raw", "bathrooms")
    floor_raw = _source_value(raw, "floor_raw", "floor")
    construction_year_raw = _source_value(raw, "construction_year_raw", "construction_year")

    listing_title_clean = clean_listing_title(title_raw, listing_url)
    if not listing_title_clean:
        return None, "missing_listing_title_clean"

    price = parse_price(price_raw, title_raw)
    if price is None:
        return None, "invalid_price"

    city, district = _resolve_location(raw)
    if not city:
        return None, "missing_city"
    if not district:
        return None, "missing_district"

    scraped_at = _parse_scraped_at(raw.get("scraped_at"))
    if not scraped_at:
        return None, "missing_scraped_at"

    batch_id = clean_text(raw.get("batch_id"))
    if not batch_id:
        return None, "missing_batch_id"

    year_limit = current_year or datetime.now(UTC).year
    surface_m2 = parse_surface(title_raw, surface_raw)
    bedrooms = parse_bedrooms(title_raw, bedrooms_raw)
    bathrooms = parse_bathrooms(title_raw, bathrooms_raw)
    floor = parse_floor_from_values(title_raw, floor_raw)
    construction_year = parse_construction_year(
        construction_year_raw,
        title_raw,
        current_year=year_limit,
    )
    property_age = year_limit - construction_year if construction_year is not None else None
    price_per_m2 = _safe_price_per_m2(price, surface_m2)

    cleaned = {
        "listing_title_clean": listing_title_clean,
        "price": price,
        "city": city,
        "district": district,
        "surface_m2": surface_m2,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "floor": floor,
        "construction_year": construction_year,
        "property_age": property_age,
        "price_per_m2": price_per_m2,
        "listing_url": listing_url,
        "scraped_at": scraped_at,
        "batch_id": batch_id,
    }
    safe = sanitize_clean_listing_record(cleaned)
    assert_compliant_record(safe, CLEAN_ALLOWED_FIELDS)
    cleaned.update(safe)
    return cleaned, None


def clean_raw_row(row: dict[str, Any], current_year: int | None = None) -> dict[str, Any] | None:
    cleaned, _reason = _clean_raw_row_with_reason(row, current_year=current_year)
    return cleaned


def remove_duplicates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    duplicate_count = 0
    for row in rows:
        url = normalize_listing_url(_source_value(row, "listing_url"))
        if url and url in seen:
            duplicate_count += 1
            continue
        if url:
            seen.add(url)
        deduped.append(row)
    return deduped, duplicate_count


def _clean_rows(
    rows: list[dict[str, Any]],
    *,
    current_year: int | None = None,
) -> tuple[list[dict[str, Any]], int, Counter[str]]:
    deduped_rows, duplicates_removed = remove_duplicates(rows)
    invalid_reasons: Counter[str] = Counter()
    clean_rows: list[dict[str, Any]] = []
    for row in deduped_rows:
        cleaned, reason = _clean_raw_row_with_reason(row, current_year=current_year)
        if cleaned is None:
            invalid_reasons[reason or "unknown"] += 1
            continue
        clean_rows.append(cleaned)
    return clean_rows, duplicates_removed, invalid_reasons


def build_clean_column_profile(rows: list[dict[str, Any]]) -> CleanColumnProfile:
    row_count = len(rows)
    required_null_counts = {
        column: sum(1 for row in rows if row.get(column) in {None, ""})
        for column in REQUIRED_CLEAN_COLUMNS
    }
    missing_percentage_by_column: dict[str, float] = {}
    optional_completeness_percent: dict[str, float] = {}
    for column in INTERNAL_OPTIONAL_COLUMNS:
        missing = sum(1 for row in rows if row.get(column) in {None, ""})
        missing_percent = 0.0 if row_count == 0 else round(missing / row_count * 100, 2)
        missing_percentage_by_column[column] = missing_percent
        optional_completeness_percent[column] = round(100 - missing_percent, 2)
    return CleanColumnProfile(
        columns_kept=list(REQUIRED_CLEAN_COLUMNS),
        columns_removed=list(INTERNAL_OPTIONAL_COLUMNS),
        missing_percentage_by_column=missing_percentage_by_column,
        required_null_counts=required_null_counts,
        optional_completeness_percent=optional_completeness_percent,
    )


def _available_feature_columns(rows: list[dict[str, Any]]) -> list[str]:
    return list(OPTIONAL_FEATURE_COLUMNS)


def _build_core_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{column: row.get(column) for column in REQUIRED_CLEAN_COLUMNS} for row in rows]


def _build_feature_rows(
    rows: list[dict[str, Any]],
    feature_columns: list[str] | None = None,
) -> list[dict[str, Any]]:
    columns = feature_columns or OPTIONAL_FEATURE_COLUMNS
    feature_rows: list[dict[str, Any]] = []

    for row in rows:
        feature_row = {
            "listing_url": row.get("listing_url"),
            **{column: row.get(column) for column in columns},
        }

        feature_row = _validate_feature_row(feature_row)

        # Keep only rows with valid surface.
        # This makes the features file cleaner and better for BI/ML.
        if feature_row.get("surface_m2") is not None:
            feature_rows.append(feature_row)

    return feature_rows


def _format_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP):f}"
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _format_csv_value(row.get(column)) for column in columns})


def _decimal_stats(rows: list[dict[str, Any]], column: str) -> dict[str, float | None]:
    values = [row.get(column) for row in rows if isinstance(row.get(column), Decimal)]
    if not values:
        return {f"{column}_min": None, f"{column}_max": None, f"{column}_avg": None}
    return {
        f"{column}_min": float(min(values)),
        f"{column}_max": float(max(values)),
        f"{column}_avg": float((sum(values) / Decimal(len(values))).quantize(TWO_PLACES)),
    }


def _top_values(rows: list[dict[str, Any]], column: str, limit: int = 10) -> list[dict[str, Any]]:
    counts = Counter(row.get(column) for row in rows if row.get(column))
    return [{"value": value, "count": count} for value, count in counts.most_common(limit)]


def _quality_report(
    rows_raw: int,
    rows: list[dict[str, Any]],
    duplicates_removed: int,
    invalid_reasons: Counter[str],
    batch_id: str,
    raw_file: Path | None = None,
) -> dict[str, Any]:
    profile = build_clean_column_profile(rows)
    core_rows = _build_core_rows(rows)
    feature_rows = _build_feature_rows(rows)
    feature_missing = {
        column: sum(1 for row in feature_rows if row.get(column) in {None, ""})
        for column in ["listing_url", *OPTIONAL_FEATURE_COLUMNS]
    }
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch_id,
        "raw_file": str(raw_file) if raw_file else None,
        "raw_rows": rows_raw,
        "rows_raw": rows_raw,
        "after_dedup_rows": rows_raw - duplicates_removed,
        "rows_after_duplicates": rows_raw - duplicates_removed,
        "removed_duplicates": duplicates_removed,
        "duplicates_removed": duplicates_removed,
        "clean_rows": len(rows),
        "core_row_count": len(core_rows),
        "features_row_count": len(feature_rows),
        "removed_missing_required": sum(
            count for reason, count in invalid_reasons.items() if reason.startswith("missing_")
        ),
        "invalid_reasons_count": dict(sorted(invalid_reasons.items())),
        "required_null_counts": profile.required_null_counts,
        "missing_values_core": {
            column: sum(1 for row in core_rows if row.get(column) in {None, ""})
            for column in REQUIRED_CLEAN_COLUMNS
        },
        "missing_values_features": feature_missing,
        "columns_kept_in_core": profile.columns_kept,
        "columns_removed_from_core": profile.columns_removed,
        "optional_completeness_percent": profile.optional_completeness_percent,
        "validation_ranges": {
            "price_mad": [float(PRICE_MIN), float(PRICE_MAX)],
            "surface_m2": [float(SURFACE_MIN), float(SURFACE_MAX)],
            "bedrooms": [BEDROOMS_MIN, BEDROOMS_MAX],
            "bathrooms": [BATHROOMS_MIN, BATHROOMS_MAX],
            "floor": [FLOOR_MIN, FLOOR_MAX],
            "price_per_m2": [float(PRICE_PER_M2_MIN), float(PRICE_PER_M2_MAX)],
        },
        "top_cities": _top_values(rows, "city"),
        "top_districts": _top_values(rows, "district"),
        "quality_warnings": [],
    }
    for reason, count in invalid_reasons.items():
        report[f"removed_{reason.replace('missing_', 'missing_')}"] = count
    report.update(_decimal_stats(rows, "price"))
    report.update(_decimal_stats(rows, "surface_m2"))
    report.update(_decimal_stats(rows, "price_per_m2"))
    report["price_min"] = report.get("price_min")
    report["price_max"] = report.get("price_max")
    report["avg_price"] = report.get("price_avg")
    report["surface_min"] = report.get("surface_m2_min")
    report["surface_max"] = report.get("surface_m2_max")
    report["avg_surface"] = report.get("surface_m2_avg")
    report["price_per_m2_min"] = report.get("price_per_m2_min")
    report["price_per_m2_max"] = report.get("price_per_m2_max")
    report["avg_price_per_m2"] = report.get("price_per_m2_avg")

    if rows:
        if report["optional_completeness_percent"]["surface_m2"] < 60:
            report["quality_warnings"].append(
                "Surface completeness below 60%. Review scraper feature selectors."
            )
        if report["optional_completeness_percent"]["bedrooms"] < 50:
            report["quality_warnings"].append(
                "Bedrooms completeness below 50%. Detail pages may be needed for this field."
            )
        if invalid_reasons.get("invalid_price", 0) / max(rows_raw, 1) > 0.25:
            report["quality_warnings"].append(
                "High invalid price rate. Rental listings or weak price extraction may be present."
            )
    return report


def _infer_batch_id(path: Path, fallback: str | None = None) -> str:
    if fallback:
        return fallback
    match = re.search(r"(batch_\d{8}T\d{6}Z|batch_[A-Za-z0-9_-]+)", path.stem)
    if match:
        return match.group(1)
    return datetime.now(UTC).strftime("batch_%Y%m%dT%H%M%SZ")


def clean_raw_csv_to_clean_csv(raw_file: Path, batch_id: str | None = None) -> CleanResult:
    settings = get_settings()
    batch_id = _infer_batch_id(raw_file, batch_id)
    logger = get_logger(__name__)

    with raw_file.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames or []
        if "listing_title_raw" not in fieldnames and "listing_title" not in fieldnames:
            raise ValueError("Raw CSV missing title column: expected listing_title_raw")
        missing_columns = sorted(
            set(RAW_OUTPUT_CSV_COLUMNS) - set(fieldnames) - {"listing_title_raw"}
        )
        if missing_columns:
            raise ValueError(f"Raw CSV missing columns: {missing_columns}")
        raw_rows = [dict(row) for row in reader]

    clean_rows, duplicates_removed, invalid_reasons = _clean_rows(raw_rows)
    feature_columns = _available_feature_columns(clean_rows)
    core_rows = _build_core_rows(clean_rows)
    feature_rows = _build_feature_rows(clean_rows, feature_columns)

    clean_file = settings.clean_dir / f"avito_clean_core_{batch_id}.csv"
    features_file = settings.clean_dir / f"avito_clean_features_{batch_id}.csv"
    quality_report = settings.clean_dir / f"quality_report_{batch_id}.json"

    _write_csv(clean_file, core_rows, REQUIRED_CLEAN_COLUMNS)
    _write_csv(features_file, feature_rows, ["listing_url", *feature_columns])

    report = _quality_report(
        len(raw_rows),
        clean_rows,
        duplicates_removed,
        invalid_reasons,
        batch_id,
        raw_file,
    )
    with quality_report.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=4, ensure_ascii=False)

    log_event(
        logger,
        logging.INFO,
        "clean_csv_written",
        batch_id=batch_id,
        raw_rows=len(raw_rows),
        clean_rows=len(core_rows),
        features_rows=len(feature_rows),
        duplicates_removed=duplicates_removed,
        clean_file=str(clean_file),
        features_file=str(features_file),
        quality_report=str(quality_report),
    )
    return CleanResult(
        batch_id=batch_id,
        clean_file=clean_file,
        features_file=features_file,
        quality_report=quality_report,
        clean_rows=len(core_rows),
        features_rows=len(feature_rows),
        duplicates_removed=duplicates_removed,
        invalid_reasons_count=dict(sorted(invalid_reasons.items())),
    )


def clean_avito_data(df: Any) -> tuple[Any, Any, dict[str, Any]]:
    if hasattr(df, "to_dict"):
        raw_rows = df.to_dict("records")
    else:
        raw_rows = list(df)
    clean_rows, duplicates_removed, invalid_reasons = _clean_rows(raw_rows)
    core_rows = _build_core_rows(clean_rows)
    feature_rows = _build_feature_rows(clean_rows)
    report = _quality_report(len(raw_rows), clean_rows, duplicates_removed, invalid_reasons, "in_memory")
    try:
        import pandas as pd

        return pd.DataFrame(core_rows), pd.DataFrame(feature_rows), report
    except ImportError:
        return core_rows, feature_rows, report


def _read_clean_csv(clean_file: Path, batch_id: str) -> CsvReadResult:
    records: list[dict[str, Any]] = []
    invalid_reasons: Counter[str] = Counter()
    with clean_file.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing_columns = sorted(set(REQUIRED_CLEAN_COLUMNS) - set(reader.fieldnames or []))
        if missing_columns:
            raise ValueError(f"Clean CSV missing columns: {missing_columns}")
        for row in reader:
            missing_required = [
                column for column in REQUIRED_CLEAN_COLUMNS if clean_text(row.get(column)) is None
            ]
            if missing_required:
                invalid_reasons[f"missing_{missing_required[0]}"] += 1
                continue
            price = parse_decimal(row.get("price"))
            if price is None or not (PRICE_MIN <= price <= PRICE_MAX):
                invalid_reasons["invalid_price"] += 1
                continue
            listing_url = normalize_listing_url(row.get("listing_url"))
            if not listing_url:
                invalid_reasons["invalid_listing_url"] += 1
                continue
            record = {
                "listing_title_clean": clean_text(row.get("listing_title_clean")),
                "price": price,
                "city": standardize_city(row.get("city")),
                "district": standardize_district(row.get("district")),
                "listing_url": listing_url,
                "scraped_at": _parse_scraped_at(row.get("scraped_at")),
                "batch_id": clean_text(row.get("batch_id")) or batch_id,
                "surface_m2": None,
                "bedrooms": None,
                "bathrooms": None,
                "floor": None,
                "construction_year": None,
                "property_age": None,
                "price_per_m2": None,
            }
            if not record["city"]:
                invalid_reasons["missing_city"] += 1
                continue
            if not record["district"]:
                invalid_reasons["missing_district"] += 1
                continue
            safe = sanitize_clean_listing_record(record)
            assert_compliant_record(safe, CLEAN_ALLOWED_FIELDS)
            record.update(safe)
            records.append(record)
    return CsvReadResult(records, sum(invalid_reasons.values()), dict(sorted(invalid_reasons.items())))


def _read_feature_csv(features_file: Path, batch_id: str) -> CsvReadResult:
    records: list[dict[str, Any]] = []
    invalid_reasons: Counter[str] = Counter()
    with features_file.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        missing_columns = sorted(
            set(["listing_url", *OPTIONAL_FEATURE_COLUMNS]) - set(reader.fieldnames or [])
        )
        if missing_columns:
            raise ValueError(f"Features CSV missing columns: {missing_columns}")
        for row in reader:
            listing_url = normalize_listing_url(row.get("listing_url"))
            if not listing_url:
                invalid_reasons["invalid_listing_url"] += 1
                continue
            surface_m2 = parse_surface(row.get("surface_m2"))
            bedrooms = parse_int_feature(row.get("bedrooms"), BEDROOMS_MIN, BEDROOMS_MAX)
            bathrooms = parse_int_feature(row.get("bathrooms"), BATHROOMS_MIN, BATHROOMS_MAX)
            floor = parse_int_feature(row.get("floor"), FLOOR_MIN, FLOOR_MAX)
            price_per_m2 = _first_valid_decimal(
                (row.get("price_per_m2"),),
                parse_decimal,
                PRICE_PER_M2_MIN,
                PRICE_PER_M2_MAX,
            )
            record = {
                "listing_url": listing_url,
                "surface_m2": surface_m2,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "floor": floor,
                "price_per_m2": price_per_m2,
                "batch_id": batch_id,
            }
            if all(record[column] is None for column in OPTIONAL_FEATURE_COLUMNS):
                invalid_reasons["all_features_missing"] += 1
                continue
            records.append(record)
    return CsvReadResult(records, sum(invalid_reasons.values()), dict(sorted(invalid_reasons.items())))


def load_clean_csv_to_clean_table(
    clean_file: Path,
    batch_id: str,
    features_file: Path | None = None,
) -> int:
    clean_result = _read_clean_csv(clean_file, batch_id)
    feature_result = (
        _read_feature_csv(features_file, batch_id)
        if features_file and features_file.exists()
        else CsvReadResult([], 0, {})
    )
    clean_records = clean_result.records
    feature_records = [
        record
        for record in feature_result.records
        if record["listing_url"] in {clean_record["listing_url"] for clean_record in clean_records}
    ]

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM clean.clean_listing_features WHERE batch_id = %(batch_id)s;",
                {"batch_id": batch_id},
            )
            cursor.execute(
                "DELETE FROM clean.clean_listings WHERE batch_id = %(batch_id)s;",
                {"batch_id": batch_id},
            )
            if clean_records:
                cursor.executemany(
                    """
                    INSERT INTO clean.clean_listings (
                        listing_title_clean, price, city, district, listing_url, scraped_at, batch_id
                    )
                    VALUES (
                        %(listing_title_clean)s, %(price)s, %(city)s, %(district)s,
                        %(listing_url)s, %(scraped_at)s, %(batch_id)s
                    )
                    ON CONFLICT (listing_url) DO UPDATE SET
                        listing_title_clean = EXCLUDED.listing_title_clean,
                        price = EXCLUDED.price,
                        city = EXCLUDED.city,
                        district = EXCLUDED.district,
                        scraped_at = EXCLUDED.scraped_at,
                        batch_id = EXCLUDED.batch_id;
                    """,
                    clean_records,
                )
            for record in feature_records:
                cursor.execute(
                    """
                    INSERT INTO clean.clean_listing_features (
                        listing_url, surface_m2, bedrooms, bathrooms, floor, price_per_m2, batch_id
                    )
                    VALUES (
                        %(listing_url)s, %(surface_m2)s, %(bedrooms)s, %(bathrooms)s,
                        %(floor)s, %(price_per_m2)s, %(batch_id)s
                    )
                    ON CONFLICT (listing_url) DO UPDATE SET
                        surface_m2 = EXCLUDED.surface_m2,
                        bedrooms = EXCLUDED.bedrooms,
                        bathrooms = EXCLUDED.bathrooms,
                        floor = EXCLUDED.floor,
                        price_per_m2 = EXCLUDED.price_per_m2,
                        batch_id = EXCLUDED.batch_id;
                    """,
                    record,
                )
        connection.commit()

    logger = get_logger(__name__)
    log_event(
        logger,
        logging.INFO,
        "clean_csv_loaded_to_clean_table",
        batch_id=batch_id,
        clean_rows=len(clean_records),
        feature_rows=len(feature_records),
        skipped_clean_rows=clean_result.skipped_rows,
        skipped_feature_rows=feature_result.skipped_rows,
    )
    return len(clean_records)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean an Avito raw CSV into BI and ML-ready CSVs.")
    parser.add_argument("--input-file", type=Path, default=None, help="Raw CSV to clean.")
    parser.add_argument("--batch-id", default=None, help="Batch id to use in output filenames.")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact quality report summary after writing outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_file = args.input_file or latest_raw_file()
    result = clean_raw_csv_to_clean_csv(input_file, args.batch_id)
    print("Cleaning completed successfully.")
    print(f"Core file saved to: {result.clean_file}")
    print(f"Features file saved to: {result.features_file}")
    print(f"Quality report saved to: {result.quality_report}")
    if args.summary:
        report = json.loads(result.quality_report.read_text(encoding="utf-8"))
        summary_keys = [
            "raw_rows",
            "after_dedup_rows",
            "clean_rows",
            "removed_duplicates",
            "invalid_reasons_count",
            "optional_completeness_percent",
            "quality_warnings",
        ]
        print(json.dumps({key: report.get(key) for key in summary_keys}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
