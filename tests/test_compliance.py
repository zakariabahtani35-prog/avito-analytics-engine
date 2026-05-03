import pytest

from src.utils.compliance import (
    assert_compliant_record,
    contains_personal_data,
    normalize_listing_url,
    sanitize_listing_record,
    sanitize_text,
)


def test_sanitize_text_redacts_email_and_phone() -> None:
    value = sanitize_text("Contact: test@example.com / 0612345678")

    assert value == "Contact: [REDACTED_EMAIL] / [REDACTED_PHONE]"
    assert not contains_personal_data(value)


def test_sanitize_listing_record_keeps_only_allowed_fields() -> None:
    record = sanitize_listing_record(
        {
            "listing_title": "Appartement",
            "seller_name": "Not allowed",
            "phone": "0612345678",
            "listing_url": "https://www.avito.ma/fr/test/listing_123?utm=abc",
        }
    )

    assert "seller_name" not in record
    assert "phone" not in record
    assert record["listing_url"] == "https://www.avito.ma/fr/test/listing_123"
    assert_compliant_record(record)


def test_assert_compliant_record_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        assert_compliant_record({"listing_title": "Appartement", "email": "x@y.com"})


def test_location_address_hint_is_removed() -> None:
    record = sanitize_listing_record(
        {
            "city": "Casablanca",
            "district": "Rue Example 12",
            "listing_url": "https://www.avito.ma/fr/test/listing_123",
        }
    )

    assert record["city"] == "Casablanca"
    assert record["district"] is None


def test_normalize_listing_url_rejects_external_hosts() -> None:
    assert normalize_listing_url("https://example.com/a") is None
    assert normalize_listing_url("/fr/test/listing_123") == "https://www.avito.ma/fr/test/listing_123"
