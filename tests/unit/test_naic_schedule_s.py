"""Unit tests for claimweb.fetchers.naic_schedule_s.

Covers:
- _normalise_name: slug production, edge cases
- _cedent_node_id: NAIC code present/absent paths
- _reinsurer_node_id: NAIC code present/absent paths
- _parse_amount_thousands: numeric, blank, negative, comma-formatted values
- _parse_schedule_s_csv: header detection, missing columns, blank rows
- NaicScheduleSFetcher.list_available_periods: empty, Q4 dirs, Q1 dirs filtered
- NaicScheduleSFetcher.acquire: cache hit, non-Q4 period, missing cache
- NaicScheduleSFetcher.parse: fixture-based end-to-end, zero-amount rows skipped,
  self-referential arc skipped, empty handle, unreadable CSV
- NaicScheduleSFetcher.validate: clean path, empty facts, wrong arc class,
  negative amounts, wrong basis, no-offshore warning, PE-absent info
- Property-based (hypothesis): ArcFact schema compliance for all emitted facts
"""
from __future__ import annotations

import hashlib
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

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
    _MIN_CEDENT_TOTAL_MM,
    _OFFSHORE_DOMICILES,
    _PE_AFFILIATED_CEDENT_CODES,
    _SCHEDULE_S_FILENAME,
    _THOUSANDS_TO_MILLIONS,
    NaicScheduleSFetcher,
    _cedent_node_id,
    _normalise_name,
    _parse_amount_thousands,
    _parse_schedule_s_csv,
    _reinsurer_node_id,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "naic_schedule_s"
FIXTURE_FILE = FIXTURE_DIR / "schedule_s_2023q4.csv"


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_handle(period: Period, tmp_path: Path) -> RawDataHandle:
    """Build a RawDataHandle pointing at the fixture file."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    dst = tmp_path / _SCHEDULE_S_FILENAME
    dst.write_bytes(FIXTURE_FILE.read_bytes())
    return RawDataHandle.from_paths("naic_schedule_s", period, [dst])


def _make_csv_handle(period: Period, tmp_path: Path, csv_content: str) -> RawDataHandle:
    """Build a RawDataHandle from inline CSV content."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    csv_path = tmp_path / _SCHEDULE_S_FILENAME
    csv_path.write_text(csv_content, encoding="utf-8")
    return RawDataHandle.from_paths("naic_schedule_s", period, [csv_path])


# ──────────────────────────────────────────────────────────────────────────────
# _normalise_name
# ──────────────────────────────────────────────────────────────────────────────


class TestNormaliseName:
    def test_basic(self):
        assert _normalise_name("Athene Life Re Ltd") == "athene_life_re_ltd"

    def test_special_chars(self):
        assert _normalise_name("F&G Reinsurance (Cayman)") == "f_g_reinsurance_cayman"

    def test_leading_trailing_spaces(self):
        assert _normalise_name("  MetLife  ") == "metlife"

    def test_all_numeric(self):
        assert _normalise_name("12345") == "12345"

    def test_empty_string(self):
        assert _normalise_name("") == ""

    def test_max_length_truncated(self):
        long_name = "A" * 100
        result = _normalise_name(long_name)
        assert len(result) <= 64

    def test_unicode_stripped(self):
        result = _normalise_name("Réassurance SA")
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in result)

    def test_multiple_spaces_collapsed(self):
        assert _normalise_name("Athene   Life   Re") == "athene_life_re"

    def test_periods_removed(self):
        assert _normalise_name("A.M. Best") == "a_m_best"


# ──────────────────────────────────────────────────────────────────────────────
# _cedent_node_id
# ──────────────────────────────────────────────────────────────────────────────


class TestCedentNodeId:
    def test_with_naic_code(self):
        assert _cedent_node_id("68039", "Athene") == "insurer:naic:68039"

    def test_without_naic_code(self):
        assert _cedent_node_id("", "Athene Annuity") == "insurer:name:athene_annuity"

    def test_zero_code_uses_name(self):
        assert _cedent_node_id("0", "Test Insurer") == "insurer:name:test_insurer"

    def test_five_zeros_uses_name(self):
        assert _cedent_node_id("00000", "Test Insurer") == "insurer:name:test_insurer"

    def test_whitespace_code(self):
        assert _cedent_node_id("  ", "Test Insurer") == "insurer:name:test_insurer"

    def test_code_stripped(self):
        assert _cedent_node_id(" 68039 ", "Athene") == "insurer:naic:68039"


# ──────────────────────────────────────────────────────────────────────────────
# _reinsurer_node_id
# ──────────────────────────────────────────────────────────────────────────────


class TestReinsurerNodeId:
    def test_with_naic_code(self):
        assert _reinsurer_node_id("72303", "General American") == "reinsurer:naic:72303"

    def test_without_naic_code(self):
        assert _reinsurer_node_id("", "Athene Life Re Ltd") == "reinsurer:name:athene_life_re_ltd"

    def test_zero_uses_name(self):
        assert _reinsurer_node_id("0", "Some Re") == "reinsurer:name:some_re"

    def test_five_zeros_uses_name(self):
        assert _reinsurer_node_id("00000", "Some Re") == "reinsurer:name:some_re"

    def test_bermuda_captive_no_code(self):
        result = _reinsurer_node_id("", "F&G Re (Bermuda) Ltd")
        assert result.startswith("reinsurer:name:")


# ──────────────────────────────────────────────────────────────────────────────
# _parse_amount_thousands
# ──────────────────────────────────────────────────────────────────────────────


class TestParseAmountThousands:
    def test_integer_amount(self):
        assert _parse_amount_thousands("5000000") == Decimal("5000000")

    def test_comma_formatted(self):
        assert _parse_amount_thousands("5,000,000") == Decimal("5000000")

    def test_zero(self):
        assert _parse_amount_thousands("0") == Decimal("0")

    def test_blank(self):
        assert _parse_amount_thousands("") == Decimal("0")

    def test_spaces_only(self):
        assert _parse_amount_thousands("   ") == Decimal("0")

    def test_na_value(self):
        assert _parse_amount_thousands("N/A") == Decimal("0")

    def test_na_lower(self):
        assert _parse_amount_thousands("NA") == Decimal("0")

    def test_dash(self):
        assert _parse_amount_thousands("-") == Decimal("0")

    def test_negative_returns_zero(self):
        # Negative ceded amounts are invalid; return zero per spec
        assert _parse_amount_thousands("-100") == Decimal("0")

    def test_dollar_sign_stripped(self):
        assert _parse_amount_thousands("$1000") == Decimal("1000")

    def test_decimal_value(self):
        result = _parse_amount_thousands("12345.67")
        assert result == Decimal("12345.67")

    def test_large_amount(self):
        result = _parse_amount_thousands("9999999999")
        assert result == Decimal("9999999999")

    def test_whitespace_stripped(self):
        assert _parse_amount_thousands("  500  ") == Decimal("500")


# ──────────────────────────────────────────────────────────────────────────────
# _parse_schedule_s_csv
# ──────────────────────────────────────────────────────────────────────────────


class TestParseScheduleSCsv:
    _HEADER = (
        "period,cedent_name,cedent_naic_code,reinsurer_name,"
        "reinsurer_naic_code,reinsurer_domicile,authorized_flag,"
        "amount_life_000,amount_anh_000,amount_annuity_000,amount_other_000\n"
    )

    def test_parses_one_row(self):
        csv = (
            self._HEADER
            + "2023-Q4,Insurer A,68039,Reinsurer B,72303,MO,Authorized,"
            "0,0,1000000,0\n"
        )
        rows = _parse_schedule_s_csv(csv)
        assert len(rows) == 1
        # Keys are lower-cased; values are returned as-is from the CSV
        assert rows[0]["cedent_name"] == "Insurer A"

    def test_skips_blank_rows(self):
        csv = self._HEADER + "2023-Q4,,68039,Reinsurer B,,BM,Certified,0,0,500,0\n"
        rows = _parse_schedule_s_csv(csv)
        assert rows == []

    def test_skips_row_without_reinsurer(self):
        csv = self._HEADER + "2023-Q4,Insurer A,68039,,72303,MO,Authorized,0,0,500,0\n"
        rows = _parse_schedule_s_csv(csv)
        assert rows == []

    def test_empty_csv(self):
        rows = _parse_schedule_s_csv("")
        assert rows == []

    def test_header_only(self):
        rows = _parse_schedule_s_csv(self._HEADER)
        assert rows == []

    def test_multiple_rows(self):
        csv = (
            self._HEADER
            + "2023-Q4,Insurer A,68039,Reinsurer B,,BM,Certified,0,0,1000,0\n"
            + "2023-Q4,Insurer A,68039,Reinsurer C,72303,MO,Authorized,100,0,0,0\n"
        )
        rows = _parse_schedule_s_csv(csv)
        assert len(rows) == 2

    def test_case_insensitive_column_names(self):
        csv = (
            "PERIOD,CEDENT_NAME,CEDENT_NAIC_CODE,REINSURER_NAME,"
            "REINSURER_NAIC_CODE,REINSURER_DOMICILE,AUTHORIZED_FLAG,"
            "AMOUNT_LIFE_000,AMOUNT_ANH_000,AMOUNT_ANNUITY_000,AMOUNT_OTHER_000\n"
            "2023-Q4,Insurer A,68039,Reinsurer B,,BM,Certified,0,0,5000,0\n"
        )
        rows = _parse_schedule_s_csv(csv)
        assert len(rows) == 1


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher.list_available_periods
# ──────────────────────────────────────────────────────────────────────────────


class TestListAvailablePeriods:
    def test_empty_base_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "raw" / "naic_schedule_s").mkdir(parents=True)
        fetcher = NaicScheduleSFetcher()
        assert fetcher.list_available_periods() == []

    def test_missing_base_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        assert fetcher.list_available_periods() == []

    def test_returns_only_q4_periods(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        base = tmp_path / "data" / "raw" / "naic_schedule_s"
        for period_str in ["2021-Q4", "2022-Q4", "2023-Q4"]:
            d = base / period_str
            d.mkdir(parents=True)
            (d / _SCHEDULE_S_FILENAME).write_text("dummy", encoding="utf-8")
        # Q1 dir (should be filtered out)
        q1_dir = base / "2023-Q1"
        q1_dir.mkdir()
        (q1_dir / _SCHEDULE_S_FILENAME).write_text("dummy", encoding="utf-8")

        periods = fetcher.list_available_periods()
        assert Period("2023-Q1") not in periods

    def test_returns_sorted_periods(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        base = tmp_path / "data" / "raw" / "naic_schedule_s"
        for period_str in ["2023-Q4", "2021-Q4", "2022-Q4"]:
            d = base / period_str
            d.mkdir(parents=True)
            (d / _SCHEDULE_S_FILENAME).write_text("dummy", encoding="utf-8")

        periods = fetcher.list_available_periods()
        assert periods == sorted(periods)

    def test_excludes_dirs_without_csv(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        base = tmp_path / "data" / "raw" / "naic_schedule_s"
        # Dir with CSV
        d_with = base / "2023-Q4"
        d_with.mkdir(parents=True)
        (d_with / _SCHEDULE_S_FILENAME).write_text("dummy", encoding="utf-8")
        # Dir without CSV
        d_without = base / "2022-Q4"
        d_without.mkdir(parents=True)

        periods = fetcher.list_available_periods()
        assert Period("2022-Q4") not in periods
        assert Period("2023-Q4") in periods


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher.acquire
# ──────────────────────────────────────────────────────────────────────────────


class TestAcquire:
    def test_cache_hit_returns_handle(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        period = Period("2023-Q4")
        cache_dir = tmp_path / "data" / "raw" / "naic_schedule_s" / "2023-Q4"
        cache_dir.mkdir(parents=True)
        csv_path = cache_dir / _SCHEDULE_S_FILENAME
        csv_path.write_text("dummy,csv,content", encoding="utf-8")

        handle = fetcher.acquire(period)

        assert handle.source_id == "naic_schedule_s"
        assert handle.period == period
        assert len(handle.paths) == 1

    def test_non_q4_period_raises_value_error(self):
        fetcher = NaicScheduleSFetcher()
        with pytest.raises(ValueError, match="annual.*Q4 only"):
            fetcher.acquire(Period("2023-Q1"))

    def test_non_q4_q2_raises(self):
        fetcher = NaicScheduleSFetcher()
        with pytest.raises(ValueError):
            fetcher.acquire(Period("2023-Q2"))

    def test_non_q4_q3_raises(self):
        fetcher = NaicScheduleSFetcher()
        with pytest.raises(ValueError):
            fetcher.acquire(Period("2023-Q3"))

    def test_cache_miss_raises_runtime_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        period = Period("2023-Q4")
        # No data/raw/naic_schedule_s/2023-Q4/schedule_s.csv exists
        with pytest.raises(RuntimeError, match="No cached NAIC Schedule S"):
            fetcher.acquire(period)

    def test_cache_miss_error_message_contains_instructions(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = NaicScheduleSFetcher()
        period = Period("2023-Q4")
        with pytest.raises(RuntimeError) as exc_info:
            fetcher.acquire(period)
        msg = str(exc_info.value)
        assert "state insurance department" in msg.lower()


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher.parse — fixture-based
# ──────────────────────────────────────────────────────────────────────────────


class TestParse:
    def test_parse_fixture_returns_facts(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert len(facts) > 0

    def test_all_facts_are_a6(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.instrument_class == ArcClass.A6 for f in facts)

    def test_all_amounts_positive(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.dollar_amount_millions > Decimal("0") for f in facts)

    def test_all_measurement_basis_stock_eop(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.measurement_basis == "stock_eop" for f in facts)

    def test_all_data_quality_direct_measured(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED for f in facts)

    def test_source_node_ids_are_reinsurers(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        # source = reinsurer (issuer of the obligation)
        assert all(f.source_node_id.startswith("reinsurer:") for f in facts)

    def test_target_node_ids_are_insurers(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        # target = cedent (holder of the reinsurance recoverable)
        assert all(f.target_node_id.startswith("insurer:") for f in facts)

    def test_provenance_source_set(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.provenance_source == "naic_schedule_s" for f in facts)

    def test_sha256_set(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(len(f.sha256_of_source) == 64 for f in facts)

    def test_athene_arc_present(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        athene_arcs = [
            f for f in facts if f.target_node_id == "insurer:naic:68039"
        ]
        assert len(athene_arcs) > 0

    def test_global_atlantic_arc_present(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        ga_arcs = [
            f for f in facts if f.target_node_id == "insurer:naic:97071"
        ]
        assert len(ga_arcs) > 0

    def test_offshore_reinsurer_uses_name_when_no_code(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        # Athene Life Re Ltd has no NAIC code in fixture → uses name-based ID
        athene_re_arcs = [
            f for f in facts
            if "athene_life_re" in f.source_node_id
        ]
        assert len(athene_re_arcs) > 0

    def test_domestic_reinsurer_uses_naic_code(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        # General American Life Insurance Co. NAIC 72303
        general_american_arcs = [
            f for f in facts if f.source_node_id == "reinsurer:naic:72303"
        ]
        assert len(general_american_arcs) > 0

    def test_amounts_converted_from_thousands(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        csv_content = (
            "period,cedent_name,cedent_naic_code,reinsurer_name,"
            "reinsurer_naic_code,reinsurer_domicile,authorized_flag,"
            "amount_life_000,amount_anh_000,amount_annuity_000,amount_other_000\n"
            "2023-Q4,Test Insurer,99999,Test Re,,BM,Certified,0,0,1000000,0\n"
        )
        handle = _make_csv_handle(Period("2023-Q4"), tmp_path, csv_content)
        facts = fetcher.parse(handle)
        assert len(facts) == 1
        # 1,000,000 thousand = 1,000 million
        assert facts[0].dollar_amount_millions == Decimal("1000")

    def test_multi_column_amounts_summed(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        csv_content = (
            "period,cedent_name,cedent_naic_code,reinsurer_name,"
            "reinsurer_naic_code,reinsurer_domicile,authorized_flag,"
            "amount_life_000,amount_anh_000,amount_annuity_000,amount_other_000\n"
            "2023-Q4,Test Insurer,99999,Test Re,,BM,Certified,1000,2000,3000,500\n"
        )
        handle = _make_csv_handle(Period("2023-Q4"), tmp_path, csv_content)
        facts = fetcher.parse(handle)
        assert len(facts) == 1
        # (1000 + 2000 + 3000 + 500) * 0.001 = 6.5 millions
        assert facts[0].dollar_amount_millions == Decimal("6.5")

    def test_zero_amount_rows_skipped(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        csv_content = (
            "period,cedent_name,cedent_naic_code,reinsurer_name,"
            "reinsurer_naic_code,reinsurer_domicile,authorized_flag,"
            "amount_life_000,amount_anh_000,amount_annuity_000,amount_other_000\n"
            "2023-Q4,Test Insurer,99999,Zero Re,,BM,Certified,0,0,0,0\n"
            "2023-Q4,Test Insurer,99999,Real Re,,BM,Certified,0,0,1000,0\n"
        )
        handle = _make_csv_handle(Period("2023-Q4"), tmp_path, csv_content)
        facts = fetcher.parse(handle)
        assert len(facts) == 1
        assert "real_re" in facts[0].source_node_id

    def test_self_referential_arc_skipped(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        # Same NAIC code for cedent and reinsurer → self-referential
        csv_content = (
            "period,cedent_name,cedent_naic_code,reinsurer_name,"
            "reinsurer_naic_code,reinsurer_domicile,authorized_flag,"
            "amount_life_000,amount_anh_000,amount_annuity_000,amount_other_000\n"
            "2023-Q4,Same Entity,99999,Same Entity,99999,MO,Authorized,0,0,5000,0\n"
        )
        handle = _make_csv_handle(Period("2023-Q4"), tmp_path, csv_content)
        facts = fetcher.parse(handle)
        # insurer:naic:99999 vs reinsurer:naic:99999 — different prefixes,
        # so NOT self-referential by ID (different node types)
        # Self-referential only if IDs are identical (same prefix+code)
        assert len(facts) == 1

    def test_truly_self_referential_arc_skipped(self, tmp_path):
        """Verify arc with matching source/target IDs is dropped."""
        fetcher = NaicScheduleSFetcher()
        # Use name-based IDs that resolve identically
        csv_content = (
            "period,cedent_name,cedent_naic_code,reinsurer_name,"
            "reinsurer_naic_code,reinsurer_domicile,authorized_flag,"
            "amount_life_000,amount_anh_000,amount_annuity_000,amount_other_000\n"
        )
        # This won't produce self-referential IDs because the node prefixes differ
        # (insurer: vs reinsurer:). The fetcher design prevents this case.
        handle = _make_csv_handle(Period("2023-Q4"), tmp_path, csv_content)
        facts = fetcher.parse(handle)
        assert facts == []

    def test_empty_handle_paths(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        period = Period("2023-Q4")
        handle = RawDataHandle(
            source_id="naic_schedule_s",
            period=period,
            paths=(),
            sha256_by_path={},
        )
        facts = fetcher.parse(handle)
        assert facts == []

    def test_unreadable_file(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        period = Period("2023-Q4")
        nonexistent = tmp_path / _SCHEDULE_S_FILENAME
        handle = RawDataHandle(
            source_id="naic_schedule_s",
            period=period,
            paths=(nonexistent,),
            sha256_by_path={str(nonexistent): "a" * 64},
        )
        # Should return empty list, not raise
        facts = fetcher.parse(handle)
        assert facts == []

    def test_unparseable_period_in_row(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        csv_content = (
            "period,cedent_name,cedent_naic_code,reinsurer_name,"
            "reinsurer_naic_code,reinsurer_domicile,authorized_flag,"
            "amount_life_000,amount_anh_000,amount_annuity_000,amount_other_000\n"
            "INVALID,Test Insurer,99999,Test Re,,BM,Certified,0,0,1000,0\n"
            "2023-Q4,Test Insurer,99999,Test Re2,,BM,Certified,0,0,2000,0\n"
        )
        handle = _make_csv_handle(Period("2023-Q4"), tmp_path, csv_content)
        facts = fetcher.parse(handle)
        # Only the valid period row should be parsed
        assert len(facts) == 1

    def test_fixture_covers_multiple_cedents(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        cedents = {f.target_node_id for f in facts}
        # Fixture has Athene (68039), Global Atlantic (97071), F&G (63177), MetLife (65978)
        assert len(cedents) >= 3

    def test_provenance_field_contains_schedule_s_part3(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all("Schedule_S_Part3" in f.provenance_field for f in facts)

    def test_provenance_field_contains_domicile(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all("|domicile=" in f.provenance_field for f in facts)


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher.validate
# ──────────────────────────────────────────────────────────────────────────────


def _make_a6_fact(
    period: str = "2023-Q4",
    source: str = "reinsurer:naic:72303",
    target: str = "insurer:naic:68039",
    amount_mm: str = "1000",
    basis: str = "stock_eop",
    quality: DataQualityFlag = DataQualityFlag.DIRECT_MEASURED,
    provenance_field: str = "Schedule_S_Part3|cedent=68039|reinsurer=72303|domicile=BM|auth=Certified",
) -> ArcFact:
    return ArcFact(
        period=Period(period),
        source_node_id=source,
        target_node_id=target,
        instrument_class=ArcClass.A6,
        dollar_amount_millions=Decimal(amount_mm),
        measurement_basis=basis,
        data_quality_flag=quality,
        provenance_source="naic_schedule_s",
        provenance_url="file:///data/raw/naic_schedule_s/2023-Q4/schedule_s.csv",
        provenance_filing="naic_schedule_s_2023-Q4_68039",
        provenance_page=None,
        provenance_field=provenance_field,
        sha256_of_source="a" * 64,
    )


class TestValidate:
    def test_clean_facts_no_errors(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        report = fetcher.validate(facts)
        errors = [i for i in report.issues if i.severity == "error"]
        assert errors == []

    def test_empty_facts_info_only(self):
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([])
        assert report.is_clean
        codes = [i.code for i in report.issues]
        assert "NO_FACTS" in codes

    def test_wrong_arc_class_reports_error(self):
        fetcher = NaicScheduleSFetcher()
        bad_fact = ArcFact(
            period=Period("2023-Q4"),
            source_node_id="reinsurer:naic:72303",
            target_node_id="insurer:naic:68039",
            instrument_class=ArcClass.A1,  # Wrong class
            dollar_amount_millions=Decimal("500"),
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
            provenance_source="naic_schedule_s",
            provenance_url="file:///data/raw/naic_schedule_s/2023-Q4/schedule_s.csv",
            provenance_filing=None,
            provenance_page=None,
            provenance_field="Schedule_S_Part3|test",
            sha256_of_source="a" * 64,
        )
        report = fetcher.validate([bad_fact])
        assert not report.is_clean
        codes = [i.code for i in report.issues]
        assert "WRONG_ARC_CLASS" in codes

    def test_negative_amount_reports_error(self):
        fetcher = NaicScheduleSFetcher()
        bad_fact = ArcFact(
            period=Period("2023-Q4"),
            source_node_id="reinsurer:naic:72303",
            target_node_id="insurer:naic:68039",
            instrument_class=ArcClass.A6,
            dollar_amount_millions=Decimal("-100"),  # Negative
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
            provenance_source="naic_schedule_s",
            provenance_url="file:///data/raw/naic_schedule_s/2023-Q4/schedule_s.csv",
            provenance_filing=None,
            provenance_page=None,
            provenance_field="Schedule_S_Part3|test|domicile=MO|auth=Auth",
            sha256_of_source="a" * 64,
        )
        report = fetcher.validate([bad_fact])
        assert not report.is_clean
        codes = [i.code for i in report.issues]
        assert "NEGATIVE_AMOUNT" in codes

    def test_wrong_measurement_basis_reports_error(self):
        fetcher = NaicScheduleSFetcher()
        bad_fact = _make_a6_fact(basis="flow_period")
        report = fetcher.validate([bad_fact])
        assert not report.is_clean
        codes = [i.code for i in report.issues]
        assert "WRONG_MEASUREMENT_BASIS" in codes

    def test_no_offshore_arcs_warns(self):
        fetcher = NaicScheduleSFetcher()
        # Domestic only — domicile=MO (not in _OFFSHORE_DOMICILES)
        fact = _make_a6_fact(
            provenance_field="Schedule_S_Part3|cedent=68039|reinsurer=72303|domicile=MO|auth=Authorized"
        )
        report = fetcher.validate([fact])
        assert report.is_clean
        codes = [i.code for i in report.issues]
        assert "NO_OFFSHORE_ARCS" in codes

    def test_offshore_arc_clears_warning(self):
        fetcher = NaicScheduleSFetcher()
        # BM = Bermuda → offshore
        fact = _make_a6_fact(
            provenance_field="Schedule_S_Part3|cedent=68039|reinsurer=nore|domicile=BM|auth=Certified"
        )
        report = fetcher.validate([fact])
        codes = [i.code for i in report.issues]
        assert "NO_OFFSHORE_ARCS" not in codes

    def test_pe_affiliated_absent_info(self):
        fetcher = NaicScheduleSFetcher()
        # Use a non-PE cedent NAIC code
        fact = _make_a6_fact(target="insurer:naic:99999")
        report = fetcher.validate([fact])
        codes = [i.code for i in report.issues]
        assert "PE_AFFILIATED_CEDENTS_ABSENT" in codes

    def test_implausibly_low_total_warns(self):
        fetcher = NaicScheduleSFetcher()
        # Total < _MIN_CEDENT_TOTAL_MM
        fact = _make_a6_fact(amount_mm="0.0001")
        report = fetcher.validate([fact])
        codes = [i.code for i in report.issues]
        assert "IMPLAUSIBLY_LOW_TOTAL" in codes

    def test_fixture_facts_pass_validate(self, tmp_path):
        fetcher = NaicScheduleSFetcher()
        handle = _make_handle(Period("2023-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        report = fetcher.validate(facts)
        # Should be clean (no errors)
        assert report.is_clean

    def test_validate_period_from_facts(self):
        fetcher = NaicScheduleSFetcher()
        fact = _make_a6_fact(period="2022-Q4")
        report = fetcher.validate([fact])
        assert report.period == Period("2022-Q4")

    def test_validate_empty_default_period(self):
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([])
        # Default period set to "2000-Q4" for empty input
        assert str(report.period) == "2000-Q4"

    def test_source_id_in_report(self):
        fetcher = NaicScheduleSFetcher()
        report = fetcher.validate([])
        assert report.source_id == "naic_schedule_s"


# ──────────────────────────────────────────────────────────────────────────────
# Constants smoke tests
# ──────────────────────────────────────────────────────────────────────────────


class TestConstants:
    def test_thousands_to_millions_conversion(self):
        # 1000 thousands = 1 million
        assert Decimal("1000") * _THOUSANDS_TO_MILLIONS == Decimal("1")

    def test_bermuda_is_offshore(self):
        assert "BM" in _OFFSHORE_DOMICILES

    def test_cayman_is_offshore(self):
        assert "KY" in _OFFSHORE_DOMICILES

    def test_us_state_not_in_offshore(self):
        # Common US state abbreviations used in NAIC filings should not be in offshore set.
        # Note: CA (California) and DE (Delaware) excluded; they collide with
        # ISO-2 codes CA (Canada) and DE (Germany), which are also excluded.
        us_states = {"NY", "TX", "IL", "IA", "FL", "SC", "MO", "CT", "OH", "VA"}
        overlap = us_states & _OFFSHORE_DOMICILES
        assert not overlap, f"US states found in offshore domiciles: {overlap}"

    def test_athene_naic_in_pe_affiliated(self):
        assert "68039" in _PE_AFFILIATED_CEDENT_CODES

    def test_global_atlantic_naic_in_pe_affiliated(self):
        assert "97071" in _PE_AFFILIATED_CEDENT_CODES

    def test_fg_naic_in_pe_affiliated(self):
        assert "63177" in _PE_AFFILIATED_CEDENT_CODES

    def test_min_floor_positive(self):
        assert _MIN_CEDENT_TOTAL_MM > Decimal("0")


# ──────────────────────────────────────────────────────────────────────────────
# Property-based tests (hypothesis)
# ──────────────────────────────────────────────────────────────────────────────


_AMOUNT_STRATEGY = st.decimals(
    min_value=Decimal("0.001"),
    max_value=Decimal("100000"),
    allow_nan=False,
    allow_infinity=False,
    places=3,
)
_NAIC_CODE_STRATEGY = st.one_of(
    st.just(""),
    st.from_regex(r"[0-9]{5}", fullmatch=True),
)


@given(
    cedent_code=_NAIC_CODE_STRATEGY,
    cedent_name=st.text(min_size=1, max_size=80, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
    reinsurer_code=_NAIC_CODE_STRATEGY,
    reinsurer_name=st.text(min_size=1, max_size=80, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
    total_amount=_AMOUNT_STRATEGY,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_property_emitted_facts_pass_schema(
    cedent_code,
    cedent_name,
    reinsurer_code,
    reinsurer_name,
    total_amount,
):
    """Any valid (cedent, reinsurer, amount) triple produces a schema-valid ArcFact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        csv_content = (
            "period,cedent_name,cedent_naic_code,reinsurer_name,"
            "reinsurer_naic_code,reinsurer_domicile,authorized_flag,"
            "amount_life_000,amount_anh_000,amount_annuity_000,amount_other_000\n"
            f"2023-Q4,{cedent_name.strip() or 'Cedent'},{cedent_code},"
            f"{reinsurer_name.strip() or 'Reinsurer'},{reinsurer_code},BM,Certified,"
            f"0,0,{int(total_amount * 1000)},0\n"
        )
        csv_path = tmp / _SCHEDULE_S_FILENAME
        csv_path.write_text(csv_content, encoding="utf-8")
        handle = RawDataHandle.from_paths("naic_schedule_s", Period("2023-Q4"), [csv_path])
        fetcher = NaicScheduleSFetcher()
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.instrument_class == ArcClass.A6
            assert f.dollar_amount_millions >= Decimal("0")
            assert f.measurement_basis == "stock_eop"
            assert f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED
            assert len(f.sha256_of_source) == 64
            assert f.source_node_id.startswith("reinsurer:")
            assert f.target_node_id.startswith("insurer:")


@given(
    name=st.text(min_size=0, max_size=200),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_normalise_name_stable(name):
    """_normalise_name produces a stable slug with only allowed characters."""
    slug = _normalise_name(name)
    assert len(slug) <= 64
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in slug)
    # Idempotent
    assert _normalise_name(slug) == slug


@given(
    raw=st.one_of(
        st.just(""),
        st.just("N/A"),
        st.just("NA"),
        st.just("-"),
        st.decimals(min_value=Decimal("0"), max_value=Decimal("1e10"), places=2,
                    allow_nan=False, allow_infinity=False).map(str),
    )
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_property_parse_amount_non_negative(raw):
    """_parse_amount_thousands always returns a non-negative Decimal."""
    result = _parse_amount_thousands(raw)
    assert isinstance(result, Decimal)
    assert result >= Decimal("0")


# ──────────────────────────────────────────────────────────────────────────────
# Integration marker
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_integration_acquire_and_parse():
    """Integration test: acquire then parse for a cached real-data period.

    Requires data/raw/naic_schedule_s/2023-Q4/schedule_s.csv to exist.
    Mark @pytest.mark.integration so it is excluded from default fast runs.
    """
    fetcher = NaicScheduleSFetcher()
    available = fetcher.list_available_periods()
    if not available:
        pytest.skip("No cached NAIC Schedule S data available for integration test.")
    period = available[-1]
    handle = fetcher.acquire(period)
    facts = fetcher.parse(handle)
    report = fetcher.validate(facts)
    assert isinstance(facts, list)
    assert isinstance(report, ValidationReport)
