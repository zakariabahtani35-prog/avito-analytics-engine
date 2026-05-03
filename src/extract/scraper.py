from __future__ import annotations

import csv
import argparse
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag

from src.config.settings import Settings, get_settings
from src.utils.compliance import (
    RAW_ALLOWED_FIELDS,
    RAW_OUTPUT_CSV_COLUMNS,
    assert_compliant_record,
    normalize_listing_url,
    sanitize_raw_listing_record,
    sanitize_text,
)
from src.utils.logger import get_logger, log_event


USER_AGENTS = [
    "Mozilla/5.0 (compatible; AvitoAcademicPipeline/1.0; +https://github.com/academic)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
]

PRICE_NUMBER_PATTERN = r"(?:\d{1,3}(?:[\s.]\d{3})+(?:[,.]\d{1,2})?|\d{2,}(?:[,.]\d{1,2})?)"
PRICE_RE = re.compile(
    rf"(?P<number>{PRICE_NUMBER_PATTERN})\s*(?P<currency>dh|dhs|mad|dirhams?)\b",
    re.IGNORECASE,
)
MILLION_PRICE_RE = re.compile(
    r"\b\d+(?:[,.]\d+)?\s*(?:million|millions)\s*(?:dh|dhs|mad|dirhams?)?\b",
    re.IGNORECASE,
)
SURFACE_RE = re.compile(
    r"(?<!\d)(?P<surface>\d{1,5}(?:[,.]\d{1,2})?)\s*(?:m2|m²|mÂ²|m\^2)\b",
    re.IGNORECASE,
)
SURFACE_KEYWORD_RE = re.compile(
    r"\bsurface\D{0,20}(?P<surface>\d{1,5}(?:[,.]\d{1,2})?)\b",
    re.IGNORECASE,
)
BEDROOM_RE = re.compile(r"(?<!\d)(?P<count>\d{1,2})\s*(?:chambres?|pieces?|pièces?)\b", re.IGNORECASE)
BATHROOM_RE = re.compile(
    r"(?<!\d)(?P<count>\d{1,2})\s*(?:sdbs?|bains?|salles?\s+de\s+bain)\b",
    re.IGNORECASE,
)
FLOOR_RE = re.compile(
    r"\b(?:étage|etage|niveau)\s*(?P<floor>-?\d{1,2})\b|"
    r"\b(?P<floor_before>-?\d{1,2})(?:er|eme|e|ème)?\s*(?:étage|etage|niveau)\b|"
    r"\b(?:rdc|rez\s+de\s+chaussée|rez\s+de\s+chaussee)\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(
    r"\b(?:construction|construit|année|annee)\D{0,20}(18\d{2}|19\d{2}|20\d{2})\b",
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
NOISE_LOCATION_RE = re.compile(
    r"\b(?:il y a|premium|star|contacter|demander|prix|dh|mad|vendeur)\b|/\d+",
    re.IGNORECASE,
)

TITLE_SELECTORS = [
    '[data-testid*="title"]',
    '[class*="title"]',
    "h1",
    "h2",
    "h3",
]
PRICE_SELECTORS = [
    '[data-testid*="price"]',
    '[class*="price"]',
    '[aria-label*="prix"]',
    '[aria-label*="Prix"]',
]
LOCATION_SELECTORS = [
    '[data-testid*="location"]',
    '[data-testid*="city"]',
    '[class*="location"]',
    '[class*="city"]',
    '[class*="address"]',
]
FEATURE_SELECTORS = [
    '[data-testid*="feature"]',
    '[data-testid*="attribute"]',
    '[class*="feature"]',
    '[class*="attribute"]',
    '[class*="detail"]',
    "li",
    "span",
]
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
    "casablanca",
    "rabat",
    "marrakech",
    "tanger",
    "agadir",
    "fes",
    "fès",
    "meknes",
    "oujda",
    "tetouan",
    "tétouan",
    "mohammedia",
    "bouskoura",
    "sale",
    "salé",
    "kenitra",
    "kénitra",
    "el_jadida",
    "ifrane",
    "dcheira",
}


class ScrapingStopped(RuntimeError):
    """Raised when scraping must stop for compliance or remote-site safety."""


@dataclass(frozen=True)
class FetchResult:
    html: str
    status_code: int


@dataclass(frozen=True)
class ScrapeResult:
    batch_id: str
    raw_file: Path
    records_count: int


class AvitoScraper:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger(__name__)
        self.session = requests.Session()
        self.blocked_responses = 0
        self.robot_parser = self._load_robots_parser()

    def scrape(self, batch_id: str) -> ScrapeResult:
        records_by_url: dict[str, dict[str, Any]] = {}
        empty_pages = 0

        for page in range(1, self.settings.scraper_max_pages + 1):
            page_url = self._build_page_url(page)
            if not self._can_fetch(page_url):
                raise ScrapingStopped(f"robots.txt does not allow scraping: {page_url}")

            fetch_result = self._fetch_html(page_url, page=page)
            if not fetch_result:
                empty_pages += 1
                if empty_pages >= self.settings.scraper_max_empty_pages:
                    break
                self._polite_delay()
                continue

            page_records = self._parse_search_page(fetch_result.html, batch_id)
            log_event(
                self.logger,
                logging.INFO,
                "scrape_page_completed",
                page=page,
                status_code=fetch_result.status_code,
                records_found=len(page_records),
                total_records=len(records_by_url),
            )

            if not page_records:
                empty_pages += 1
                if empty_pages >= self.settings.scraper_max_empty_pages:
                    log_event(
                        self.logger,
                        logging.INFO,
                        "scrape_stopped_empty_pages",
                        page=page,
                        empty_pages=empty_pages,
                    )
                    break
                self._polite_delay()
                continue

            empty_pages = 0
            for record in page_records:
                if self.settings.fetch_detail_pages and record.get("listing_url"):
                    self._enrich_from_detail_page(record)
                safe_record = sanitize_raw_listing_record(record)
                safe_record["batch_id"] = batch_id
                safe_record["source"] = "avito.ma"
                assert_compliant_record(safe_record, RAW_ALLOWED_FIELDS)
                listing_url = safe_record.get("listing_url")
                if listing_url:
                    records_by_url[listing_url] = safe_record

            if len(records_by_url) >= self.settings.scraper_target_listings:
                log_event(
                    self.logger,
                    logging.INFO,
                    "scrape_target_reached",
                    target_listings=self.settings.scraper_target_listings,
                    total_records=len(records_by_url),
                    page=page,
                )
                break

            self._polite_delay()

        if len(records_by_url) < self.settings.scraper_target_listings:
            log_event(
                self.logger,
                logging.WARNING,
                "scrape_target_not_reached",
                target_listings=self.settings.scraper_target_listings,
                total_records=len(records_by_url),
                max_pages=self.settings.scraper_max_pages,
            )

        raw_file = self._write_raw_file(batch_id, list(records_by_url.values()))
        return ScrapeResult(
            batch_id=batch_id,
            raw_file=raw_file,
            records_count=len(records_by_url),
        )

    def _load_robots_parser(self) -> RobotFileParser | None:
        parsed = urlparse(self.settings.avito_search_url)
        robots_url = urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self.session.get(
                robots_url,
                timeout=self.settings.scraper_timeout_seconds,
                headers={"User-Agent": USER_AGENTS[0]},
            )
            response.raise_for_status()
            parser.parse(response.text.splitlines())
            log_event(self.logger, logging.INFO, "robots_loaded", status=response.status_code)
            return parser
        except requests.RequestException as exc:
            log_event(
                self.logger,
                logging.WARNING,
                "robots_load_failed",
                error=exc.__class__.__name__,
            )
            if self.settings.robots_strict:
                raise ScrapingStopped("robots.txt could not be read in strict mode") from exc
            return None

    def _can_fetch(self, url: str) -> bool:
        if self.robot_parser is None:
            return True
        return self.robot_parser.can_fetch(USER_AGENTS[0], url)

    def _build_page_url(self, page: int) -> str:
        if "{page}" in self.settings.avito_search_url:
            return self.settings.avito_search_url.format(page=page)
        if page == 1:
            return self.settings.avito_search_url

        parsed = urlparse(self.settings.avito_search_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["o"] = str(page)
        return urlunparse(parsed._replace(query=urlencode(query)))

    def _fetch_html(self, url: str, page: int | None = None) -> FetchResult | None:
        for attempt in range(1, self.settings.scraper_max_retries + 1):
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
            }
            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=self.settings.scraper_timeout_seconds,
                )
            except requests.RequestException as exc:
                log_event(
                    self.logger,
                    logging.WARNING,
                    "request_failed",
                    page=page,
                    attempt=attempt,
                    error=exc.__class__.__name__,
                )
                self._backoff(attempt)
                continue

            log_event(
                self.logger,
                logging.INFO,
                "page_fetch_status",
                page=page,
                attempt=attempt,
                status_code=response.status_code,
            )

            if response.status_code in {403, 429}:
                self.blocked_responses += 1
                log_event(
                    self.logger,
                    logging.WARNING,
                    "scraping_blocked_status",
                    page=page,
                    status=response.status_code,
                    blocked_responses=self.blocked_responses,
                )
                if self.blocked_responses >= self.settings.scraper_max_blocked_responses:
                    raise ScrapingStopped(
                        f"Stopped safely after HTTP {response.status_code} responses"
                    )
                self._backoff(attempt, status_code=response.status_code)
                continue

            if 500 <= response.status_code < 600:
                log_event(
                    self.logger,
                    logging.WARNING,
                    "server_error_retry",
                    page=page,
                    attempt=attempt,
                    status=response.status_code,
                )
                self._backoff(attempt, status_code=response.status_code)
                continue

            if response.status_code == 404:
                return None

            response.raise_for_status()
            return FetchResult(html=response.text, status_code=response.status_code)

        return None

    def _parse_search_page(self, html: str, batch_id: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        scraped_at = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
        records = self._parse_json_ld(soup, scraped_at, batch_id)
        records.extend(self._parse_listing_anchors(soup, scraped_at, batch_id))

        deduped: dict[str, dict[str, Any]] = {}
        for record in records:
            url = record.get("listing_url")
            if url:
                merged = deduped.get(url, {}).copy()
                merged.update({key: value for key, value in record.items() if value is not None})
                deduped[url] = merged
        return list(deduped.values())

    def _parse_json_ld(
        self,
        soup: BeautifulSoup,
        scraped_at: str,
        batch_id: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for script in soup.select('script[type="application/ld+json"]'):
            payload = script.string or script.get_text(strip=True)
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for item in self._walk_json(data):
                if not isinstance(item, dict):
                    continue
                url = item.get("url") or item.get("@id")
                listing_url = normalize_listing_url(str(url) if url else None)
                if not listing_url or not self._looks_like_listing_url(listing_url):
                    continue

                offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
                url_city, url_district = self._location_from_url(listing_url)
                records.append(
                    {
                        "listing_title_raw": sanitize_text(item.get("name")),
                        "price_raw": sanitize_text(offers.get("price") or item.get("price")),
                        "city_raw": url_city,
                        "district_raw": url_district,
                        "listing_url": listing_url,
                        "scraped_at": scraped_at,
                        "batch_id": batch_id,
                        "source": "avito.ma",
                    }
                )
        return records

    def _walk_json(self, value: Any) -> list[Any]:
        found = [value]
        if isinstance(value, dict):
            for nested in value.values():
                found.extend(self._walk_json(nested))
        elif isinstance(value, list):
            for nested in value:
                found.extend(self._walk_json(nested))
        return found

    def _parse_listing_anchors(
        self,
        soup: BeautifulSoup,
        scraped_at: str,
        batch_id: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for anchor in soup.select("a[href]"):
            listing_url = normalize_listing_url(anchor.get("href"))
            if not listing_url or not self._looks_like_listing_url(listing_url):
                continue

            card = self._nearest_card(anchor)
            text = sanitize_text(card.get_text(" ", strip=True) if card else anchor.get_text(" "))
            title = self._extract_title(card, anchor)
            city_raw, district_raw = self._extract_location(card, text)
            url_city, url_district = self._location_from_url(listing_url)

            record = {
                "listing_title_raw": title,
                "price_raw": self._extract_price_text(card, text),
                "city_raw": city_raw or url_city,
                "district_raw": district_raw or url_district,
                "surface_raw": self._extract_surface_text(card, text),
                "bedrooms_raw": self._extract_bedrooms_text(card, text),
                "bathrooms_raw": self._extract_bathrooms_text(card, text),
                "floor_raw": self._extract_floor_text(card, text),
                "construction_year_raw": self._extract_construction_year_text(card, text),
                "listing_url": listing_url,
                "scraped_at": scraped_at,
                "batch_id": batch_id,
                "source": "avito.ma",
            }
            records.append(sanitize_raw_listing_record(record))
        return records

    def _looks_like_listing_url(self, url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.lower()
        if any(blocked in path for blocked in ["/login", "/profile", "/boutiques", "/shops"]):
            return False
        if path.count("/") < 3:
            return False
        if not path.endswith(".htm") and not re.search(r"_[0-9]{6,}", path):
            return False
        return "avito.ma" in parsed.netloc.lower()

    def _nearest_card(self, anchor: Tag) -> Tag:
        for depth, parent in enumerate(anchor.parents):
            if depth > 8:
                break
            if not isinstance(parent, Tag):
                continue

            text = parent.get_text(" ", strip=True)
            if len(text) > 1600:
                continue

            listing_links = {
                normalized
                for link in parent.select("a[href]")
                if (normalized := normalize_listing_url(link.get("href")))
                and self._looks_like_listing_url(normalized)
            }
            if len(listing_links) > 2:
                continue

            classes = " ".join(parent.get("class", [])).lower()
            testid = str(parent.get("data-testid", "")).lower()
            card_hint = any(
                hint in f"{classes} {testid}"
                for hint in ["listing", "ad-card", "adcard", "classified", "item"]
            )
            if parent.name in {"article", "li"} or card_hint:
                return parent
        return anchor

    def _extract_title(self, card: Tag | None, anchor: Tag) -> str | None:
        href = normalize_listing_url(anchor.get("href"))
        url_title = self._title_from_url(href)
        if url_title:
            return url_title

        for attribute in ("title", "aria-label"):
            attribute_title = sanitize_text(anchor.get(attribute))
            if attribute_title and len(attribute_title) <= 220 and not looks_like_card_noise(attribute_title):
                return attribute_title

        title = first_short_text(card, TITLE_SELECTORS, max_length=220) if card else None
        if title and not looks_like_card_noise(title):
            return title
        anchor_text = sanitize_text(anchor.get_text(" ", strip=True))
        if anchor_text and len(anchor_text) <= 220 and not looks_like_card_noise(anchor_text):
            return anchor_text
        return title or anchor_text

    def _title_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        path = unquote(urlparse(url).path)
        slug = Path(path).stem
        slug = re.sub(r"_[0-9]+$", "", slug)
        slug = slug.replace("_", " ")
        return sanitize_text(slug)

    def _extract_price_text(self, card: Tag | None, fallback_text: str | None) -> str | None:
        price = first_short_text(card, PRICE_SELECTORS, max_length=80) if card else None
        if price:
            return price
        return extract_price_candidate(fallback_text)

    def _extract_location(
        self,
        card: Tag | None,
        fallback_text: str | None,
    ) -> tuple[str | None, str | None]:
        candidates: list[str] = []
        if card:
            structured = first_short_text(card, LOCATION_SELECTORS, max_length=140)
            if structured:
                candidates.append(structured)
        if fallback_text:
            candidates.append(fallback_text)

        for candidate in candidates:
            city, district = parse_location_candidate(candidate)
            if city or district:
                return city, district
        return None, None

    def _extract_surface_text(self, card: Tag | None, text: str | None) -> str | None:
        candidate = first_feature_text(card, ["surface", "m2", "m²"]) if card else None
        return extract_surface_candidate(candidate) or extract_surface_candidate(text)

    def _extract_bedrooms_text(self, card: Tag | None, text: str | None) -> str | None:
        candidate = first_feature_text(card, ["chambre", "piece", "pièce", "studio"]) if card else None
        return extract_bedroom_candidate(candidate) or extract_bedroom_candidate(text)

    def _extract_bathrooms_text(self, card: Tag | None, text: str | None) -> str | None:
        candidate = first_feature_text(card, ["sdb", "bain", "salle de bain"]) if card else None
        return extract_bathroom_candidate(candidate) or extract_bathroom_candidate(text)

    def _extract_floor_text(self, card: Tag | None, text: str | None) -> str | None:
        candidate = first_feature_text(card, ["étage", "etage", "niveau", "rdc", "rez"]) if card else None
        return extract_floor_candidate(candidate) or extract_floor_candidate(text)

    def _extract_construction_year_text(self, card: Tag | None, text: str | None) -> str | None:
        candidate = first_feature_text(card, ["construction", "construit", "année", "annee"]) if card else None
        return extract_year_candidate(candidate) or extract_year_candidate(text)

    def _location_from_url(self, url: str) -> tuple[str | None, str | None]:
        parts = [
            slug_to_label(part)
            for part in unquote(urlparse(url).path).split("/")
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
            return first, None
        return None, first

    def _enrich_from_detail_page(self, record: dict[str, Any]) -> None:
        url = record.get("listing_url")
        if not url or not self._can_fetch(url):
            return
        fetch_result = self._fetch_html(url)
        if not fetch_result:
            return
        soup = BeautifulSoup(fetch_result.html, "lxml")
        text = sanitize_text(soup.get_text(" ", strip=True))
        if not text:
            return
        city_raw, district_raw = self._extract_location(soup, text)
        enrichment = {
            "price_raw": extract_price_candidate(text),
            "city_raw": city_raw,
            "district_raw": district_raw,
            "surface_raw": self._extract_surface_text(soup, text),
            "bedrooms_raw": self._extract_bedrooms_text(soup, text),
            "bathrooms_raw": self._extract_bathrooms_text(soup, text),
            "floor_raw": self._extract_floor_text(soup, text),
            "construction_year_raw": self._extract_construction_year_text(soup, text),
        }
        for key, value in enrichment.items():
            if not record.get(key) and value:
                record[key] = value
        self._polite_delay()

    def _polite_delay(self) -> None:
        jitter = random.uniform(0, self.settings.scraper_delay_seconds * 0.25)
        time.sleep(self.settings.scraper_delay_seconds + jitter)

    def _backoff(self, attempt: int, status_code: int | None = None) -> None:
        base_delay = 10 if status_code == 429 else 2
        max_delay = 180 if status_code == 429 else 60
        retry_after = base_delay * (2 ** (attempt - 1))
        time.sleep(min(max_delay, retry_after + random.uniform(0, base_delay)))

    def _write_raw_file(self, batch_id: str, records: list[dict[str, Any]]) -> Path:
        output_path = self.settings.raw_dir / f"avito_raw_{batch_id}.csv"
        with output_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=RAW_OUTPUT_CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for record in records:
                safe_record = sanitize_raw_listing_record(record)
                assert_compliant_record(safe_record, RAW_ALLOWED_FIELDS)
                writer.writerow({column: safe_record.get(column) for column in RAW_OUTPUT_CSV_COLUMNS})
        log_event(
            self.logger,
            logging.INFO,
            "raw_csv_written",
            batch_id=batch_id,
            records=len(records),
            raw_file=str(output_path),
        )
        return output_path


def first_short_text(card: Tag | None, selectors: list[str], max_length: int) -> str | None:
    if not card:
        return None
    for selector in selectors:
        for node in card.select(selector):
            text = sanitize_text(node.get_text(" ", strip=True))
            if text and len(text) <= max_length:
                return text
    return None


def looks_like_card_noise(text: str | None) -> bool:
    text = sanitize_text(text)
    if not text:
        return False
    return bool(
        re.search(
            r"\b(?:il y a|premium|contacter|demander le prix|prix non spécifié)\b|"
            r"\b\d+/\d+\b",
            text,
            re.IGNORECASE,
        )
    )


def first_feature_text(card: Tag | None, keywords: list[str]) -> str | None:
    if not card:
        return None
    for selector in FEATURE_SELECTORS:
        for node in card.select(selector):
            text = sanitize_text(node.get_text(" ", strip=True))
            if not text or len(text) > 120:
                continue
            lower = text.lower()
            if any(keyword in lower for keyword in keywords):
                return text
    return None


def extract_price_candidate(text: str | None) -> str | None:
    text = sanitize_text(text)
    if not text:
        return None
    if re.search(r"\b(?:demander le prix|prix non spécifié|prix non specifie)\b", text, re.IGNORECASE):
        return "Prix non spécifié"

    candidates: list[tuple[int, str, bool]] = []
    for match in MILLION_PRICE_RE.finditer(text):
        after = text[match.end() : match.end() + 20]
        is_monthly = bool(re.match(r"\s*(?:/|par)\s*mois", after, re.IGNORECASE))
        candidates.append((match.start(), match.group(0), is_monthly))
    for match in PRICE_RE.finditer(text):
        after = text[match.end() : match.end() + 20]
        is_monthly = bool(re.match(r"\s*(?:/|par)\s*mois", after, re.IGNORECASE))
        candidates.append((match.start(), match.group(0), is_monthly))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    non_monthly = [candidate for candidate in candidates if not candidate[2]]
    return sanitize_text((non_monthly or candidates)[0][1])


def extract_surface_candidate(text: str | None) -> str | None:
    text = sanitize_text(text)
    if not text:
        return None
    for pattern in (SURFACE_RE, SURFACE_KEYWORD_RE):
        match = pattern.search(text)
        if match:
            return sanitize_text(f"{match.group('surface')} m²")
    return None


def extract_bedroom_candidate(text: str | None) -> str | None:
    text = sanitize_text(text)
    if not text:
        return None
    if re.search(r"\bstudio\b", text, re.IGNORECASE):
        return "1 chambre"
    match = BEDROOM_RE.search(text)
    if match:
        return sanitize_text(f"{match.group('count')} chambres")
    return None


def extract_bathroom_candidate(text: str | None) -> str | None:
    text = sanitize_text(text)
    if not text:
        return None
    match = BATHROOM_RE.search(text)
    if match:
        return sanitize_text(f"{match.group('count')} sdb")
    return None


def extract_floor_candidate(text: str | None) -> str | None:
    text = sanitize_text(text)
    if not text:
        return None
    match = FLOOR_RE.search(text)
    if not match:
        return None
    if re.search(r"\b(?:rdc|rez\s+de\s+chaussée|rez\s+de\s+chaussee)\b", match.group(0), re.IGNORECASE):
        return "Rez de chaussée"
    floor = match.group("floor") or match.group("floor_before")
    return sanitize_text(f"Étage {floor}") if floor else None


def extract_year_candidate(text: str | None) -> str | None:
    text = sanitize_text(text)
    if not text:
        return None
    match = YEAR_RE.search(text)
    if match:
        return sanitize_text(match.group(0))
    return None


def parse_location_candidate(text: str | None) -> tuple[str | None, str | None]:
    text = sanitize_text(text)
    if not text:
        return None, None

    match = LOCATION_RE.search(text)
    if match:
        city = clean_location_piece(match.group("city"))
        district = clean_location_piece(match.group("district"))
        return city, district

    parts = re_split_location(text)
    useful = [clean_location_piece(part) for part in parts]
    useful = [part for part in useful if part]
    if not useful:
        return None, None
    if len(useful[0]) > 60 or NOISE_LOCATION_RE.search(useful[0]):
        return None, None
    city = useful[0]
    district = useful[1] if len(useful) > 1 and len(useful[1]) <= 60 else None
    return city, district


def clean_location_piece(value: str | None) -> str | None:
    text = sanitize_text(value)
    if not text:
        return None
    text = re.sub(r"\b(?:Toute la ville|Autre secteur)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:Premium|Star)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+/\d+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,-")
    if not text or len(text) > 70 or NOISE_LOCATION_RE.search(text):
        return None
    return text


def slug_to_label(value: str | None) -> str | None:
    text = sanitize_text(unquote(value or ""))
    if not text:
        return None
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.title() if text else None


def re_split_location(value: str) -> list[str]:
    return [
        part.strip()
        for part in value.replace("|", ",").replace(" - ", ",").split(",")
        if part.strip()
    ]


def scrape_to_raw_csv(batch_id: str) -> ScrapeResult:
    return AvitoScraper().scrape(batch_id)


def scrape_avito(batch_id: str) -> ScrapeResult:
    return scrape_to_raw_csv(batch_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape public Avito real-estate listings.")
    parser.add_argument(
        "--batch-id",
        default=datetime.now(UTC).strftime("batch_%Y%m%dT%H%M%SZ"),
        help="Batch id used in the raw CSV filename.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = scrape_to_raw_csv(args.batch_id)
    print("Scraping completed successfully.")
    print(f"Raw file saved to: {result.raw_file}")
    print(f"Records scraped: {result.records_count}")


if __name__ == "__main__":
    main()
