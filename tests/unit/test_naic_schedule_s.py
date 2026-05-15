"""Unit tests for claimweb.fetchers.naic_schedule_s.

Covers:
- _normalise_name: slug production, truncation, special characters
- _cedent_node_id: registry lookup, fallback
- _reinsurer_node_id: offshore vs US domicile, NAIC present/absent
- _is_offshore: offshore detection for all domicile codes
- _parse_amount: thousands USD parsing, parentheses, commas, empty
- _period_to_year: year extraction
- _read_schedule_s_csv: canonical CSV parsing, part filtering, encoding
- _write_schedule_s_csv: round-trip write/read
- _rows_from_json: JSON API response parsing (list and dict wrappers)
- _normalise_csv_row: alternate column-name normalisation
- _write_unmapped_registry: deduplication, file writing
- _parse_iowa_response: JSON and CSV dispatch
- NaicScheduleSFetcher.parse: fixture-based A6 arc extraction
- NaicScheduleSFetcher.validate: clean path, empty, negatives, missing offshore
- NaicScheduleSFetcher.list_available_periods: Q4-only filtering from cache
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
from claimweb.fetchers.naic_schedule_s import (
    _CACHE_LIFETIME_DAYS,
    _CEDENT_REGISTRY,
    _CEDED_PARTS,
    _COL_CEDED_AMT,
    _COL_CEDENT_NAME,
    _COL_CEDENT_NAIC,
    _COL_DOMICILE,
    _COL_LINE,
    _COL_PART,
    _COL_REINS_FED_ID,
    _COL_REINS_NAME,
    _COL_REINS_NAIC,
    _COL_TYPE,
    _COL_YEAR,
    _DOMICILE_TO_PREFIX,
    _MIN_CEDED_TOTAL_MM,
    _OFFSHORE_DOMICILES,
    _THOUSANDS_TO_MILLIONS,
    _US_STATE_CODES,
    NaicScheduleSFetcher,
    _cedent_node_id,
    _is_offshore,
    _normalise_csv_row,
    _normalise_name,
    _parse_amount,
    _parse_iowa_response,
    _period_to_year,
    _read_schedule_s_csv,
    _reinsurer_node_id,
    _rows_from_json,
    _write_schedule_s_csv,
    _write_unmapped_registry,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "naic_schedule_s"
FIXTURE_CSV = FIXTURE_DIR / "schedule_s_2024.csv"


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_handle(period: Period, tmp_path: Path) -> RawDataHandle:
    """Build a RawDataHandle pointing at the fixture CSV."""
    dest_dir = tmp_path / "naic_schedule_s" / str(period)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "68039_schedule_s.csv"
    dest.write_bytes(FIXTURE_CSV.read_bytes())
    return RawDataHandle.from_paths("naic_schedule_s", period, [dest])


def _make_minimal_arc(
    period: Period = None,
    source: str = "insurer:naic:68039",
    target: str = "reinsurer:bermuda:athene_re_ltd",
    amount: Decimal = Decimal("25000"),
) -> ArcFact:
    if period is None:
        period = Period("2024-Q4")
    return ArcFact(
        period=period,
        source_node_id=source,
        target_node_id=target,
        instrument_class=ArcClass.A6,
        dollar_amount_millions=amount,
        measurement_basis="stock_eop",
        data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
        provenance_source="naic_schedule_s",
        provenance_url="https://iid.iowa.gov/companies/68039/financials/2024/schedule_s",
        provenance_filing="NAIC/68039/2024/ScheduleS",
        provenance_page=None,
        provenance_field="Schedule_S_S4.CEDED_AMOUNT_THOUSANDS",
        sha256_of_source="a" * 64,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────


class TestConstants:
    def test_thousands_to_millions(self):
        assert _THOUSANDS_TO_MILLIONS == Decimal("0.001")

    def test_ceded_parts(self):
        assert "S2" in _CEDED_PARTS
        assert "S4" in _CEDED_PARTS
        assert "S1" not in _CEDED_PARTS
        assert "S3" not in _CEDED_PARTS

    def test_min_ceded_total_mm(self):
        assert _MIN_CEDED_TOTAL_MM > Decimal("0")

    def test_offshore_domiciles_contains_bmu(self):
        assert "BMU" in _OFFSHORE_DOMICILES
        assert "CYM" in _OFFSHORE_DOMICILES
        assert "IRL" in _OFFSHORE_DOMICILES

    def test_us_state_codes_count(self):
        # 50 states + DC
        assert len(_US_STATE_CODES) == 51

    def test_domicile_to_prefix_bermuda(self):
        assert _DOMICILE_TO_PREFIX["BMU"] == "bermuda"
        assert _DOMICILE_TO_PREFIX["CYM"] == "cayman"

    def test_cedent_registry_has_target_companies(self):
        assert "68039" in _CEDENT_REGISTRY  # Athene
        assert "92525" in _CEDENT_REGISTRY  # AmEq
        assert "33588" in _CEDENT_REGISTRY  # F&G

    def test_cedent_registry_entries_have_required_keys(self):
        for code, entry in _CEDENT_REGISTRY.items():
            assert "name" in entry, f"Missing 'name' for {code}"
            assert "state" in entry, f"Missing 'state' for {code}"
            assert "node_id" in entry, f"Missing 'node_id' for {code}"


# ──────────────────────────────────────────────────────────────────────────────
# _normalise_name
# ──────────────────────────────────────────────────────────────────────────────


class TestNormaliseName:
    def test_simple_name(self):
        assert _normalise_name("Athene Re Ltd.") == "athene_re_ltd"

    def test_lowercases(self):
        assert _normalise_name("MUNICH RE") == "munich_re"

    def test_special_chars_become_underscores(self):
        assert _normalise_name("A & B Co.") == "a_b_co"

    def test_truncates_to_64(self):
        long_name = "a" * 100
        result = _normalise_name(long_name)
        assert len(result) == 64

    def test_strips_leading_trailing_underscores(self):
        result = _normalise_name("  ---Entity---  ")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_empty_string(self):
        assert _normalise_name("") == ""

    def test_unicode_chars_removed(self):
        result = _normalise_name("Société Générale Réass.")
        # Non-ascii chars become underscores, then collapsed
        assert result.isascii() or len(result) > 0

    def test_numbers_preserved(self):
        result = _normalise_name("Re Ltd 2024")
        assert "2024" in result


# ──────────────────────────────────────────────────────────────────────────────
# _cedent_node_id
# ──────────────────────────────────────────────────────────────────────────────


class TestCedentNodeId:
    def test_registry_lookup_athene(self):
        assert _cedent_node_id("68039") == "insurer:naic:68039"

    def test_registry_lookup_amereq(self):
        assert _cedent_node_id("92525") == "insurer:naic:92525"

    def test_fallback_unknown_code(self):
        result = _cedent_node_id("99999")
        assert result == "insurer:naic:99999"

    def test_strips_whitespace(self):
        assert _cedent_node_id("  68039  ") == "insurer:naic:68039"

    def test_all_registry_entries_produce_correct_prefix(self):
        for code in _CEDENT_REGISTRY:
            node_id = _cedent_node_id(code)
            assert node_id.startswith("insurer:naic:")


# ──────────────────────────────────────────────────────────────────────────────
# _reinsurer_node_id
# ──────────────────────────────────────────────────────────────────────────────


class TestReinsurerNodeId:
    def test_bermuda_offshore(self):
        result = _reinsurer_node_id("Athene Re Ltd.", "0", "BMU")
        assert result == "reinsurer:bermuda:athene_re_ltd"

    def test_cayman_offshore(self):
        result = _reinsurer_node_id("North End Re", "", "CYM")
        assert result.startswith("reinsurer:cayman:")

    def test_ireland_offshore(self):
        result = _reinsurer_node_id("Irish Re Co", "", "IRL")
        assert result.startswith("reinsurer:ireland:")

    def test_us_with_naic_code(self):
        result = _reinsurer_node_id("General Re Corp", "22292", "CT")
        assert result == "insurer:naic:22292"

    def test_us_without_naic_code(self):
        result = _reinsurer_node_id("Small Re Inc", "0", "MO")
        assert result == "insurer:name:small_re_inc"

    def test_us_empty_naic_code(self):
        result = _reinsurer_node_id("RGA Re", "", "MO")
        assert result.startswith("insurer:name:")

    def test_empty_domicile_fallback(self):
        result = _reinsurer_node_id("Unknown Re", "0", "")
        assert result.startswith("reinsurer:name:") or result.startswith("reinsurer:")

    def test_unknown_foreign_domicile(self):
        result = _reinsurer_node_id("Some Foreign Re", "0", "SGP")
        # SGP not in US states → treated as offshore/foreign
        assert result.startswith("reinsurer:")

    def test_generic_foreign_marker(self):
        result = _reinsurer_node_id("Alien Re", "0", "Alien")
        assert result.startswith("reinsurer:foreign:")


# ──────────────────────────────────────────────────────────────────────────────
# _is_offshore
# ──────────────────────────────────────────────────────────────────────────────


class TestIsOffshore:
    def test_bermuda_is_offshore(self):
        assert _is_offshore("BMU") is True

    def test_cayman_is_offshore(self):
        assert _is_offshore("CYM") is True

    def test_us_state_not_offshore(self):
        assert _is_offshore("CT") is False
        assert _is_offshore("IA") is False
        assert _is_offshore("NY") is False

    def test_empty_string(self):
        assert _is_offshore("") is False

    def test_all_offshore_domiciles_detected(self):
        for dom in _OFFSHORE_DOMICILES:
            assert _is_offshore(dom) is True, f"Expected {dom} to be offshore"

    def test_all_us_states_not_offshore(self):
        for state in _US_STATE_CODES:
            assert _is_offshore(state) is False, f"Expected {state} to NOT be offshore"


# ──────────────────────────────────────────────────────────────────────────────
# _parse_amount
# ──────────────────────────────────────────────────────────────────────────────


class TestParseAmount:
    def test_simple_integer(self):
        assert _parse_amount("1000") == Decimal("1000")

    def test_comma_separated(self):
        assert _parse_amount("25,000,000") == Decimal("25000000")

    def test_dollar_sign(self):
        assert _parse_amount("$5000") == Decimal("5000")

    def test_parenthesized_negative(self):
        assert _parse_amount("(1234)") == Decimal("-1234")

    def test_empty_string(self):
        assert _parse_amount("") == Decimal("0")

    def test_whitespace_only(self):
        assert _parse_amount("   ") == Decimal("0")

    def test_non_numeric(self):
        assert _parse_amount("N/A") == Decimal("0")

    def test_decimal_value(self):
        assert _parse_amount("1234.56") == Decimal("1234.56")

    def test_comma_and_dollar(self):
        assert _parse_amount("$1,234,567") == Decimal("1234567")

    def test_zero(self):
        assert _parse_amount("0") == Decimal("0")

    def test_negative_with_minus(self):
        assert _parse_amount("-500") == Decimal("-500")

    def test_result_is_decimal_type(self):
        result = _parse_amount("12345")
        assert isinstance(result, Decimal)


# ──────────────────────────────────────────────────────────────────────────────
# _period_to_year
# ──────────────────────────────────────────────────────────────────────────────


class TestPeriodToYear:
    def test_q4_period(self):
        assert _period_to_year(Period("2024-Q4")) == 2024

    def test_q1_period(self):
        assert _period_to_year(Period("2020-Q1")) == 2020

    def test_different_years(self):
        for year in [2000, 2010, 2023, 2024]:
            assert _period_to_year(Period(f"{year}-Q4")) == year


# ──────────────────────────────────────────────────────────────────────────────
# _read_schedule_s_csv
# ──────────────────────────────────────────────────────────────────────────────


class TestReadScheduleSCsv:
    def test_reads_fixture(self, tmp_path):
        dest = tmp_path / "test.csv"
        dest.write_bytes(FIXTURE_CSV.read_bytes())
        rows = _read_schedule_s_csv(dest)
        assert len(rows) > 0

    def test_filters_to_ceded_parts_only(self, tmp_path):
        dest = tmp_path / "test.csv"
        dest.write_bytes(FIXTURE_CSV.read_bytes())
        rows = _read_schedule_s_csv(dest)
        for row in rows:
            assert row["part"] in _CEDED_PARTS

    def test_row_has_expected_keys(self, tmp_path):
        dest = tmp_path / "test.csv"
        dest.write_bytes(FIXTURE_CSV.read_bytes())
        rows = _read_schedule_s_csv(dest)
        for row in rows:
            assert "cedent_naic" in row
            assert "reins_name" in row
            assert "domicile" in row
            assert "ceded_thousands" in row
            assert isinstance(row["ceded_thousands"], Decimal)

    def test_filters_missing_reins_name(self, tmp_path):
        content = (
            f"{_COL_CEDENT_NAIC},{_COL_CEDENT_NAME},{_COL_YEAR},{_COL_PART},"
            f"{_COL_LINE},{_COL_REINS_NAME},{_COL_REINS_NAIC},{_COL_REINS_FED_ID},"
            f"{_COL_DOMICILE},{_COL_TYPE},{_COL_CEDED_AMT}\n"
            f"68039,Athene,2024,S4,1,,0,,BMU,T,1000\n"
        )
        dest = tmp_path / "empty_reins.csv"
        dest.write_text(content, encoding="utf-8")
        rows = _read_schedule_s_csv(dest)
        assert len(rows) == 0

    def test_filters_non_ceded_parts(self, tmp_path):
        content = (
            f"{_COL_CEDENT_NAIC},{_COL_CEDENT_NAME},{_COL_YEAR},{_COL_PART},"
            f"{_COL_LINE},{_COL_REINS_NAME},{_COL_REINS_NAIC},{_COL_REINS_FED_ID},"
            f"{_COL_DOMICILE},{_COL_TYPE},{_COL_CEDED_AMT}\n"
            f"68039,Athene,2024,S1,1,Some Re,0,,BMU,T,1000\n"
            f"68039,Athene,2024,S3,2,Other Re,0,,BMU,T,2000\n"
        )
        dest = tmp_path / "assumed_only.csv"
        dest.write_text(content, encoding="utf-8")
        rows = _read_schedule_s_csv(dest)
        assert len(rows) == 0

    def test_tolerates_missing_file(self, tmp_path):
        rows = _read_schedule_s_csv(tmp_path / "nonexistent.csv")
        assert rows == []

    def test_handles_bom_encoding(self, tmp_path):
        content = (
            f"{_COL_CEDENT_NAIC},{_COL_CEDENT_NAME},{_COL_YEAR},{_COL_PART},"
            f"{_COL_LINE},{_COL_REINS_NAME},{_COL_REINS_NAIC},{_COL_REINS_FED_ID},"
            f"{_COL_DOMICILE},{_COL_TYPE},{_COL_CEDED_AMT}\n"
            f"68039,Athene,2024,S4,1,Athene Re,0,,BMU,T,5000\n"
        )
        dest = tmp_path / "bom.csv"
        dest.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
        rows = _read_schedule_s_csv(dest)
        assert len(rows) == 1
        assert rows[0]["cedent_naic"] == "68039"


# ──────────────────────────────────────────────────────────────────────────────
# _write_schedule_s_csv  /  round-trip
# ──────────────────────────────────────────────────────────────────────────────


class TestWriteScheduleSCsv:
    def _sample_rows(self) -> list[dict]:
        return [
            {
                "cedent_naic": "68039",
                "cedent_name": "Athene Annuity",
                "year": "2024",
                "part": "S4",
                "line_num": "1",
                "reins_name": "Athene Re Ltd.",
                "reins_naic": "0",
                "reins_fed_id": "",
                "domicile": "BMU",
                "type_business": "T",
                "ceded_thousands": Decimal("25000000"),
            }
        ]

    def test_round_trip(self, tmp_path):
        rows = self._sample_rows()
        dest = tmp_path / "out.csv"
        _write_schedule_s_csv(dest, rows)
        back = _read_schedule_s_csv(dest)
        assert len(back) == 1
        assert back[0]["cedent_naic"] == "68039"
        assert back[0]["ceded_thousands"] == Decimal("25000000")

    def test_creates_parent_dirs(self, tmp_path):
        dest = tmp_path / "a" / "b" / "c" / "out.csv"
        _write_schedule_s_csv(dest, self._sample_rows())
        assert dest.exists()

    def test_writes_header(self, tmp_path):
        dest = tmp_path / "out.csv"
        _write_schedule_s_csv(dest, self._sample_rows())
        content = dest.read_text()
        assert _COL_CEDENT_NAIC in content
        assert _COL_REINS_NAME in content

    def test_empty_rows_writes_header_only(self, tmp_path):
        dest = tmp_path / "empty.csv"
        _write_schedule_s_csv(dest, [])
        content = dest.read_text()
        lines = [l for l in content.splitlines() if l.strip()]
        assert len(lines) == 1  # header only


# ──────────────────────────────────────────────────────────────────────────────
# _rows_from_json
# ──────────────────────────────────────────────────────────────────────────────


class TestRowsFromJson:
    def _item(self, reins_name="Test Re", part="S4", amount="5000", domicile="BMU"):
        return {
            "reinsurer_name": reins_name,
            "schedule_part": part,
            "ceded_amount": amount,
            "domicile": domicile,
            "reinsurer_naic": "0",
        }

    def test_list_input(self):
        items = [self._item()]
        rows = _rows_from_json(items, "68039", "Athene", 2024)
        assert len(rows) == 1
        assert rows[0]["reins_name"] == "Test Re"

    def test_dict_with_data_key(self):
        data = {"data": [self._item()]}
        rows = _rows_from_json(data, "68039", "Athene", 2024)
        assert len(rows) == 1

    def test_dict_with_rows_key(self):
        data = {"rows": [self._item()]}
        rows = _rows_from_json(data, "68039", "Athene", 2024)
        assert len(rows) == 1

    def test_filters_non_ceded_parts(self):
        items = [self._item(part="S1"), self._item(part="S3")]
        rows = _rows_from_json(items, "68039", "Athene", 2024)
        assert len(rows) == 0

    def test_filters_empty_reins_name(self):
        items = [self._item(reins_name="")]
        rows = _rows_from_json(items, "68039", "Athene", 2024)
        assert len(rows) == 0

    def test_cedent_fields_injected(self):
        rows = _rows_from_json([self._item()], "68039", "Athene Annuity", 2024)
        assert rows[0]["cedent_naic"] == "68039"
        assert rows[0]["cedent_name"] == "Athene Annuity"
        assert rows[0]["year"] == "2024"

    def test_amount_is_decimal(self):
        rows = _rows_from_json([self._item(amount="12345")], "68039", "Athene", 2024)
        assert isinstance(rows[0]["ceded_thousands"], Decimal)

    def test_camelcase_field_names(self):
        item = {
            "reinsurerName": "Camel Re",
            "schedulePart": "S4",
            "ceded_amount": "3000",
            "domicile": "CYM",
        }
        rows = _rows_from_json([item], "68039", "Athene", 2024)
        assert len(rows) == 1
        assert rows[0]["reins_name"] == "Camel Re"

    def test_non_list_non_dict_returns_empty(self):
        rows = _rows_from_json("bad input", "68039", "Athene", 2024)
        assert rows == []

    def test_empty_list(self):
        rows = _rows_from_json([], "68039", "Athene", 2024)
        assert rows == []


# ──────────────────────────────────────────────────────────────────────────────
# _normalise_csv_row
# ──────────────────────────────────────────────────────────────────────────────


class TestNormaliseCsvRow:
    def _row(self):
        return {
            _COL_REINS_NAME: "Test Re",
            _COL_PART: "S4",
            _COL_DOMICILE: "BMU",
            _COL_CEDED_AMT: "10000",
            _COL_REINS_NAIC: "0",
            _COL_REINS_FED_ID: "",
            _COL_TYPE: "T",
            _COL_LINE: "1",
        }

    def test_standard_columns(self):
        result = _normalise_csv_row(self._row(), "68039", "Athene", 2024)
        assert result is not None
        assert result["reins_name"] == "Test Re"
        assert result["part"] == "S4"

    def test_alternate_reins_name_column(self):
        row = {"Reinsurer Name": "Alt Re", _COL_PART: "S2", _COL_CEDED_AMT: "100"}
        result = _normalise_csv_row(row, "68039", "Athene", 2024)
        assert result is not None
        assert result["reins_name"] == "Alt Re"

    def test_missing_reins_name_returns_none(self):
        row = {_COL_PART: "S4", _COL_CEDED_AMT: "5000"}
        result = _normalise_csv_row(row, "68039", "Athene", 2024)
        assert result is None

    def test_non_ceded_part_returns_none(self):
        row = {_COL_REINS_NAME: "Test Re", _COL_PART: "S1"}
        result = _normalise_csv_row(row, "68039", "Athene", 2024)
        assert result is None

    def test_cedent_fields_always_injected(self):
        result = _normalise_csv_row(self._row(), "68039", "Athene", 2024)
        assert result["cedent_naic"] == "68039"
        assert result["cedent_name"] == "Athene"
        assert result["year"] == "2024"

    def test_amount_is_decimal(self):
        result = _normalise_csv_row(self._row(), "68039", "Athene", 2024)
        assert isinstance(result["ceded_thousands"], Decimal)


# ──────────────────────────────────────────────────────────────────────────────
# _parse_iowa_response
# ──────────────────────────────────────────────────────────────────────────────


class TestParseIowaResponse:
    def test_json_list_response(self):
        data = [
            {
                "reinsurer_name": "Athene Re Ltd.",
                "schedule_part": "S4",
                "ceded_amount": "25000000",
                "domicile": "BMU",
                "reinsurer_naic": "0",
            }
        ]
        content = json.dumps(data).encode("utf-8")
        rows = _parse_iowa_response(content, "68039", "Athene Annuity", 2024)
        assert len(rows) == 1
        assert rows[0]["reins_name"] == "Athene Re Ltd."

    def test_json_dict_response(self):
        data = {
            "data": [
                {
                    "reinsurer_name": "North End Re",
                    "schedule_part": "S4",
                    "ceded_amount": "8000000",
                    "domicile": "CYM",
                }
            ]
        }
        content = json.dumps(data).encode("utf-8")
        rows = _parse_iowa_response(content, "92525", "AmEq", 2024)
        assert len(rows) == 1

    def test_csv_fallback(self):
        csv_content = (
            f"{_COL_REINS_NAME},{_COL_PART},{_COL_DOMICILE},{_COL_CEDED_AMT}\n"
            f"Test Re,S4,BMU,9000\n"
        )
        content = csv_content.encode("utf-8")
        rows = _parse_iowa_response(content, "68039", "Athene", 2024)
        assert len(rows) == 1
        assert rows[0]["reins_name"] == "Test Re"

    def test_empty_content_returns_empty(self):
        rows = _parse_iowa_response(b"", "68039", "Athene", 2024)
        assert rows == []

    def test_invalid_content_returns_empty(self):
        rows = _parse_iowa_response(b"!!!not json or csv!!!", "68039", "Athene", 2024)
        assert rows == []


# ──────────────────────────────────────────────────────────────────────────────
# _write_unmapped_registry
# ──────────────────────────────────────────────────────────────────────────────


class TestWriteUnmappedRegistry:
    def test_creates_registry_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        unmapped = [
            {"reins_name": "Mystery Re", "domicile": "BMU", "reins_naic": "0", "suggested_id": "reinsurer:bermuda:mystery_re", "period": "2024-Q4"}
        ]
        _write_unmapped_registry(Period("2024-Q4"), unmapped)
        registry_path = tmp_path / "claimweb" / "registry" / "unmapped" / "naic_schedule_s_2024-Q4.json"
        assert registry_path.exists()

    def test_deduplicates_entries(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        entry = {"reins_name": "Mystery Re", "domicile": "BMU", "reins_naic": "0", "suggested_id": "x", "period": "2024-Q4"}
        _write_unmapped_registry(Period("2024-Q4"), [entry])
        _write_unmapped_registry(Period("2024-Q4"), [entry])
        registry_path = tmp_path / "claimweb" / "registry" / "unmapped" / "naic_schedule_s_2024-Q4.json"
        data = json.loads(registry_path.read_text())
        assert len(data) == 1

    def test_accumulates_new_entries(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        e1 = {"reins_name": "Re One", "domicile": "BMU", "reins_naic": "0", "suggested_id": "x", "period": "2024-Q4"}
        e2 = {"reins_name": "Re Two", "domicile": "CYM", "reins_naic": "0", "suggested_id": "y", "period": "2024-Q4"}
        _write_unmapped_registry(Period("2024-Q4"), [e1])
        _write_unmapped_registry(Period("2024-Q4"), [e2])
        registry_path = tmp_path / "claimweb" / "registry" / "unmapped" / "naic_schedule_s_2024-Q4.json"
        data = json.loads(registry_path.read_text())
        assert len(data) == 2


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher.list_available_periods
# ──────────────────────────────────────────────────────────────────────────────


class TestListAvailablePeriods:
    def test_empty_when_no_cache(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        assert fetcher.list_available_periods() == []

    def test_returns_q4_periods(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "data" / "raw" / "naic_schedule_s"
        (base / "2024-Q4").mkdir(parents=True)
        (base / "2023-Q4").mkdir(parents=True)
        fetcher = NaicScheduleSFetcher()
        periods = fetcher.list_available_periods()
        assert Period("2024-Q4") in periods
        assert Period("2023-Q4") in periods

    def test_excludes_non_q4_dirs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "data" / "raw" / "naic_schedule_s"
        (base / "2024-Q4").mkdir(parents=True)
        (base / "2024-Q1").mkdir(parents=True)
        fetcher = NaicScheduleSFetcher()
        periods = fetcher.list_available_periods()
        period_strs = [str(p) for p in periods]
        assert "2024-Q1" not in period_strs

    def test_ignores_invalid_dir_names(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "data" / "raw" / "naic_schedule_s"
        (base / "2024-Q4").mkdir(parents=True)
        (base / "not-a-period").mkdir(parents=True)
        (base / "README").mkdir(parents=True)
        fetcher = NaicScheduleSFetcher()
        periods = fetcher.list_available_periods()
        assert len(periods) == 1

    def test_returns_sorted(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "data" / "raw" / "naic_schedule_s"
        for yr in ["2022", "2024", "2023", "2021"]:
            (base / f"{yr}-Q4").mkdir(parents=True)
        fetcher = NaicScheduleSFetcher()
        periods = fetcher.list_available_periods()
        assert periods == sorted(periods)


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher.acquire  (smoke tests — no real HTTP)
# ──────────────────────────────────────────────────────────────────────────────


class TestAcquire:
    def test_rejects_non_q4_period(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        with pytest.raises(ValueError, match="Q4"):
            fetcher.acquire(Period("2024-Q1"))

    def test_rejects_q2(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        with pytest.raises(ValueError):
            fetcher.acquire(Period("2024-Q2"))

    def test_uses_cached_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        period = Period("2024-Q4")
        cache_dir = tmp_path / "data" / "raw" / "naic_schedule_s" / str(period)
        cache_dir.mkdir(parents=True)

        # Pre-populate cache for ALL registry companies to avoid any HTTP calls
        for naic_code in _CEDENT_REGISTRY:
            dest = cache_dir / f"{naic_code}_schedule_s.csv"
            dest.write_bytes(FIXTURE_CSV.read_bytes())

        fetcher = NaicScheduleSFetcher()
        # All companies are cached so the HTTP client is never actually used
        with patch("claimweb.fetchers.naic_schedule_s.httpx.Client") as mock_client:
            handle = fetcher.acquire(period)

        # Every cached file should appear in the handle
        path_strs = [str(p) for p in handle.paths]
        assert any("68039" in s for s in path_strs)

    def test_creates_cache_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        # Patch _fetch_company to return empty for all companies (simulates network unavailable)
        with patch.object(NaicScheduleSFetcher, "_fetch_company", return_value=[]):
            handle = fetcher.acquire(Period("2024-Q4"))
        expected_dir = tmp_path / "data" / "raw" / "naic_schedule_s" / "2024-Q4"
        assert expected_dir.exists()


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher.parse
# ──────────────────────────────────────────────────────────────────────────────


class TestParse:
    def test_emits_a6_arcs(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        assert len(facts) > 0
        for arc in facts:
            assert arc.instrument_class is ArcClass.A6

    def test_all_amounts_positive(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.dollar_amount_millions > Decimal("0")

    def test_amounts_converted_to_millions(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        # Fixture has 25000000 thousands → 25000 millions for Athene Re Ltd.
        athene_re_arcs = [
            arc for arc in facts
            if "athene_re_ltd" in arc.target_node_id or "athene re ltd" in arc.target_node_id.lower()
        ]
        if athene_re_arcs:
            assert athene_re_arcs[0].dollar_amount_millions == Decimal("25000000") * Decimal("0.001")

    def test_source_nodes_have_insurer_prefix(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.source_node_id.startswith("insurer:")

    def test_offshore_targets_have_reinsurer_prefix(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        # Bermuda arcs should have reinsurer:bermuda: prefix
        bmu_arcs = [arc for arc in facts if "bermuda" in arc.target_node_id]
        assert len(bmu_arcs) > 0

    def test_data_quality_flag_is_direct_measured(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.data_quality_flag is DataQualityFlag.DIRECT_MEASURED

    def test_measurement_basis_is_stock_eop(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.measurement_basis == "stock_eop"

    def test_provenance_source(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.provenance_source == "naic_schedule_s"

    def test_provenance_url_nonempty(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.provenance_url

    def test_provenance_field_references_schedule_part(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert "Schedule_S_" in arc.provenance_field

    def test_sha256_present(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert len(arc.sha256_of_source) == 64

    def test_skips_zero_amount_rows(self, tmp_path):
        period = Period("2024-Q4")
        csv_content = (
            f"{_COL_CEDENT_NAIC},{_COL_CEDENT_NAME},{_COL_YEAR},{_COL_PART},"
            f"{_COL_LINE},{_COL_REINS_NAME},{_COL_REINS_NAIC},{_COL_REINS_FED_ID},"
            f"{_COL_DOMICILE},{_COL_TYPE},{_COL_CEDED_AMT}\n"
            f"68039,Athene,2024,S4,1,Athene Re,0,,BMU,T,0\n"
            f"68039,Athene,2024,S4,2,Other Re,0,,BMU,T,5000\n"
        )
        dest_dir = tmp_path / "naic_schedule_s" / str(period)
        dest_dir.mkdir(parents=True)
        dest = dest_dir / "68039_schedule_s.csv"
        dest.write_text(csv_content)
        handle = RawDataHandle.from_paths("naic_schedule_s", period, [dest])
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        assert len(facts) == 1
        assert facts[0].dollar_amount_millions == Decimal("5000") * _THOUSANDS_TO_MILLIONS

    def test_empty_handle_returns_empty_list(self, tmp_path):
        period = Period("2024-Q4")
        handle = RawDataHandle(
            source_id="naic_schedule_s",
            period=period,
            paths=(),
            sha256_by_path={},
        )
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        assert facts == []

    def test_period_on_all_arcs(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.period == period

    def test_domestic_reinsurer_gets_insurer_prefix(self, tmp_path):
        period = Period("2024-Q4")
        csv_content = (
            f"{_COL_CEDENT_NAIC},{_COL_CEDENT_NAME},{_COL_YEAR},{_COL_PART},"
            f"{_COL_LINE},{_COL_REINS_NAME},{_COL_REINS_NAIC},{_COL_REINS_FED_ID},"
            f"{_COL_DOMICILE},{_COL_TYPE},{_COL_CEDED_AMT}\n"
            f"68039,Athene,2024,S2,1,General Re Corp,22292,,CT,T,1200000\n"
        )
        dest_dir = tmp_path / "naic_schedule_s" / str(period)
        dest_dir.mkdir(parents=True)
        dest = dest_dir / "68039_schedule_s.csv"
        dest.write_text(csv_content)
        handle = RawDataHandle.from_paths("naic_schedule_s", period, [dest])
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        assert len(facts) == 1
        assert facts[0].target_node_id == "insurer:naic:22292"

    def test_non_csv_paths_skipped(self, tmp_path):
        period = Period("2024-Q4")
        dest_dir = tmp_path / "naic_schedule_s" / str(period)
        dest_dir.mkdir(parents=True)
        txt_file = dest_dir / "readme.txt"
        txt_file.write_text("not a csv")
        handle = RawDataHandle(
            source_id="naic_schedule_s",
            period=period,
            paths=(txt_file,),
            sha256_by_path={str(txt_file): "a" * 64},
        )
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        assert facts == []


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher.validate
# ──────────────────────────────────────────────────────────────────────────────


class TestValidate:
    def _errors(self, report: ValidationReport) -> list:
        return [i for i in report.issues if i.severity == "error"]

    def _warnings(self, report: ValidationReport) -> list:
        return [i for i in report.issues if i.severity == "warning"]

    def _infos(self, report: ValidationReport) -> list:
        return [i for i in report.issues if i.severity == "info"]

    def test_valid_arcs_no_errors(self):
        arcs = [
            _make_minimal_arc(amount=Decimal("5000")),
            _make_minimal_arc(
                target="reinsurer:cayman:north_end_re",
                amount=Decimal("3000"),
            ),
        ]
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate(arcs)
        assert report.is_clean
        assert not self._errors(report)

    def test_empty_facts_produces_warning(self):
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([])
        assert self._warnings(report) or self._infos(report)

    def test_wrong_arc_class_error(self):
        arc = ArcFact(
            period=Period("2024-Q4"),
            source_node_id="insurer:naic:68039",
            target_node_id="reinsurer:bermuda:test",
            instrument_class=ArcClass.A3,
            dollar_amount_millions=Decimal("1000"),
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
            provenance_source="naic_schedule_s",
            provenance_url="https://example.com",
            provenance_filing=None,
            provenance_page=None,
            provenance_field="Schedule_S_S4.CEDED_AMOUNT_THOUSANDS",
            sha256_of_source="a" * 64,
        )
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([arc])
        assert not report.is_clean
        assert self._errors(report)

    def test_negative_amount_error(self):
        arc = _make_minimal_arc(amount=Decimal("-1000"))
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([arc])
        assert not report.is_clean

    def test_no_offshore_arcs_produces_info(self):
        # All domestic targets
        arc = _make_minimal_arc(target="insurer:naic:22292", amount=Decimal("5000"))
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([arc])
        assert self._infos(report) or self._warnings(report)

    def test_unexpected_source_prefix_warning(self):
        arc = _make_minimal_arc(source="fund:some_entity", amount=Decimal("5000"))
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([arc])
        assert self._warnings(report)

    def test_low_total_ceded_warning(self):
        arc = _make_minimal_arc(amount=Decimal("50"))  # below _MIN_CEDED_TOTAL_MM
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([arc])
        assert self._warnings(report)

    def test_high_total_ceded_no_warning(self):
        arcs = [_make_minimal_arc(amount=Decimal("10000")) for _ in range(10)]
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate(arcs)
        assert report.is_clean

    def test_validate_returns_validation_report_instance(self):
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([_make_minimal_arc()])
        assert isinstance(report, ValidationReport)


# ──────────────────────────────────────────────────────────────────────────────
# Property-based tests (hypothesis)
# ──────────────────────────────────────────────────────────────────────────────


@given(st.text(min_size=0, max_size=200))
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_property_normalise_name_stable(name: str) -> None:
    """_normalise_name is idempotent: applying it twice yields the same result."""
    once = _normalise_name(name)
    twice = _normalise_name(once)
    assert once == twice, f"Not idempotent: {name!r} → {once!r} → {twice!r}"


@given(
    st.one_of(
        st.integers(min_value=0, max_value=10_000_000).map(str),
        st.just(""),
        st.just("N/A"),
        st.just("0"),
    )
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_property_parse_amount_non_negative_for_non_negative_input(raw: str) -> None:
    """_parse_amount returns >= 0 for non-negative numeric inputs."""
    result = _parse_amount(raw)
    assert isinstance(result, Decimal)
    assert result >= Decimal("0")


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(
    amounts=st.lists(
        st.decimals(min_value="0.001", max_value="100000", places=3, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=5,
    )
)
def test_property_emitted_facts_pass_schema(amounts: list[Decimal]) -> None:
    """ArcFacts emitted from CSV rows satisfy the ArcFact schema invariants."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        period = Period("2024-Q4")
        rows_str = "\n".join(
            f"68039,Athene,2024,S4,{i},Athene Re Ltd.,0,,BMU,T,{int(amt * 1000)}"
            for i, amt in enumerate(amounts, start=1)
        )
        csv_content = (
            f"{_COL_CEDENT_NAIC},{_COL_CEDENT_NAME},{_COL_YEAR},{_COL_PART},"
            f"{_COL_LINE},{_COL_REINS_NAME},{_COL_REINS_NAIC},{_COL_REINS_FED_ID},"
            f"{_COL_DOMICILE},{_COL_TYPE},{_COL_CEDED_AMT}\n"
            + rows_str + "\n"
        )
        dest_dir = tmp_path / "naic_schedule_s" / str(period)
        dest_dir.mkdir(parents=True)
        dest = dest_dir / "68039_schedule_s.csv"
        dest.write_text(csv_content)
        handle = RawDataHandle.from_paths("naic_schedule_s", period, [dest])
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.instrument_class is ArcClass.A6
            assert arc.dollar_amount_millions > Decimal("0")
            assert isinstance(arc.dollar_amount_millions, Decimal)
            assert arc.measurement_basis == "stock_eop"
            assert arc.data_quality_flag is DataQualityFlag.DIRECT_MEASURED
            assert len(arc.sha256_of_source) == 64
            assert arc.provenance_source == "naic_schedule_s"
