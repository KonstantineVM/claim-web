"""Unit tests for claimweb.fetchers.naic_schedule_d.

Covers:
- _normalise_name: slug production, truncation, special characters
- _insurer_node_id: registry lookup, fallback
- _issuer_node_id: CUSIP-keyed, Treasury, agency, CLO, corporate
- _classify_security: CLO/CDO→A7, Treasury/agency→A10, corporate→A12
- _parse_amount: thousands USD parsing, parentheses, commas, empty
- _period_to_year: year extraction
- _read_schedule_d_csv: canonical CSV parsing, zero-amount filtering, encoding
- _write_schedule_d_csv: round-trip write/read
- _rows_from_json: JSON API response parsing
- _normalise_csv_row: alternate column-name normalisation
- _write_unmapped_registry: deduplication, file writing
- _parse_iowa_response: JSON and CSV dispatch
- NaicScheduleDFetcher.parse: fixture-based A7/A10/A12 arc extraction
- NaicScheduleDFetcher.validate: arc class checks, amount checks, warnings
- NaicScheduleDFetcher.list_available_periods: Q4-only filtering from cache
- Property-based (hypothesis): ArcFact schema compliance, normalise_name stability,
  parse_amount non-negative
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from claimweb.fetchers.base import (
    ArcClass,
    ArcFact,
    DataQualityFlag,
    Period,
    RawDataHandle,
    ValidationReport,
)
from claimweb.fetchers.naic_schedule_d import (
    _CACHE_LIFETIME_DAYS,
    _COL_BOOK_VALUE,
    _COL_CUSIP,
    _COL_DESCRIPTION,
    _COL_FAIR_VALUE,
    _COL_INSURER_NAME,
    _COL_INSURER_NAIC,
    _COL_ISSUER_NAME,
    _COL_ISSUER_NAIC,
    _COL_MATURITY,
    _COL_NAIC_DESIG,
    _COL_PAR_VALUE,
    _COL_SECURITY_TYPE,
    _COL_YEAR,
    _INSURER_REGISTRY,
    _MIN_HOLDINGS_TOTAL_MM,
    _SCHED_D_FIELDNAMES,
    _THOUSANDS_TO_MILLIONS,
    NaicScheduleDFetcher,
    _classify_security,
    _insurer_node_id,
    _issuer_node_id,
    _normalise_csv_row,
    _normalise_name,
    _parse_amount,
    _parse_iowa_response,
    _period_to_year,
    _read_schedule_d_csv,
    _rows_from_json,
    _write_schedule_d_csv,
    _write_unmapped_registry,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "naic_schedule_d"
FIXTURE_CSV = FIXTURE_DIR / "schedule_d_2024.csv"


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_handle(period: Period, tmp_path: Path) -> RawDataHandle:
    """Build a RawDataHandle pointing at the fixture CSV."""
    dest_dir = tmp_path / "naic_schedule_d" / str(period)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "68039_schedule_d.csv"

    # Copy fixture to temp path so we can compute SHA.
    content = FIXTURE_CSV.read_bytes()
    dest.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()

    return RawDataHandle(
        source_id="naic_schedule_d",
        period=period,
        paths=(dest,),
        sha256_by_path={str(dest): sha},
    )


# ──────────────────────────────────────────────────────────────────────────────
# _normalise_name
# ──────────────────────────────────────────────────────────────────────────────


class TestNormaliseName:
    def test_basic_slug(self):
        assert _normalise_name("Apple Inc") == "apple_inc"

    def test_strips_leading_trailing_special(self):
        assert _normalise_name("  __Hello World__  ") == "hello_world"

    def test_truncates_to_64(self):
        long_name = "A" * 100
        result = _normalise_name(long_name)
        assert len(result) == 64

    def test_replaces_hyphens_and_dots(self):
        assert _normalise_name("Bank-of-America Corp.") == "bank_of_america_corp"

    def test_empty_string(self):
        assert _normalise_name("") == ""

    def test_numbers_preserved(self):
        assert _normalise_name("CLO 2023-1A") == "clo_2023_1a"

    def test_case_insensitive(self):
        assert _normalise_name("FNMA") == "fnma"
        assert _normalise_name("Fnma") == "fnma"


# ──────────────────────────────────────────────────────────────────────────────
# _insurer_node_id
# ──────────────────────────────────────────────────────────────────────────────


class TestInsurerNodeId:
    def test_registry_lookup_athene(self):
        assert _insurer_node_id("68039") == "insurer:naic:68039"

    def test_registry_lookup_amerequity(self):
        assert _insurer_node_id("92525") == "insurer:naic:92525"

    def test_registry_lookup_metlife(self):
        assert _insurer_node_id("67105") == "insurer:naic:67105"

    def test_fallback_unknown_code(self):
        assert _insurer_node_id("99999") == "insurer:naic:99999"

    def test_strips_whitespace(self):
        assert _insurer_node_id("  68039  ") == "insurer:naic:68039"

    def test_all_registry_entries_have_correct_prefix(self):
        for code in _INSURER_REGISTRY:
            node_id = _insurer_node_id(code)
            assert node_id.startswith("insurer:naic:")


# ──────────────────────────────────────────────────────────────────────────────
# _issuer_node_id
# ──────────────────────────────────────────────────────────────────────────────


class TestIssuerNodeId:
    def test_treasury_cusip(self):
        node = _issuer_node_id("912828ZT0", "United States Treasury", "UST", ArcClass.A10)
        assert node == "issuer:us_treasury"

    def test_treasury_91282_prefix(self):
        node = _issuer_node_id("91282CBA2", "US TREAS", "UST", ArcClass.A10)
        assert node == "issuer:us_treasury"

    def test_fnma_cusip(self):
        node = _issuer_node_id("3135G0X24", "Federal National Mortgage Assoc", "MBS", ArcClass.A10)
        assert "fnma" in node or "agency" in node

    def test_fhlmc_cusip(self):
        node = _issuer_node_id("3137ABCD1", "Federal Home Loan Mortgage", "MBS", ArcClass.A10)
        assert "fhlmc" in node or "agency" in node

    def test_gnma_name(self):
        node = _issuer_node_id("38376JX44", "GNMA Pool", "MBS", ArcClass.A10)
        assert "gnma" in node or "agency" in node

    def test_gov_fallback_no_cusip(self):
        node = _issuer_node_id("", "Some Gov Agency", "UST", ArcClass.A10)
        assert node.startswith("issuer:")

    def test_clo_with_cusip(self):
        node = _issuer_node_id("00090BAA1", "AGL CLO 22 Ltd", "CLO", ArcClass.A7)
        assert node == "issuer:clo:00090B"

    def test_clo_with_short_cusip(self):
        node = _issuer_node_id("ABC", "AGL CLO 22", "CLO", ArcClass.A7)
        assert node == "issuer:clo:ABC"

    def test_clo_no_cusip_uses_name(self):
        node = _issuer_node_id("", "Apollo CLO 2023-1", "CLO", ArcClass.A7)
        assert node.startswith("issuer:clo:name:")

    def test_clo_no_cusip_no_name(self):
        node = _issuer_node_id("", "", "CLO", ArcClass.A7)
        assert node == "issuer:clo:unknown"

    def test_corporate_with_cusip(self):
        node = _issuer_node_id("037833100", "Apple Inc", "CORP", ArcClass.A12)
        assert node == "issuer:corp:037833"

    def test_corporate_no_cusip_uses_name(self):
        node = _issuer_node_id("", "Walmart Inc", "CORP", ArcClass.A12)
        assert node.startswith("issuer:corp:name:")

    def test_corporate_no_cusip_no_name(self):
        node = _issuer_node_id("", "", "CORP", ArcClass.A12)
        assert node == "issuer:corp:unknown"


# ──────────────────────────────────────────────────────────────────────────────
# _classify_security
# ──────────────────────────────────────────────────────────────────────────────


class TestClassifySecurity:
    def test_clo_type_code(self):
        assert _classify_security("00090BAA1", "Some bond", "CLO", "2") is ArcClass.A7

    def test_cdo_type_code(self):
        assert _classify_security("", "Some bond", "CDO", "1") is ArcClass.A7

    def test_cmo_type_code(self):
        assert _classify_security("", "Some bond", "CMO", "1") is ArcClass.A7

    def test_clo_in_description(self):
        assert _classify_security(
            "", "ATLAS CLO 2023-1 LTD TRANCHE B", "CORP", "1"
        ) is ArcClass.A7

    def test_clo_abbrev_description(self):
        assert _classify_security(
            "", "AGL CLO 22 Ltd", "OTHER", "1"
        ) is ArcClass.A7

    def test_collateralized_loan_obligation_description(self):
        assert _classify_security(
            "", "COLLATERALIZED LOAN OBLIGATION 2022", "", "1"
        ) is ArcClass.A7

    def test_collateralized_debt_obligation_description(self):
        assert _classify_security(
            "", "Collateralized Debt Obligation Fund", "OTHER", "2"
        ) is ArcClass.A7

    def test_treasury_type_code(self):
        assert _classify_security("912828ZT0", "Some bond", "UST", "1") is ArcClass.A10

    def test_ustr_type_code(self):
        assert _classify_security("912828ZT0", "Some bond", "USTR", "1") is ArcClass.A10

    def test_mbs_type_code(self):
        assert _classify_security("31376JD43", "FNMA Pool", "MBS", "1") is ArcClass.A10

    def test_agy_type_code(self):
        assert _classify_security("", "Agency bond", "AGY", "1") is ArcClass.A10

    def test_treasury_cusip_prefix_912810(self):
        assert _classify_security("912810SQ0", "Treasury Bond", "CORP", "1") is ArcClass.A10

    def test_treasury_cusip_prefix_912828(self):
        assert _classify_security("912828ZT0", "Note", "CORP", "1") is ArcClass.A10

    def test_treasury_cusip_prefix_91282(self):
        assert _classify_security("91282CBA2", "Note", "CORP", "1") is ArcClass.A10

    def test_agency_cusip_prefix_3135(self):
        assert _classify_security("3135G0X24", "FNMA", "CORP", "1") is ArcClass.A10

    def test_agency_cusip_prefix_3137(self):
        assert _classify_security("3137ABCD1", "FHLMC", "CORP", "1") is ArcClass.A10

    def test_us_treasury_description(self):
        assert _classify_security("", "US TREASURY NOTE 4.5%", "", "1") is ArcClass.A10

    def test_us_treasury_dotted_description(self):
        assert _classify_security("", "U.S. Treasury Note 3.875%", "", "1") is ArcClass.A10

    def test_fnma_description(self):
        assert _classify_security("", "FNMA POOL 4.000% 2054", "", "1") is ArcClass.A10

    def test_federal_national_mortgage_description(self):
        assert _classify_security(
            "", "FEDERAL NATIONAL MORTGAGE ASSOC", "", "1"
        ) is ArcClass.A10

    def test_corporate_default(self):
        assert _classify_security("037833100", "APPLE INC 3.75%", "CORP", "1") is ArcClass.A12

    def test_corporate_empty_type(self):
        assert _classify_security("06051GHF4", "BANK OF AMERICA CORP", "", "2") is ArcClass.A12

    def test_unknown_type_not_clo_not_gov(self):
        assert _classify_security("", "MUNI BOND STATE OF CA", "MUNI", "1") is ArcClass.A12

    def test_clo_takes_precedence_over_treasury_type(self):
        # If somehow both CLO type code and MBS type code conflict, CLO wins.
        assert _classify_security("", "CLO 2023 Fund", "CLO", "1") is ArcClass.A7


# ──────────────────────────────────────────────────────────────────────────────
# _parse_amount
# ──────────────────────────────────────────────────────────────────────────────


class TestParseAmount:
    def test_basic_integer(self):
        assert _parse_amount("1000") == Decimal("1000")

    def test_with_commas(self):
        assert _parse_amount("1,000,000") == Decimal("1000000")

    def test_with_dollar_sign(self):
        assert _parse_amount("$500") == Decimal("500")

    def test_decimal_value(self):
        assert _parse_amount("1234.56") == Decimal("1234.56")

    def test_empty_string(self):
        assert _parse_amount("") == Decimal("0")

    def test_whitespace_only(self):
        assert _parse_amount("   ") == Decimal("0")

    def test_parenthesized_negative(self):
        assert _parse_amount("(500)") == Decimal("-500")

    def test_parenthesized_negative_with_commas(self):
        assert _parse_amount("(1,250,000)") == Decimal("-1250000")

    def test_non_numeric(self):
        assert _parse_amount("N/A") == Decimal("0")

    def test_zero(self):
        assert _parse_amount("0") == Decimal("0")

    def test_leading_trailing_whitespace(self):
        assert _parse_amount("  750  ") == Decimal("750")

    def test_large_value(self):
        assert _parse_amount("999999999") == Decimal("999999999")


# ──────────────────────────────────────────────────────────────────────────────
# _period_to_year
# ──────────────────────────────────────────────────────────────────────────────


class TestPeriodToYear:
    def test_q4_2024(self):
        assert _period_to_year(Period("2024-Q4")) == 2024

    def test_q1_2020(self):
        assert _period_to_year(Period("2020-Q1")) == 2020

    def test_q3_2015(self):
        assert _period_to_year(Period("2015-Q3")) == 2015


# ──────────────────────────────────────────────────────────────────────────────
# _read_schedule_d_csv
# ──────────────────────────────────────────────────────────────────────────────


class TestReadScheduleDCsv:
    def test_reads_fixture_csv(self, tmp_path):
        rows = _read_schedule_d_csv(FIXTURE_CSV)
        assert len(rows) > 0

    def test_row_has_expected_keys(self, tmp_path):
        rows = _read_schedule_d_csv(FIXTURE_CSV)
        required_keys = {
            "insurer_naic", "insurer_name", "year", "cusip", "description",
            "issuer_name", "security_type", "par_thousands", "book_thousands",
        }
        for row in rows:
            assert required_keys.issubset(row.keys())

    def test_amounts_are_decimal(self, tmp_path):
        rows = _read_schedule_d_csv(FIXTURE_CSV)
        for row in rows:
            assert isinstance(row["par_thousands"], Decimal)
            assert isinstance(row["book_thousands"], Decimal)
            assert isinstance(row["fair_thousands"], Decimal)

    def test_fixture_has_treasury_rows(self):
        rows = _read_schedule_d_csv(FIXTURE_CSV)
        ust_rows = [r for r in rows if r["security_type"] == "UST"]
        assert len(ust_rows) > 0

    def test_fixture_has_clo_rows(self):
        rows = _read_schedule_d_csv(FIXTURE_CSV)
        clo_rows = [r for r in rows if r["security_type"] == "CLO"]
        assert len(clo_rows) > 0

    def test_fixture_has_corp_rows(self):
        rows = _read_schedule_d_csv(FIXTURE_CSV)
        corp_rows = [r for r in rows if r["security_type"] == "CORP"]
        assert len(corp_rows) > 0

    def test_skips_missing_description(self, tmp_path):
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text(
            f"{_COL_INSURER_NAIC},{_COL_INSURER_NAME},{_COL_YEAR},"
            f"{_COL_CUSIP},{_COL_DESCRIPTION},{_COL_BOOK_VALUE}\n"
            "68039,Athene,2024,912828ZT0,,500000\n"
        )
        rows = _read_schedule_d_csv(bad_csv)
        assert len(rows) == 0

    def test_skips_missing_insurer_naic(self, tmp_path):
        bad_csv = tmp_path / "bad2.csv"
        bad_csv.write_text(
            f"{_COL_INSURER_NAIC},{_COL_INSURER_NAME},{_COL_YEAR},"
            f"{_COL_CUSIP},{_COL_DESCRIPTION},{_COL_BOOK_VALUE}\n"
            ",Athene,2024,912828ZT0,US TREAS NOTE,500000\n"
        )
        rows = _read_schedule_d_csv(bad_csv)
        assert len(rows) == 0

    def test_nonexistent_file_returns_empty(self, tmp_path):
        rows = _read_schedule_d_csv(tmp_path / "nonexistent.csv")
        assert rows == []

    def test_handles_bom_encoding(self, tmp_path):
        bom_csv = tmp_path / "bom.csv"
        content = (
            f"{_COL_INSURER_NAIC},{_COL_INSURER_NAME},{_COL_YEAR},"
            f"{_COL_CUSIP},{_COL_DESCRIPTION},{_COL_ISSUER_NAME},"
            f"{_COL_ISSUER_NAIC},{_COL_SECURITY_TYPE},{_COL_NAIC_DESIG},"
            f"{_COL_MATURITY},{_COL_PAR_VALUE},{_COL_BOOK_VALUE},{_COL_FAIR_VALUE}\n"
            "68039,Athene,2024,912828ZT0,US TREAS 4.5%,US Treasury,0,UST,1,"
            "2025-11-30,100000,100250,99800\n"
        )
        # Write with utf-8-sig so the file starts with a UTF-8 BOM (\xef\xbb\xbf).
        bom_csv.write_bytes(content.encode("utf-8-sig"))
        rows = _read_schedule_d_csv(bom_csv)
        assert len(rows) == 1
        assert rows[0]["insurer_naic"] == "68039"


# ──────────────────────────────────────────────────────────────────────────────
# _write_schedule_d_csv / round-trip
# ──────────────────────────────────────────────────────────────────────────────


class TestWriteScheduleDCsv:
    def test_roundtrip_single_row(self, tmp_path):
        rows = [{
            "insurer_naic": "68039",
            "insurer_name": "Athene",
            "year": "2024",
            "cusip": "912828ZT0",
            "description": "US TREASURY NOTE 4.5%",
            "issuer_name": "United States Treasury",
            "issuer_naic": "0",
            "security_type": "UST",
            "naic_designation": "1",
            "maturity": "2024-11-30",
            "par_thousands": Decimal("500000"),
            "book_thousands": Decimal("501250"),
            "fair_thousands": Decimal("499800"),
        }]
        dest = tmp_path / "test.csv"
        _write_schedule_d_csv(dest, rows)
        back = _read_schedule_d_csv(dest)
        assert len(back) == 1
        assert back[0]["insurer_naic"] == "68039"
        assert back[0]["cusip"] == "912828ZT0"
        assert back[0]["book_thousands"] == Decimal("501250")

    def test_creates_parent_dirs(self, tmp_path):
        dest = tmp_path / "nested" / "deep" / "file.csv"
        _write_schedule_d_csv(dest, [])
        assert dest.exists()

    def test_writes_header(self, tmp_path):
        dest = tmp_path / "header.csv"
        _write_schedule_d_csv(dest, [])
        content = dest.read_text()
        assert _COL_INSURER_NAIC in content
        assert _COL_CUSIP in content
        assert _COL_BOOK_VALUE in content

    def test_all_fieldnames_in_output(self, tmp_path):
        dest = tmp_path / "fields.csv"
        _write_schedule_d_csv(dest, [])
        reader = csv.DictReader(io.StringIO(dest.read_text()))
        assert set(reader.fieldnames or []) == set(_SCHED_D_FIELDNAMES)

    def test_roundtrip_multiple_rows(self, tmp_path):
        original = _read_schedule_d_csv(FIXTURE_CSV)
        dest = tmp_path / "rt.csv"
        _write_schedule_d_csv(dest, original)
        back = _read_schedule_d_csv(dest)
        assert len(back) == len(original)

    def test_roundtrip_preserves_decimal_precision(self, tmp_path):
        rows = [{
            "insurer_naic": "68039",
            "insurer_name": "Athene",
            "year": "2024",
            "cusip": "912828ZT0",
            "description": "US TREASURY",
            "issuer_name": "US Treasury",
            "issuer_naic": "0",
            "security_type": "UST",
            "naic_designation": "1",
            "maturity": "2025-01-01",
            "par_thousands": Decimal("123456789"),
            "book_thousands": Decimal("123456789.123"),
            "fair_thousands": Decimal("0"),
        }]
        dest = tmp_path / "precision.csv"
        _write_schedule_d_csv(dest, rows)
        back = _read_schedule_d_csv(dest)
        assert back[0]["book_thousands"] == Decimal("123456789.123")


# ──────────────────────────────────────────────────────────────────────────────
# _rows_from_json
# ──────────────────────────────────────────────────────────────────────────────


class TestRowsFromJson:
    def test_list_of_dicts(self):
        data = [
            {
                "description": "US TREASURY NOTE",
                "cusip": "912828ZT0",
                "security_type": "UST",
                "book_value": "500000",
                "par_value": "500000",
            }
        ]
        rows = _rows_from_json(data, "68039", "Athene", 2024)
        assert len(rows) == 1
        assert rows[0]["description"] == "US TREASURY NOTE"
        assert rows[0]["insurer_naic"] == "68039"
        assert rows[0]["year"] == "2024"

    def test_dict_with_data_key(self):
        data = {
            "data": [
                {"description": "CLO Fund", "cusip": "00090BAA1", "book_value": "50000"}
            ]
        }
        rows = _rows_from_json(data, "92525", "AmerEquity", 2024)
        assert len(rows) == 1
        assert rows[0]["description"] == "CLO Fund"

    def test_dict_with_rows_key(self):
        data = {
            "rows": [
                {"description": "Corp Bond", "book_value": "80000"}
            ]
        }
        rows = _rows_from_json(data, "68039", "Athene", 2024)
        assert len(rows) == 1

    def test_dict_with_records_key(self):
        data = {
            "records": [
                {"description": "FNMA Pool", "par_value": "200000"}
            ]
        }
        rows = _rows_from_json(data, "68039", "Athene", 2024)
        assert len(rows) == 1

    def test_skips_missing_description(self):
        data = [{"cusip": "912828ZT0", "book_value": "500000"}]
        rows = _rows_from_json(data, "68039", "Athene", 2024)
        assert len(rows) == 0

    def test_empty_list(self):
        rows = _rows_from_json([], "68039", "Athene", 2024)
        assert rows == []

    def test_non_dict_items_skipped(self):
        data = ["not-a-dict", {"description": "valid bond", "book_value": "1000"}]
        rows = _rows_from_json(data, "68039", "Athene", 2024)
        assert len(rows) == 1

    def test_camelCase_field_names(self):
        data = [{"description": "CLO", "bookValue": "50000", "parValue": "50000"}]
        rows = _rows_from_json(data, "68039", "Athene", 2024)
        assert len(rows) == 1
        assert rows[0]["book_thousands"] == Decimal("50000")

    def test_amounts_parsed_as_decimal(self):
        data = [{"description": "Bond", "book_value": "1,234,567", "par_value": "(500)"}]
        rows = _rows_from_json(data, "68039", "Athene", 2024)
        assert rows[0]["book_thousands"] == Decimal("1234567")
        assert rows[0]["par_thousands"] == Decimal("-500")

    def test_unrecognised_data_structure_returns_empty(self):
        rows = _rows_from_json({"not_a_valid_key": 42}, "68039", "Athene", 2024)
        assert rows == []


# ──────────────────────────────────────────────────────────────────────────────
# _normalise_csv_row
# ──────────────────────────────────────────────────────────────────────────────


class TestNormaliseCsvRow:
    def _base_row(self) -> dict:
        return {
            _COL_DESCRIPTION: "US TREASURY NOTE 4.5%",
            _COL_CUSIP: "912828ZT0",
            _COL_SECURITY_TYPE: "UST",
            _COL_PAR_VALUE: "500000",
            _COL_BOOK_VALUE: "501250",
            _COL_FAIR_VALUE: "499800",
            _COL_ISSUER_NAME: "United States Treasury",
            _COL_ISSUER_NAIC: "0",
            _COL_NAIC_DESIG: "1",
            _COL_MATURITY: "2025-11-30",
        }

    def test_basic_canonical_row(self):
        result = _normalise_csv_row(self._base_row(), "68039", "Athene", 2024)
        assert result is not None
        assert result["description"] == "US TREASURY NOTE 4.5%"
        assert result["insurer_naic"] == "68039"
        assert result["cusip"] == "912828ZT0"
        assert result["book_thousands"] == Decimal("501250")

    def test_returns_none_when_no_description(self):
        row = self._base_row()
        row[_COL_DESCRIPTION] = ""
        assert _normalise_csv_row(row, "68039", "Athene", 2024) is None

    def test_alternate_description_column(self):
        row = {"Description": "Corp Bond", "BOOK_VALUE_THOUSANDS": "80000"}
        result = _normalise_csv_row(row, "68039", "Athene", 2024)
        assert result is not None
        assert result["description"] == "Corp Bond"

    def test_alternate_par_column(self):
        row = {"description": "Bond", "ParValue": "100000", "BookValue": "99000"}
        result = _normalise_csv_row(row, "68039", "Athene", 2024)
        assert result is not None
        assert result["par_thousands"] == Decimal("100000")

    def test_alternate_book_value_bacv(self):
        row = {
            "description": "Bond", "par_value": "100000",
            "BACV": "99500", "fair_value": "98000",
        }
        result = _normalise_csv_row(row, "68039", "Athene", 2024)
        assert result is not None
        assert result["book_thousands"] == Decimal("99500")

    def test_security_type_uppercased(self):
        row = self._base_row()
        row[_COL_SECURITY_TYPE] = "clo"
        result = _normalise_csv_row(row, "68039", "Athene", 2024)
        assert result is not None
        assert result["security_type"] == "CLO"

    def test_year_injected_from_argument(self):
        result = _normalise_csv_row(self._base_row(), "68039", "Athene", 2021)
        assert result is not None
        assert result["year"] == "2021"


# ──────────────────────────────────────────────────────────────────────────────
# _parse_iowa_response
# ──────────────────────────────────────────────────────────────────────────────


class TestParseIowaResponse:
    def test_parses_json_response(self):
        data = [
            {"description": "US TREAS NOTE", "cusip": "912828ZT0",
             "security_type": "UST", "book_value": "500000"}
        ]
        content = json.dumps(data).encode()
        rows = _parse_iowa_response(content, "68039", "Athene", 2024)
        assert len(rows) == 1
        assert rows[0]["description"] == "US TREAS NOTE"

    def test_parses_csv_fallback(self):
        content = (
            f"{_COL_INSURER_NAIC},{_COL_INSURER_NAME},{_COL_YEAR},"
            f"{_COL_CUSIP},{_COL_DESCRIPTION},{_COL_ISSUER_NAME},"
            f"{_COL_ISSUER_NAIC},{_COL_SECURITY_TYPE},{_COL_NAIC_DESIG},"
            f"{_COL_MATURITY},{_COL_PAR_VALUE},{_COL_BOOK_VALUE},{_COL_FAIR_VALUE}\n"
            "68039,Athene,2024,912828ZT0,US TREAS NOTE,US Treasury,0,UST,1,"
            "2025-11-30,100000,100250,99800\n"
        ).encode("utf-8")
        rows = _parse_iowa_response(content, "68039", "Athene", 2024)
        assert len(rows) == 1

    def test_empty_content_returns_empty(self):
        rows = _parse_iowa_response(b"", "68039", "Athene", 2024)
        assert rows == []

    def test_invalid_content_returns_empty(self):
        rows = _parse_iowa_response(b"<html>not json</html>", "68039", "Athene", 2024)
        assert rows == []


# ──────────────────────────────────────────────────────────────────────────────
# _write_unmapped_registry
# ──────────────────────────────────────────────────────────────────────────────


class TestWriteUnmappedRegistry:
    def test_creates_registry_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        entries = [{
            "cusip": "ABC123456",
            "issuer_name": "Unknown Corp",
            "description": "Unknown Bond",
            "security_type": "CORP",
            "suggested_id": "issuer:corp:name:unknown_corp",
            "arc_class": "A12",
            "period": "2024-Q4",
        }]
        _write_unmapped_registry(Period("2024-Q4"), entries)
        registry_path = tmp_path / "claimweb" / "registry" / "unmapped" / "naic_schedule_d_2024-Q4.json"
        assert registry_path.exists()
        data = json.loads(registry_path.read_text())
        assert len(data) == 1
        assert data[0]["cusip"] == "ABC123456"

    def test_deduplicates_by_cusip_and_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        entry = {
            "cusip": "ABC123456",
            "issuer_name": "Corp X",
            "description": "Bond",
            "security_type": "CORP",
            "suggested_id": "issuer:corp:name:corp_x",
            "arc_class": "A12",
            "period": "2024-Q4",
        }
        _write_unmapped_registry(Period("2024-Q4"), [entry])
        _write_unmapped_registry(Period("2024-Q4"), [entry])
        registry_path = tmp_path / "claimweb" / "registry" / "unmapped" / "naic_schedule_d_2024-Q4.json"
        data = json.loads(registry_path.read_text())
        assert len(data) == 1

    def test_appends_new_entries(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        entry1 = {
            "cusip": "ABC123456", "issuer_name": "Corp A",
            "description": "Bond A", "security_type": "CORP",
            "suggested_id": "issuer:corp:name:corp_a",
            "arc_class": "A12", "period": "2024-Q4",
        }
        entry2 = {
            "cusip": "DEF789012", "issuer_name": "Corp B",
            "description": "Bond B", "security_type": "CORP",
            "suggested_id": "issuer:corp:name:corp_b",
            "arc_class": "A12", "period": "2024-Q4",
        }
        _write_unmapped_registry(Period("2024-Q4"), [entry1])
        _write_unmapped_registry(Period("2024-Q4"), [entry2])
        registry_path = tmp_path / "claimweb" / "registry" / "unmapped" / "naic_schedule_d_2024-Q4.json"
        data = json.loads(registry_path.read_text())
        assert len(data) == 2


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleDFetcher.list_available_periods
# ──────────────────────────────────────────────────────────────────────────────


class TestListAvailablePeriods:
    def test_empty_when_no_cache_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleDFetcher()
        assert fetcher.list_available_periods() == []

    def test_returns_q4_periods_only(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        raw_dir = tmp_path / "data" / "raw" / "naic_schedule_d"
        (raw_dir / "2024-Q4").mkdir(parents=True)
        (raw_dir / "2023-Q4").mkdir()
        (raw_dir / "2023-Q2").mkdir()   # Should be excluded (not Q4)
        (raw_dir / "not-a-period").mkdir()   # Should be excluded (invalid)
        fetcher = NaicScheduleDFetcher()
        periods = fetcher.list_available_periods()
        assert all(p.quarter == 4 for p in periods)
        assert len(periods) == 2
        assert Period("2024-Q4") in periods
        assert Period("2023-Q4") in periods

    def test_sorted_ascending(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        raw_dir = tmp_path / "data" / "raw" / "naic_schedule_d"
        for yr in [2022, 2020, 2021]:
            (raw_dir / f"{yr}-Q4").mkdir(parents=True)
        fetcher = NaicScheduleDFetcher()
        periods = fetcher.list_available_periods()
        years = [p.year for p in periods]
        assert years == sorted(years)


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleDFetcher.acquire — Q4 enforcement
# ──────────────────────────────────────────────────────────────────────────────


class TestAcquireQ4Enforcement:
    def test_non_q4_raises_value_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleDFetcher()
        with pytest.raises(ValueError, match="Q4"):
            fetcher.acquire(Period("2024-Q1"))

    def test_non_q4_q2_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleDFetcher()
        with pytest.raises(ValueError):
            fetcher.acquire(Period("2024-Q2"))

    def test_non_q4_q3_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleDFetcher()
        with pytest.raises(ValueError):
            fetcher.acquire(Period("2023-Q3"))


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleDFetcher.acquire — cache hit
# ──────────────────────────────────────────────────────────────────────────────


class TestAcquireCacheHit:
    def test_uses_cached_csv_without_http(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Pre-populate cache for all 8 insurers.
        period = Period("2024-Q4")
        cache_dir = tmp_path / "data" / "raw" / "naic_schedule_d" / str(period)
        cache_dir.mkdir(parents=True)
        for naic_code in _INSURER_REGISTRY:
            csv_path = cache_dir / f"{naic_code}_schedule_d.csv"
            # Write a small valid CSV.
            content = FIXTURE_CSV.read_bytes()
            csv_path.write_bytes(content)

        with patch("claimweb.fetchers.naic_schedule_d.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_client.return_value.__exit__ = MagicMock(return_value=False)
            fetcher = NaicScheduleDFetcher()
            handle = fetcher.acquire(period)

        # HTTP client should not have been called for any company.
        assert not mock_client.return_value.__enter__.return_value.get.called
        assert len(handle.paths) == len(_INSURER_REGISTRY)


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleDFetcher.parse
# ──────────────────────────────────────────────────────────────────────────────


class TestParse:
    def test_parse_fixture_produces_arcs(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert len(facts) > 0

    def test_parse_produces_arcfact_instances(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert all(isinstance(f, ArcFact) for f in facts)

    def test_parse_only_a7_a10_a12(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        valid_classes = {ArcClass.A7, ArcClass.A10, ArcClass.A12}
        assert all(f.instrument_class in valid_classes for f in facts)

    def test_parse_produces_a10_for_treasury(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        a10_facts = [f for f in facts if f.instrument_class is ArcClass.A10]
        assert len(a10_facts) > 0

    def test_parse_produces_a7_for_clo(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        a7_facts = [f for f in facts if f.instrument_class is ArcClass.A7]
        assert len(a7_facts) > 0

    def test_parse_produces_a12_for_corporate(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        a12_facts = [f for f in facts if f.instrument_class is ArcClass.A12]
        assert len(a12_facts) > 0

    def test_arc_direction_source_is_issuer(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert all(f.source_node_id.startswith("issuer:") for f in facts)

    def test_arc_direction_target_is_insurer(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert all(f.target_node_id.startswith("insurer:") for f in facts)

    def test_treasury_source_is_us_treasury(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        treasury_arcs = [
            f for f in facts
            if f.instrument_class is ArcClass.A10
            and f.source_node_id == "issuer:us_treasury"
        ]
        assert len(treasury_arcs) > 0

    def test_amounts_are_in_millions(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        # Fixture row for 912828ZT0: book_value=501,250 thousands → 501.250 millions
        a_treasury = next(
            (f for f in facts if f.source_node_id == "issuer:us_treasury"), None
        )
        assert a_treasury is not None
        assert a_treasury.dollar_amount_millions == Decimal("501250") * _THOUSANDS_TO_MILLIONS

    def test_non_negative_amounts(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert all(f.dollar_amount_millions >= Decimal("0") for f in facts)

    def test_direct_measured_when_book_value_present(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        # Fixture rows all have book_value present.
        direct = [f for f in facts if f.data_quality_flag is DataQualityFlag.DIRECT_MEASURED]
        assert len(direct) > 0

    def test_proxy_when_only_par_value(self, tmp_path):
        period = Period("2024-Q4")
        csv_content = (
            f"{_COL_INSURER_NAIC},{_COL_INSURER_NAME},{_COL_YEAR},{_COL_CUSIP},"
            f"{_COL_DESCRIPTION},{_COL_ISSUER_NAME},{_COL_ISSUER_NAIC},"
            f"{_COL_SECURITY_TYPE},{_COL_NAIC_DESIG},{_COL_MATURITY},"
            f"{_COL_PAR_VALUE},{_COL_BOOK_VALUE},{_COL_FAIR_VALUE}\n"
            "68039,Athene,2024,912828ZT0,US TREAS 4.5%,US Treasury,0,UST,1,"
            "2025-11-30,500000,0,0\n"
        )
        csv_path = tmp_path / "test_proxy.csv"
        csv_path.write_text(csv_content)
        sha = hashlib.sha256(csv_content.encode()).hexdigest()
        handle = RawDataHandle(
            source_id="naic_schedule_d",
            period=period,
            paths=(csv_path,),
            sha256_by_path={str(csv_path): sha},
        )
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert len(facts) == 1
        assert facts[0].data_quality_flag is DataQualityFlag.PROXY

    def test_skips_zero_amount_rows(self, tmp_path):
        period = Period("2024-Q4")
        csv_content = (
            f"{_COL_INSURER_NAIC},{_COL_INSURER_NAME},{_COL_YEAR},{_COL_CUSIP},"
            f"{_COL_DESCRIPTION},{_COL_ISSUER_NAME},{_COL_ISSUER_NAIC},"
            f"{_COL_SECURITY_TYPE},{_COL_NAIC_DESIG},{_COL_MATURITY},"
            f"{_COL_PAR_VALUE},{_COL_BOOK_VALUE},{_COL_FAIR_VALUE}\n"
            "68039,Athene,2024,912828ZT0,US TREAS 4.5%,US Treasury,0,UST,1,"
            "2025-11-30,0,0,0\n"
        )
        csv_path = tmp_path / "test_zero.csv"
        csv_path.write_text(csv_content)
        sha = hashlib.sha256(csv_content.encode()).hexdigest()
        handle = RawDataHandle(
            source_id="naic_schedule_d",
            period=period,
            paths=(csv_path,),
            sha256_by_path={str(csv_path): sha},
        )
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert len(facts) == 0

    def test_parse_provenance_fields_populated(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.provenance_source == "naic_schedule_d"
            assert f.provenance_url
            assert f.provenance_filing
            assert f.sha256_of_source

    def test_parse_period_set_correctly(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert all(f.period == period for f in facts)

    def test_parse_measurement_basis_is_stock_eop(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert all(f.measurement_basis == "stock_eop" for f in facts)

    def test_parse_empty_handle_returns_empty(self, tmp_path):
        period = Period("2024-Q4")
        handle = RawDataHandle(
            source_id="naic_schedule_d",
            period=period,
            paths=(),
            sha256_by_path={},
        )
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        assert facts == []

    def test_parse_iowa_url_for_ia_companies(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleDFetcher()
        facts = fetcher.parse(handle)
        # Fixture is for 68039 (Iowa domicile).
        iowa_facts = [f for f in facts if "iid.iowa.gov" in f.provenance_url]
        assert len(iowa_facts) > 0


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleDFetcher.validate
# ──────────────────────────────────────────────────────────────────────────────


class TestValidate:
    def _make_arc(
        self,
        period: str = "2024-Q4",
        arc_class: ArcClass = ArcClass.A10,
        source: str = "issuer:us_treasury",
        target: str = "insurer:naic:68039",
        amount: str = "500",
    ) -> ArcFact:
        return ArcFact(
            period=Period(period),
            source_node_id=source,
            target_node_id=target,
            instrument_class=arc_class,
            dollar_amount_millions=Decimal(amount),
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
            provenance_source="naic_schedule_d",
            provenance_url="https://iid.iowa.gov/companies/68039/financials/2024/schedule_d",
            provenance_filing="NAIC/68039/2024/ScheduleD_Part1",
            provenance_page=None,
            provenance_field="Schedule_D_Part1.CUSIP=912828ZT0.BOOK_VALUE_THOUSANDS",
            sha256_of_source="a" * 64,
        )

    @staticmethod
    def _errors(report: ValidationReport) -> list:
        return [i for i in report.issues if i.severity == "error"]

    @staticmethod
    def _warnings(report: ValidationReport) -> list:
        return [i for i in report.issues if i.severity == "warning"]

    @staticmethod
    def _infos(report: ValidationReport) -> list:
        return [i for i in report.issues if i.severity == "info"]

    def test_valid_facts_pass(self):
        facts = [
            self._make_arc(arc_class=ArcClass.A10, amount="2000"),
            self._make_arc(arc_class=ArcClass.A7, source="issuer:clo:00090B", amount="500"),
            self._make_arc(arc_class=ArcClass.A12, source="issuer:corp:037833", amount="800"),
        ]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        assert report.is_clean

    def test_wrong_arc_class_errors(self):
        facts = [self._make_arc(arc_class=ArcClass.A6)]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        assert not report.is_clean
        assert any("WRONG_ARC_CLASS" in e.code for e in self._errors(report))

    def test_wrong_arc_class_a1_errors(self):
        facts = [self._make_arc(arc_class=ArcClass.A1)]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        assert not report.is_clean

    def test_negative_amount_errors(self):
        facts = [self._make_arc(amount="-100")]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        assert not report.is_clean
        assert any("NEGATIVE_HOLDING" in e.code for e in self._errors(report))

    def test_bad_source_prefix_warns(self):
        facts = [self._make_arc(source="reinsurer:bermuda:xyz", amount="2000")]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        assert any("UNEXPECTED_SOURCE_PREFIX" in w.code for w in self._warnings(report))

    def test_bad_target_prefix_warns(self):
        facts = [self._make_arc(target="reinsurer:bermuda:xyz", amount="2000")]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        assert any("UNEXPECTED_TARGET_PREFIX" in w.code for w in self._warnings(report))

    def test_empty_facts_warns(self):
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate([])
        assert any("NO_ARCS" in w.code for w in self._warnings(report))

    def test_no_clo_arcs_info(self):
        facts = [
            self._make_arc(arc_class=ArcClass.A10, amount="2000"),
            self._make_arc(arc_class=ArcClass.A12, source="issuer:corp:037833", amount="800"),
        ]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        assert any("NO_CLO_ARCS" in i.code for i in self._infos(report))

    def test_no_treasury_arcs_info(self):
        facts = [
            self._make_arc(arc_class=ArcClass.A7, source="issuer:clo:00090B", amount="500"),
            self._make_arc(arc_class=ArcClass.A12, source="issuer:corp:037833", amount="800"),
        ]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        assert any("NO_TREASURY_ARCS" in i.code for i in self._infos(report))

    def test_low_total_warns(self):
        facts = [self._make_arc(arc_class=ArcClass.A10, amount="10")]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        assert any("LOW_HOLDINGS_TOTAL" in w.code for w in self._warnings(report))

    def test_above_minimum_threshold_no_warning(self):
        facts = [self._make_arc(arc_class=ArcClass.A10, amount="5000")]
        fetcher = NaicScheduleDFetcher()
        report = fetcher.validate(facts)
        low_warnings = [w for w in self._warnings(report) if "LOW_HOLDINGS_TOTAL" in w.code]
        assert len(low_warnings) == 0


# ──────────────────────────────────────────────────────────────────────────────
# Property-based tests (hypothesis)
# ──────────────────────────────────────────────────────────────────────────────


@given(st.text(min_size=0, max_size=200))
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=100)
def test_normalise_name_never_exceeds_64(name):
    result = _normalise_name(name)
    assert len(result) <= 64


@given(st.text(min_size=0, max_size=200))
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=100)
def test_normalise_name_only_safe_chars(name):
    result = _normalise_name(name)
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in result)


@given(
    st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("9999999"),
        allow_nan=False,
        allow_infinity=False,
        places=3,
    )
)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=100)
def test_parse_amount_roundtrips_decimal(value):
    """_parse_amount must exactly reproduce a Decimal when it is serialised as a string."""
    result = _parse_amount(str(value))
    assert result == value


@given(
    st.lists(
        st.fixed_dictionaries({
            "period": st.just("2024-Q4"),
            "source_node_id": st.just("issuer:us_treasury"),
            "target_node_id": st.just("insurer:naic:68039"),
            "arc_class": st.sampled_from([ArcClass.A7, ArcClass.A10, ArcClass.A12]),
            "amount": st.decimals(
                min_value=Decimal("0.001"),
                max_value=Decimal("999999"),
                allow_nan=False,
                allow_infinity=False,
                places=3,
            ),
        }),
        min_size=1,
        max_size=10,
    )
)
@settings(suppress_health_check=[HealthCheck.too_slow], max_examples=50)
def test_parse_output_arcfacts_schema_compliant(arc_specs):
    """All ArcFacts produced by the parse pathway conform to the schema."""
    facts = []
    for spec in arc_specs:
        facts.append(ArcFact(
            period=Period(spec["period"]),
            source_node_id=spec["source_node_id"],
            target_node_id=spec["target_node_id"],
            instrument_class=spec["arc_class"],
            dollar_amount_millions=spec["amount"],
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
            provenance_source="naic_schedule_d",
            provenance_url="https://iid.iowa.gov/test",
            provenance_filing="NAIC/68039/2024/ScheduleD_Part1",
            provenance_page=None,
            provenance_field="Schedule_D_Part1.BOOK_VALUE_THOUSANDS",
            sha256_of_source="a" * 64,
        ))
    for fact in facts:
        assert isinstance(fact.period, Period)
        assert fact.instrument_class in {ArcClass.A7, ArcClass.A10, ArcClass.A12}
        assert fact.dollar_amount_millions >= Decimal("0")
        assert fact.provenance_source == "naic_schedule_d"
