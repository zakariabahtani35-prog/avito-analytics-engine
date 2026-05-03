import csv
import json
from contextlib import contextmanager
from decimal import Decimal

from src.clean.clean_data import (
    REQUIRED_CLEAN_COLUMNS,
    _available_feature_columns,
    _build_feature_rows,
    _read_clean_csv,
    _read_feature_csv,
    build_clean_column_profile,
    clean_listing_title,
    clean_raw_csv_to_clean_csv,
    clean_raw_row,
    load_clean_csv_to_clean_table,
    parse_decimal,
    parse_floor,
    standardize_city,
)
from src.utils.compliance import RAW_CSV_COLUMNS


def test_parse_decimal_handles_moroccan_price_text() -> None:
    assert parse_decimal("1 250 000 DH") == Decimal("1250000.00")
    assert parse_decimal("1.5 million MAD") == Decimal("1500000.00")


def test_parse_floor_handles_ground_floor() -> None:
    assert parse_floor("Rez de chaussee") == 0
    assert parse_floor("RDC") == 0
    assert parse_floor("3eme etage") == 3
    assert parse_floor("0", focused=True) is None
    assert parse_floor("Etage 0") is None


def test_standardize_city_aliases() -> None:
    assert standardize_city("casa") == "Casablanca"
    assert standardize_city("Fes") == "Fès"


def test_clean_raw_row_engineers_features() -> None:
    row = {
        "listing_title": "Appartement lumineux",
        "price": "1 200 000 DH",
        "city": "casa",
        "district": "Maarif",
        "surface_m2": "120 m2",
        "bedrooms": "3 chambres",
        "bathrooms": "2 salles de bain",
        "floor": "4 etage",
        "construction_year": "Construit en 2016",
        "listing_url": "https://www.avito.ma/fr/casablanca/appartements/appartement_12345678",
        "scraped_at": "2026-04-28T12:00:00",
        "batch_id": "batch_test",
    }

    cleaned = clean_raw_row(row, current_year=2026)

    assert cleaned is not None
    assert cleaned["price"] == Decimal("1200000.00")
    assert cleaned["surface_m2"] == Decimal("120.00")
    assert cleaned["price_per_m2"] == Decimal("10000.00")
    assert cleaned["property_age"] == 10
    assert cleaned["city"] == "Casablanca"


def test_clean_raw_row_drops_rows_without_required_analytics_fields() -> None:
    row = {
        "listing_title": "Appartement sans prix",
        "price": None,
        "surface_m2": "100 m2",
        "listing_url": "https://www.avito.ma/fr/rabat/appartements/appartement_12345678",
        "batch_id": "batch_test",
    }

    assert clean_raw_row(row, current_year=2026) is None


def test_clean_raw_row_drops_rows_with_invalid_required_values() -> None:
    row = {
        "listing_title": "Appartement",
        "price": "900000 DH",
        "surface_m2": "90 m2",
        "bedrooms": "999 chambres",
        "bathrooms": "-",
        "floor": "999 etage",
        "construction_year": "1492",
        "listing_url": "https://www.avito.ma/fr/rabat/appartements/appartement_12345678",
        "batch_id": "batch_test",
    }

    assert clean_raw_row(row, current_year=2026) is None


def test_clean_raw_row_keeps_missing_optional_fields_as_null() -> None:
    row = {
        "listing_title": "Appartement lumineux à vendre à Casablanca, Maarif",
        "price_raw": "1 200 000 DH",
        "city_raw": "Casablanca",
        "district_raw": "Maarif",
        "surface_raw": None,
        "bedrooms_raw": "99 chambres",
        "bathrooms_raw": None,
        "floor_raw": None,
        "listing_url": "https://www.avito.ma/fr/maarif/appartements/appartement_12345678.htm",
        "scraped_at": "2026-04-28T12:00:00",
        "batch_id": "batch_test",
        "source": "avito.ma",
    }

    cleaned = clean_raw_row(row, current_year=2026)

    assert cleaned is not None
    assert cleaned["surface_m2"] is None
    assert cleaned["bedrooms"] is None
    assert cleaned["bathrooms"] is None
    assert cleaned["floor"] is None
    assert cleaned["price_per_m2"] is None


def test_clean_raw_row_prefers_listing_specific_values_from_title() -> None:
    row = {
        "listing_title": (
            "GROUP JNANE NIZAR il y a 23 heures Premium 1/15 "
            "Appartements dans Marrakech, Guéliz Appartement à vendre 83 m² "
            "à semlalia, guéliz 2 chambres 2 sdbs 84 m² Étage 1 "
            "1 550 000 DH 8 615 DH / mois Contacter le Vendeur"
        ),
        "price_raw": (
            "GROUP JNANE NIZAR il y a 23 heures Appartements dans Marrakech, Guéliz "
            "Appartement à vendre 83 m² 1 550 000 DH "
            "Lkayen il y a 18 heures Appartements dans Tanger Appartement 124 m² "
            "1 800 000 DH"
        ),
        "surface_raw": "Appartement de 90 m2 Hay El Qods Appartements 250 DH",
        "listing_url": "https://www.avito.ma/fr/guéliz/appartements/appartement_55811696.htm",
        "scraped_at": "2026-04-28T12:00:00",
        "batch_id": "batch_test",
        "source": "avito.ma",
    }

    cleaned = clean_raw_row(row, current_year=2026)

    assert cleaned is not None
    assert cleaned["price"] == Decimal("1550000.00")
    assert cleaned["surface_m2"] == Decimal("83.00")
    assert cleaned["city"] == "Marrakech"
    assert cleaned["district"] == "Guéliz"
    assert cleaned["price_per_m2"] == Decimal("18674.70")


def test_clean_column_profile_keeps_core_fixed_and_removes_optional_from_core() -> None:
    rows = []
    for index in range(5):
        rows.append(
            {
                "listing_title_clean": f"Appartement lumineux {index}",
                "price": Decimal("1000000.00"),
                "city": "Casablanca",
                "district": "Maarif",
                "listing_url": f"https://www.avito.ma/fr/test/listing_{index}",
                "scraped_at": "2026-04-28T12:00:00",
                "batch_id": "batch_test",
                "surface_m2": Decimal("100.00") if index < 3 else None,
                "bedrooms": 2 if index < 2 else None,
                "bathrooms": None,
                "floor": 1 if index < 4 else None,
                "price_per_m2": Decimal("10000.00") if index < 3 else None,
                "construction_year": 2020 if index < 3 else None,
                "property_age": 6 if index < 3 else None,
            }
        )

    profile = build_clean_column_profile(rows)

    assert profile.columns_kept == REQUIRED_CLEAN_COLUMNS
    assert "surface_m2" in profile.columns_removed
    assert "floor" in profile.columns_removed
    assert "price_per_m2" in profile.columns_removed
    assert "bedrooms" in profile.columns_removed
    assert "bathrooms" in profile.columns_removed
    assert profile.missing_percentage_by_column["surface_m2"] == 40.0
    assert profile.missing_percentage_by_column["bedrooms"] == 60.0
    assert all(count == 0 for count in profile.required_null_counts.values())


def test_feature_rows_use_fixed_ml_schema() -> None:
    rows = [
        {
            "listing_url": "https://www.avito.ma/fr/test/listing_1",
            "surface_m2": Decimal("100.00"),
            "bedrooms": 2,
            "bathrooms": 1,
            "floor": 0,
            "price_per_m2": Decimal("10000.00"),
        },
        {
            "listing_url": "https://www.avito.ma/fr/test/listing_2",
            "surface_m2": Decimal("80.00"),
            "bedrooms": None,
            "bathrooms": None,
            "floor": None,
            "price_per_m2": Decimal("12500.00"),
        },
    ]

    feature_columns = _available_feature_columns(rows)
    feature_rows = _build_feature_rows(rows, feature_columns)

    assert feature_columns == ["surface_m2", "bedrooms", "bathrooms", "floor", "price_per_m2"]
    assert len(feature_rows) == 2
    assert feature_rows[0]["bedrooms"] == 2
    assert feature_rows[1]["bathrooms"] is None


def test_clean_raw_csv_to_clean_csv_writes_core_and_features_outputs(tmp_path, monkeypatch) -> None:
    class DummySettings:
        clean_dir = tmp_path

    raw_file = tmp_path / "raw.csv"
    with raw_file.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=RAW_CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "listing_title": (
                    "Appartement lumineux a vendre a Casablanca, Maarif "
                    "100 m2 2 chambres 1 sdb 1 000 000 DH"
                ),
                "price_raw": "1 000 000 DH",
                "city_raw": "Casablanca",
                "district_raw": "Maarif",
                "surface_raw": "100 m2",
                "bedrooms_raw": "2 chambres",
                "bathrooms_raw": "1 sdb",
                "floor_raw": "",
                "construction_year_raw": "",
                "listing_url": "https://www.avito.ma/fr/test/listing_123",
                "scraped_at": "2026-04-28T12:00:00",
                "batch_id": "batch_test",
                "source": "avito.ma",
            }
        )

    monkeypatch.setattr("src.clean.clean_data.get_settings", lambda: DummySettings())

    result = clean_raw_csv_to_clean_csv(raw_file, "batch_test")

    assert result.clean_file.name == "avito_clean_core_batch_test.csv"
    assert result.features_file.name == "avito_clean_features_batch_test.csv"
    with result.clean_file.open("r", encoding="utf-8", newline="") as file:
        assert csv.DictReader(file).fieldnames == REQUIRED_CLEAN_COLUMNS
    with result.features_file.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames == [
            "listing_url",
            "surface_m2",
            "bedrooms",
            "bathrooms",
            "floor",
            "price_per_m2",
        ]
        feature_rows = list(reader)
    assert feature_rows[0]["surface_m2"] == "100.00"
    assert feature_rows[0]["floor"] == ""
    assert feature_rows[0]["price_per_m2"] == "10000.00"

    report = json.loads(result.quality_report.read_text(encoding="utf-8"))
    assert report["core_row_count"] == 1
    assert report["features_row_count"] == 1
    assert report["required_null_counts"] == dict.fromkeys(REQUIRED_CLEAN_COLUMNS, 0)
    assert "surface_m2" in report["columns_removed_from_core"]
    assert report["optional_completeness_percent"]["surface_m2"] == 100.0


def test_clean_raw_csv_drops_rows_rejected_by_loader_sanitizer(tmp_path, monkeypatch) -> None:
    class DummySettings:
        clean_dir = tmp_path

    raw_file = tmp_path / "raw.csv"
    valid_url = "https://www.avito.ma/fr/test/listing_valid"
    invalid_url = "https://www.avito.ma/fr/rue-example/appartements/listing_invalid"
    with raw_file.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=RAW_CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(
            {
                "listing_title": "Appartement lumineux a vendre 100 m2 2 chambres 1 sdb 1 000 000 DH",
                "price_raw": "1 000 000 DH",
                "city_raw": "Casablanca",
                "district_raw": "Maarif",
                "surface_raw": "100 m2",
                "bedrooms_raw": "2 chambres",
                "bathrooms_raw": "1 sdb",
                "floor_raw": "",
                "construction_year_raw": "",
                "listing_url": valid_url,
                "scraped_at": "2026-04-28T12:00:00",
                "batch_id": "batch_test",
                "source": "avito.ma",
            }
        )
        writer.writerow(
            {
                "listing_title": "Appartement familial a vendre 90 m2 2 chambres 1 sdb 900 000 DH",
                "price_raw": "900 000 DH",
                "city_raw": "Casablanca",
                "district_raw": "",
                "surface_raw": "90 m2",
                "bedrooms_raw": "2 chambres",
                "bathrooms_raw": "1 sdb",
                "floor_raw": "",
                "construction_year_raw": "",
                "listing_url": invalid_url,
                "scraped_at": "2026-04-28T12:00:00",
                "batch_id": "batch_test",
                "source": "avito.ma",
            }
        )

    monkeypatch.setattr("src.clean.clean_data.get_settings", lambda: DummySettings())

    result = clean_raw_csv_to_clean_csv(raw_file, "batch_test")

    with result.clean_file.open("r", encoding="utf-8", newline="") as file:
        core_rows = list(csv.DictReader(file))
    with result.features_file.open("r", encoding="utf-8", newline="") as file:
        feature_rows = list(csv.DictReader(file))
    report = json.loads(result.quality_report.read_text(encoding="utf-8"))

    assert [row["listing_url"] for row in core_rows] == [valid_url]
    assert [row["listing_url"] for row in feature_rows] == [valid_url]
    assert report["clean_rows"] == 1
    assert report["removed_missing_district"] == 1
    assert report["invalid_reasons_count"]["missing_district"] == 1


def test_read_core_and_feature_csvs_keep_optional_values_separate(tmp_path) -> None:
    clean_file = tmp_path / "clean.csv"
    clean_file.write_text(
        "\n".join(
            [
                "listing_title_clean,price,city,district,listing_url,scraped_at,batch_id",
                (
                    "Appartement lumineux centre,1000000,Casablanca,Maarif,"
                    "https://www.avito.ma/fr/test/listing_123,"
                    "2026-04-28T12:00:00,batch_test"
                ),
            ]
        ),
        encoding="utf-8",
    )
    features_file = tmp_path / "features.csv"
    features_file.write_text(
        "\n".join(
            [
                "listing_url,surface_m2,bedrooms,bathrooms,floor,price_per_m2",
                "https://www.avito.ma/fr/test/listing_123,100,2,1,0,10000",
            ]
        ),
        encoding="utf-8",
    )

    records = _read_clean_csv(clean_file, "batch_test").records
    feature_records = _read_feature_csv(features_file, "batch_test").records

    assert records[0]["surface_m2"] is None
    assert records[0]["price_per_m2"] is None
    assert feature_records[0]["surface_m2"] == Decimal("100.00")
    assert feature_records[0]["bedrooms"] == 2
    assert feature_records[0]["price_per_m2"] == Decimal("10000.00")


def test_read_clean_csv_skips_invalid_rows_without_raising(tmp_path) -> None:
    clean_file = tmp_path / "clean.csv"
    clean_file.write_text(
        "\n".join(
            [
                "listing_title_clean,price,city,district,listing_url,scraped_at,batch_id",
                (
                    "appartement lumineux centre,1000000,casablanca,maarif,"
                    "https://www.avito.ma/fr/test/listing_valid,"
                    "2026-04-28T12:00:00,batch_test"
                ),
                (
                    "appartement lumineux centre,not-a-price,casablanca,maarif,"
                    "https://www.avito.ma/fr/test/listing_bad_price,"
                    "2026-04-28T12:00:00,batch_test"
                ),
            ]
        ),
        encoding="utf-8",
    )

    result = _read_clean_csv(clean_file, "batch_test")

    assert len(result.records) == 1
    assert result.skipped_rows == 1
    assert result.invalid_reasons_count["invalid_price"] == 1


def test_read_clean_csv_skips_missing_required_fields(tmp_path) -> None:
    clean_file = tmp_path / "clean.csv"
    clean_file.write_text(
        "\n".join(
            [
                "listing_title_clean,price,city,district,listing_url,scraped_at,batch_id",
                (
                    ",1000000,casablanca,maarif,"
                    "https://www.avito.ma/fr/test/listing_missing_title,"
                    "2026-04-28T12:00:00,batch_test"
                ),
                (
                    "appartement lumineux centre,1000000,,maarif,"
                    "https://www.avito.ma/fr/test/listing_missing_city,"
                    "2026-04-28T12:00:00,batch_test"
                ),
                (
                    "appartement lumineux centre,1000000,casablanca,nan,"
                    "https://www.avito.ma/fr/test/listing_missing_district,"
                    "2026-04-28T12:00:00,batch_test"
                ),
            ]
        ),
        encoding="utf-8",
    )

    result = _read_clean_csv(clean_file, "batch_test")

    assert result.records == []
    assert result.skipped_rows == 3
    assert result.invalid_reasons_count["missing_listing_title_clean"] == 1
    assert result.invalid_reasons_count["missing_city"] == 1
    assert result.invalid_reasons_count["missing_district"] == 1


def test_read_feature_csv_skips_all_null_feature_rows(tmp_path) -> None:
    features_file = tmp_path / "features.csv"
    features_file.write_text(
        "\n".join(
            [
                "listing_url,surface_m2,bedrooms,bathrooms,floor,price_per_m2",
                "https://www.avito.ma/fr/test/listing_empty,,,,,",
                "https://www.avito.ma/fr/test/listing_valid,100,2,1,,10000",
            ]
        ),
        encoding="utf-8",
    )

    result = _read_feature_csv(features_file, "batch_test")

    assert len(result.records) == 1
    assert result.records[0]["bedrooms"] == 2
    assert result.skipped_rows == 1
    assert result.invalid_reasons_count["all_features_missing"] == 1


def test_load_clean_csv_to_clean_table_skips_bad_rows_before_insert(tmp_path, monkeypatch) -> None:
    clean_file = tmp_path / "avito_clean_core_batch_test.csv"
    clean_file.write_text(
        "\n".join(
            [
                "listing_title_clean,price,city,district,listing_url,scraped_at,batch_id",
                (
                    "appartement lumineux centre,1000000,casablanca,maarif,"
                    "https://www.avito.ma/fr/test/listing_valid,"
                    "2026-04-28T12:00:00,batch_test"
                ),
                (
                    "appartement lumineux centre,bad,casablanca,maarif,"
                    "https://www.avito.ma/fr/test/listing_bad,"
                    "2026-04-28T12:00:00,batch_test"
                ),
            ]
        ),
        encoding="utf-8",
    )
    features_file = tmp_path / "avito_clean_features_batch_test.csv"
    features_file.write_text(
        "\n".join(
            [
                "listing_url,surface_m2,bedrooms,bathrooms,floor,price_per_m2",
                "https://www.avito.ma/fr/test/listing_valid,100,2,1,,10000",
                "https://www.avito.ma/fr/test/listing_empty,,,,,",
            ]
        ),
        encoding="utf-8",
    )

    class FakeCursor:
        inserted_rows = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, query, params=None):
            self.last_query = query

        def executemany(self, query, records):
            self.inserted_rows += len(records)

        def fetchone(self):
            return {"exists": False}

    class FakeConnection:
        cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

        def commit(self):
            return None

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr("src.clean.clean_data.get_connection", fake_connection)

    loaded_count = load_clean_csv_to_clean_table(clean_file, "batch_test", features_file)

    assert loaded_count == 1
    assert FakeConnection.cursor_obj.inserted_rows == 1


def test_clean_listing_title_removes_seller_and_action_noise() -> None:
    title = (
        "KARYNTON il y a 4 minutes Appartements dans Rabat, Agdal "
        "Appartement meublé calme agdal 4 personnes 1 chambre 700 DH "
        "Contacter le Vendeur"
    )

    cleaned = clean_listing_title(title)

    assert cleaned == "Appartement meublé calme agdal"
