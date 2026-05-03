from __future__ import annotations

import html
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse


RAW_OUTPUT_CSV_COLUMNS = [
    "listing_title_raw",
    "price_raw",
    "city_raw",
    "district_raw",
    "surface_raw",
    "bedrooms_raw",
    "bathrooms_raw",
    "floor_raw",
    "construction_year_raw",
    "listing_url",
    "scraped_at",
    "batch_id",
    "source",
]

RAW_CSV_COLUMNS = [*RAW_OUTPUT_CSV_COLUMNS, "listing_title"]

CLEAN_CORE_CSV_COLUMNS = [
    "listing_title_clean",
    "price",
    "city",
    "district",
    "listing_url",
    "scraped_at",
    "batch_id",
]

CLEAN_FEATURE_CSV_COLUMNS = [
    "listing_url",
    "surface_m2",
    "bedrooms",
    "bathrooms",
    "floor",
    "price_per_m2",
]

CLEAN_INTERNAL_FIELDS = [
    "listing_title_clean",
    "price",
    "city",
    "district",
    "surface_m2",
    "bedrooms",
    "bathrooms",
    "floor",
    "construction_year",
    "price_per_m2",
    "property_age",
    "listing_url",
    "scraped_at",
    "batch_id",
]

CLEAN_CSV_COLUMNS = CLEAN_CORE_CSV_COLUMNS

LEGACY_ALLOWED_FIELDS = {
    "listing_title",
    "listing_title_raw",
    "price",
    "city",
    "district",
    "surface_m2",
    "bedrooms",
    "bathrooms",
    "floor",
    "construction_year",
    "listing_url",
    "scraped_at",
    "batch_id",
    "source",
}

RAW_ALLOWED_FIELDS = set(RAW_OUTPUT_CSV_COLUMNS)
CLEAN_ALLOWED_FIELDS = set(CLEAN_INTERNAL_FIELDS)
ALLOWED_FIELDS = RAW_ALLOWED_FIELDS | CLEAN_ALLOWED_FIELDS | LEGACY_ALLOWED_FIELDS
CLEAN_NUMERIC_FIELDS = {
    "price",
    "surface_m2",
    "bedrooms",
    "bathrooms",
    "floor",
    "construction_year",
    "price_per_m2",
    "property_age",
}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
MOROCCO_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?212|0)[\s.\-]?[567][\s.\-]?(?:\d[\s.\-]?){7,8}(?!\d)"
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
ADDRESS_HINT_RE = re.compile(
    r"\b(?:rue|avenue|boulevard|bd|residence|résidence|immeuble|apartment|"
    r"appartement|lot|numero|num|n°)\b",
    re.IGNORECASE,
)


def contains_personal_data(value: str | None) -> bool:
    if not value:
        return False
    return bool(EMAIL_RE.search(value) or MOROCCO_PHONE_RE.search(value))


def redact_personal_data(value: str) -> str:
    value = EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = MOROCCO_PHONE_RE.sub("[REDACTED_PHONE]", value)
    return value


def repair_mojibake(value: str) -> str:
    if not any(marker in value for marker in ("Ã", "Â")):
        return value
    try:
        return value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value


def sanitize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = repair_mojibake(html.unescape(str(value)))
    text = HTML_TAG_RE.sub(" ", text)
    text = redact_personal_data(text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text or None


def normalize_listing_url(url: str | None, base_url: str = "https://www.avito.ma") -> str | None:
    if not url:
        return None
    parsed = urlparse(urljoin(base_url, url.strip()))
    host = parsed.netloc.lower()
    if host not in {"www.avito.ma", "avito.ma"}:
        return None
    clean_path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme or "https", parsed.netloc, clean_path, "", "", ""))


def _sanitize_location(value: Any) -> str | None:
    text = sanitize_text(value)
    if text and ADDRESS_HINT_RE.search(text):
        return None
    return text


def sanitize_raw_listing_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return only non-personal raw real-estate fields in the CSV contract."""

    raw_record = {
        "listing_title_raw": record.get("listing_title_raw") or record.get("listing_title"),
        "price_raw": record.get("price_raw", record.get("price")),
        "city_raw": record.get("city_raw", record.get("city")),
        "district_raw": record.get("district_raw", record.get("district")),
        "surface_raw": record.get("surface_raw", record.get("surface_m2")),
        "bedrooms_raw": record.get("bedrooms_raw", record.get("bedrooms")),
        "bathrooms_raw": record.get("bathrooms_raw", record.get("bathrooms")),
        "floor_raw": record.get("floor_raw", record.get("floor")),
        "construction_year_raw": record.get(
            "construction_year_raw", record.get("construction_year")
        ),
        "listing_url": normalize_listing_url(record.get("listing_url")),
        "scraped_at": record.get("scraped_at"),
        "batch_id": record.get("batch_id"),
        "source": record.get("source"),
    }

    sanitized: dict[str, Any] = {}
    for field in RAW_OUTPUT_CSV_COLUMNS:
        if field == "listing_url":
            sanitized[field] = raw_record[field]
        elif field in {"city_raw", "district_raw"}:
            sanitized[field] = _sanitize_location(raw_record[field])
        else:
            sanitized[field] = sanitize_text(raw_record[field])
    return sanitized


def sanitize_clean_listing_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return only clean analytical fields in the clean CSV contract."""

    clean_record = {
        "listing_title_clean": record.get("listing_title_clean", record.get("listing_title")),
        "price": record.get("price"),
        "city": record.get("city"),
        "district": record.get("district"),
        "surface_m2": record.get("surface_m2", record.get("surface_raw")),
        "bedrooms": record.get("bedrooms", record.get("bedrooms_raw")),
        "bathrooms": record.get("bathrooms", record.get("bathrooms_raw")),
        "floor": record.get("floor", record.get("floor_raw")),
        "construction_year": record.get(
            "construction_year", record.get("construction_year_raw")
        ),
        "price_per_m2": record.get("price_per_m2"),
        "property_age": record.get("property_age"),
        "listing_url": normalize_listing_url(record.get("listing_url")),
        "scraped_at": record.get("scraped_at"),
        "batch_id": record.get("batch_id"),
    }

    sanitized: dict[str, Any] = {}
    for field in CLEAN_INTERNAL_FIELDS:
        if field == "listing_url":
            sanitized[field] = clean_record[field]
        elif field in {"city", "district"}:
            sanitized[field] = _sanitize_location(clean_record[field])
        elif field in CLEAN_NUMERIC_FIELDS:
            sanitized[field] = clean_record[field] if clean_record[field] not in {"", None} else None
        else:
            sanitized[field] = sanitize_text(clean_record[field])
    return sanitized


def sanitize_listing_record(record: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible sanitizer for legacy tests and helper callers."""

    sanitized: dict[str, Any] = {}
    for field in LEGACY_ALLOWED_FIELDS:
        value = record.get(field)
        if field == "listing_url":
            sanitized[field] = normalize_listing_url(value)
        elif field in {"city", "district"}:
            sanitized[field] = _sanitize_location(value)
        else:
            sanitized[field] = sanitize_text(value)
    return sanitized


def has_disallowed_fields(
    record: dict[str, Any],
    allowed_fields: Iterable[str] | None = None,
) -> bool:
    allowed = set(allowed_fields or ALLOWED_FIELDS)
    return any(field not in allowed for field in record)


def assert_compliant_record(
    record: dict[str, Any],
    allowed_fields: Iterable[str] | None = None,
) -> None:
    allowed = set(allowed_fields or ALLOWED_FIELDS)
    if has_disallowed_fields(record, allowed):
        extra = sorted(set(record) - allowed)
        raise ValueError(f"Disallowed fields detected: {extra}")

    for field, value in record.items():
        if field in {"listing_url", "source", "batch_id", "scraped_at"}:
            continue
        if contains_personal_data(str(value) if value is not None else None):
            raise ValueError(f"Personal data detected in field: {field}")
