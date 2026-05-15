"""Unit tests for claimweb.fetchers.sec_adv.

Covers:
- _normalise_name: slugification
- _parse_raum: USD integer → millions Decimal
- _parse_crd: CRD normalisation (zero / empty / valid)
- _aam_node_id / _related_node_id: node ID conventions
- _read_firm_csv: reads fixture CSV, returns correct dict
- _read_schedule_r_csv: reads fixture CSV, filters empty rows
- _find_zip_entry: filename pattern matching
- _extract_iapd_zip_url: HTML URL extraction
- SecAdvFetcher.list_available_periods: empty dir, one period
- SecAdvFetcher.parse: fixture-based golden-path test
- SecAdvFetcher.parse: service relationships are excluded
- SecAdvFetcher.parse: missing firm in firm table → skip
- SecAdvFetcher.parse: self-referential arc skipped
- SecAdvFetcher.parse: empty handles return []
- SecAdvFetcher.validate: clean path, missing file warning, wrong arc class
- SecAdvFetcher.validate: no insurer arcs → info message
- SecAdvFetcher.validate: negative RAUM → error
- Property-based (hypothesis): all emitted ArcFacts pass schema validation
"""
from __future__ import annotations

import csv
import hashlib
import io
import tempfile
import zipfile
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
from claimweb.fetchers.sec_adv import (
    _CACHE_LIFETIME_DAYS,
    _FINANCIAL_RELATIONSHIP_TYPES,
    _FIRM_FILENAME,
    _IAPD_PAGE_URL,
    _REL_TYPE_TO_PREFIX,
    _SCHED_R_FILENAME,
    _SERVICE_RELATIONSHIP_TYPES,
    _USD_TO_MILLIONS,
    SecAdvFetcher,
    _aam_node_id,
    _extract_iapd_zip_url,
    _find_zip_entry,
    _normalise_name,
    _parse_crd,
    _parse_iapd_zip,
    _parse_raum,
    _read_firm_csv,
    _read_schedule_r_csv,
    _related_node_id,
)

# ──────────────────────────────────────────────────────────────────────────────
# Paths to fixture files
# ──────────────────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "sec_adv"
FIRM_FIXTURE = FIXTURE_DIR / "ia_firm.csv"
SCHED_R_FIXTURE = FIXTURE_DIR / "ia_schedule_r.csv"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_handle(period: Period, tmp_path: Path) -> RawDataHandle:
    """Build a RawDataHandle from the fixture CSV files."""
    period_dir = tmp_path / str(period)
    period_dir.mkdir(parents=True, exist_ok=True)

    firm_dst = period_dir / _FIRM_FILENAME
    sched_r_dst = period_dir / _SCHED_R_FILENAME
    firm_dst.write_bytes(FIRM_FIXTURE.read_bytes())
    sched_r_dst.write_bytes(SCHED_R_FIXTURE.read_bytes())

    return RawDataHandle.from_paths("sec_adv", period, [firm_dst, sched_r_dst])


# ──────────────────────────────────────────────────────────────────────────────
# _normalise_name
# ──────────────────────────────────────────────────────────────────────────────


class TestNormaliseName:
    def test_basic(self):
        assert _normalise_name("Apollo Global Management LLC") == "apollo_global_management_llc"

    def test_punctuation_stripped(self):
        assert _normalise_name("Athene Holding, Ltd.") == "athene_holding_ltd"

    def test_leading_trailing_underscores_removed(self):
        slug = _normalise_name("  --Foo Bar--  ")
        assert not slug.startswith("_")
        assert not slug.endswith("_")

    def test_max_length_64(self):
        long_name = "A" * 200
        assert len(_normalise_name(long_name)) <= 64

    def test_empty_string(self):
        assert _normalise_name("") == ""

    def test_unicode_replaced_by_underscore(self):
        slug = _normalise_name("Büyük Şirket A.Ş.")
        assert all(c.isalnum() or c == "_" for c in slug)


# ──────────────────────────────────────────────────────────────────────────────
# _parse_raum
# ──────────────────────────────────────────────────────────────────────────────


class TestParseRaum:
    def test_standard_usd_integer(self):
        result = _parse_raum("600000000000")
        expected = Decimal("600000000000") * _USD_TO_MILLIONS
        assert result == expected

    def test_usd_to_millions_conversion(self):
        # 1,000,000 USD = 1 million
        assert _parse_raum("1000000") == Decimal("1")

    def test_empty_string_returns_zero(self):
        assert _parse_raum("") == Decimal("0")

    def test_whitespace_only_returns_zero(self):
        assert _parse_raum("   ") == Decimal("0")

    def test_non_numeric_returns_zero(self):
        assert _parse_raum("N/A") == Decimal("0")

    def test_comma_separated_number(self):
        # e.g. "600,000,000,000"
        result = _parse_raum("600,000,000,000")
        expected = Decimal("600000000000") * _USD_TO_MILLIONS
        assert result == expected

    def test_zero_string(self):
        assert _parse_raum("0") == Decimal("0")

    def test_returns_decimal_type(self):
        result = _parse_raum("500000000")
        assert isinstance(result, Decimal)

    def test_large_value(self):
        # 1 trillion USD = 1,000,000 million
        result = _parse_raum("1000000000000")
        assert result == Decimal("1000000")


# ──────────────────────────────────────────────────────────────────────────────
# _parse_crd
# ──────────────────────────────────────────────────────────────────────────────


class TestParseCrd:
    def test_valid_crd(self):
        assert _parse_crd("148760") == "148760"

    def test_zero_returns_empty(self):
        assert _parse_crd("0") == ""

    def test_empty_returns_empty(self):
        assert _parse_crd("") == ""

    def test_whitespace_stripped(self):
        assert _parse_crd("  148760  ") == "148760"

    def test_whitespace_around_zero(self):
        assert _parse_crd("  0  ") == ""


# ──────────────────────────────────────────────────────────────────────────────
# Node ID helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestNodeIdHelpers:
    def test_aam_node_id_with_crd(self):
        assert _aam_node_id("148760", "Apollo") == "aam:crd:148760"

    def test_aam_node_id_without_crd(self):
        result = _aam_node_id("", "Apollo Global Management")
        assert result == "aam:name:apollo_global_management"

    def test_aam_node_id_zero_crd(self):
        result = _aam_node_id("0", "Apollo")
        assert result.startswith("aam:name:")

    def test_related_insurer_with_crd(self):
        result = _related_node_id("12345", "Athene", "Insurance Company")
        assert result == "insurer:crd:12345"

    def test_related_insurer_without_crd(self):
        result = _related_node_id("0", "Athene Holding Ltd", "Insurance Company")
        assert result == "insurer:name:athene_holding_ltd"

    def test_related_investment_adviser(self):
        result = _related_node_id("99999", "Sub Adviser LLC", "Investment Adviser")
        assert result == "aam:crd:99999"

    def test_related_broker_dealer(self):
        result = _related_node_id("77777", "Capital Markets LLC", "Broker-Dealer")
        assert result == "broker:crd:77777"

    def test_related_bank(self):
        result = _related_node_id("", "First National Bank", "Banking or Thrift Institution")
        assert result == "bank:name:first_national_bank"

    def test_related_pooled_vehicle(self):
        result = _related_node_id("55555", "Fund I LP", "Registered Pooled Investment Vehicle")
        assert result == "fund:crd:55555"

    def test_related_unknown_type(self):
        result = _related_node_id("11111", "Mysterious Entity", "Other Financial Industry Participant")
        assert result == "entity:crd:11111"

    def test_all_rel_types_in_mapping_have_valid_prefix(self):
        valid_prefixes = {"insurer", "aam", "fund", "broker", "bank", "entity", "bdc"}
        for rel_type, prefix in _REL_TYPE_TO_PREFIX.items():
            assert prefix in valid_prefixes, f"Unknown prefix {prefix!r} for {rel_type!r}"


# ──────────────────────────────────────────────────────────────────────────────
# _read_firm_csv
# ──────────────────────────────────────────────────────────────────────────────


class TestReadFirmCsv:
    def test_reads_fixture(self):
        firms = _read_firm_csv(FIRM_FIXTURE)
        assert "148760" in firms
        assert "104016" in firms
        assert "147023" in firms

    def test_firm_fields(self):
        firms = _read_firm_csv(FIRM_FIXTURE)
        apollo = firms["148760"]
        assert apollo["legal_name"] == "Apollo Global Management LLC"
        assert apollo["sec_number"] == "801-74140"
        assert isinstance(apollo["raum_millions"], Decimal)
        assert apollo["raum_millions"] == Decimal("600000")  # 600B / 1M

    def test_zero_raum_parsed_as_zero(self):
        firms = _read_firm_csv(FIRM_FIXTURE)
        assert firms["99001"]["raum_millions"] == Decimal("0")

    def test_missing_file_returns_empty(self, tmp_path):
        result = _read_firm_csv(tmp_path / "nonexistent.csv")
        assert result == {}

    def test_empty_crd_rows_skipped(self, tmp_path):
        content = "CRD_NUMBER,SEC_NUMBER,LEGAL_NM,ASSETS_UNDER_MGMT_AMT\n,801-00000,Empty CRD Co,0\n"
        p = tmp_path / "firm.csv"
        p.write_text(content)
        result = _read_firm_csv(p)
        assert result == {}


# ──────────────────────────────────────────────────────────────────────────────
# _read_schedule_r_csv
# ──────────────────────────────────────────────────────────────────────────────


class TestReadScheduleRCsv:
    def test_reads_fixture(self):
        rows = _read_schedule_r_csv(SCHED_R_FIXTURE)
        assert len(rows) > 0

    def test_row_fields(self):
        rows = _read_schedule_r_csv(SCHED_R_FIXTURE)
        apollo_rows = [r for r in rows if r["firm_crd"] == "148760"]
        assert len(apollo_rows) >= 3

        rel_types = {r["relationship_type"] for r in apollo_rows}
        assert "Insurance Company" in rel_types
        assert "Accounting Firm" in rel_types

    def test_related_name_present(self):
        rows = _read_schedule_r_csv(SCHED_R_FIXTURE)
        names = {r["related_name"] for r in rows}
        assert "Athene Holding Ltd." in names

    def test_missing_file_returns_empty_list(self, tmp_path):
        result = _read_schedule_r_csv(tmp_path / "nonexistent.csv")
        assert result == []

    def test_rows_with_empty_firm_crd_skipped(self, tmp_path):
        content = (
            "CRD_NUMBER,RELATED_PERSON_NM,RELATED_PERSON_CRD_NO,RELATIONSHIP_TYPE\n"
            ",Orphan Firm,0,Insurance Company\n"
            "148760,Valid Related,0,Investment Adviser\n"
        )
        p = tmp_path / "sched_r.csv"
        p.write_text(content)
        rows = _read_schedule_r_csv(p)
        assert len(rows) == 1
        assert rows[0]["firm_crd"] == "148760"

    def test_rows_with_empty_related_name_skipped(self, tmp_path):
        content = (
            "CRD_NUMBER,RELATED_PERSON_NM,RELATED_PERSON_CRD_NO,RELATIONSHIP_TYPE\n"
            "148760,,0,Insurance Company\n"
        )
        p = tmp_path / "sched_r.csv"
        p.write_text(content)
        rows = _read_schedule_r_csv(p)
        assert rows == []


# ──────────────────────────────────────────────────────────────────────────────
# _find_zip_entry
# ──────────────────────────────────────────────────────────────────────────────


class TestFindZipEntry:
    def test_finds_exact_match(self):
        names = ["ia_firm.csv", "ia_schedule_r.csv", "readme.txt"]
        assert _find_zip_entry(names, ("ia_firm",)) == "ia_firm.csv"

    def test_case_insensitive(self):
        names = ["IA_FIRM_SEC.csv", "IA_SCHEDULE_R_SEC.csv"]
        assert _find_zip_entry(names, ("ia_firm",)) == "IA_FIRM_SEC.csv"

    def test_first_match_wins(self):
        names = ["ia_firm_2024.csv", "ia_firm_2023.csv"]
        result = _find_zip_entry(names, ("ia_firm",))
        assert result == "ia_firm_2024.csv"

    def test_no_match_returns_none(self):
        names = ["readme.txt", "data.json"]
        assert _find_zip_entry(names, ("ia_firm",)) is None

    def test_multiple_patterns_any_match(self):
        names = ["IA_SCHEDULE_R_SEC.csv", "firm.csv"]
        result = _find_zip_entry(names, ("ia_schedule_r", "schedule_r"))
        assert result == "IA_SCHEDULE_R_SEC.csv"


# ──────────────────────────────────────────────────────────────────────────────
# _extract_iapd_zip_url
# ──────────────────────────────────────────────────────────────────────────────


class TestExtractIapdZipUrl:
    def test_finds_adv_zip_href(self):
        html = '<a href="/files/investment/form-adv-data.zip">Download</a>'
        result = _extract_iapd_zip_url(html)
        assert result == "https://www.sec.gov/files/investment/form-adv-data.zip"

    def test_finds_ia_firm_zip_href(self):
        html = '<a href="https://example.com/IA_firm_2024.zip">IA Firm Data</a>'
        result = _extract_iapd_zip_url(html)
        assert result is not None
        assert result.endswith(".zip")

    def test_returns_none_when_no_zip(self):
        html = "<html><body>No downloads here</body></html>"
        assert _extract_iapd_zip_url(html) is None

    def test_absolute_url_preserved(self):
        html = '<a href="https://www.sec.gov/data/adv.zip">Download</a>'
        result = _extract_iapd_zip_url(html)
        assert result == "https://www.sec.gov/data/adv.zip"

    def test_relative_url_made_absolute(self):
        html = '<a href="/download/iapd-data.zip">Data</a>'
        result = _extract_iapd_zip_url(html)
        assert result == "https://www.sec.gov/download/iapd-data.zip"


# ──────────────────────────────────────────────────────────────────────────────
# SecAdvFetcher.list_available_periods
# ──────────────────────────────────────────────────────────────────────────────


class TestListAvailablePeriods:
    def test_empty_directory_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "raw" / "sec_adv").mkdir(parents=True)
        fetcher = SecAdvFetcher()
        assert fetcher.list_available_periods() == []

    def test_missing_directory_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fetcher = SecAdvFetcher()
        assert fetcher.list_available_periods() == []

    def test_one_period(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "raw" / "sec_adv" / "2024-Q4").mkdir(parents=True)
        fetcher = SecAdvFetcher()
        result = fetcher.list_available_periods()
        assert result == [Period("2024-Q4")]

    def test_multiple_periods_sorted(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "data" / "raw" / "sec_adv"
        for p in ("2024-Q2", "2023-Q4", "2024-Q1"):
            (base / p).mkdir(parents=True)
        fetcher = SecAdvFetcher()
        result = fetcher.list_available_periods()
        assert result == [Period("2023-Q4"), Period("2024-Q1"), Period("2024-Q2")]

    def test_non_period_dirs_ignored(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "data" / "raw" / "sec_adv"
        (base / "2024-Q3").mkdir(parents=True)
        (base / "cache").mkdir(parents=True)
        (base / "tmp_download").mkdir(parents=True)
        fetcher = SecAdvFetcher()
        result = fetcher.list_available_periods()
        assert result == [Period("2024-Q3")]


# ──────────────────────────────────────────────────────────────────────────────
# SecAdvFetcher.parse — golden path
# ──────────────────────────────────────────────────────────────────────────────


class TestSecAdvFetcherParse:
    def test_golden_path_count(self, tmp_path):
        """Fixture has 11 Schedule R rows; service relations excluded → <11 arcs."""
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        # Accounting Firm and Law Firm entries (2 for Apollo) are excluded.
        assert len(facts) > 0
        assert len(facts) < 11

    def test_service_relationships_excluded(self, tmp_path):
        """Accounting Firm and Law Firm entries must not produce arcs."""
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            # Service providers produce no arcs; their related entities would be
            # things like "Deloitte" which should not appear.
            assert "deloitte" not in arc.target_node_id
            assert "simpson" not in arc.target_node_id

    def test_insurer_arcs_present(self, tmp_path):
        """Athene and Global Atlantic must appear as insurer: targets."""
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        targets = {arc.target_node_id for arc in facts}
        insurer_targets = {t for t in targets if t.startswith("insurer:")}
        assert len(insurer_targets) >= 2

    def test_arc_class_is_a11(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.instrument_class is ArcClass.A11

    def test_source_nodes_are_aam(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.source_node_id.startswith("aam:")

    def test_period_matches_handle(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.period == period

    def test_data_quality_flag_is_proxy(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.data_quality_flag is DataQualityFlag.PROXY

    def test_measurement_basis_is_stock_eop(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.measurement_basis == "stock_eop"

    def test_provenance_source_is_sec_adv(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.provenance_source == "sec_adv"

    def test_provenance_url_is_iapd_page(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.provenance_url == _IAPD_PAGE_URL

    def test_raum_in_millions(self, tmp_path):
        """Apollo's 600B RAUM should appear as 600,000 million on each arc."""
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        apollo_arcs = [arc for arc in facts if "148760" in arc.source_node_id]
        assert len(apollo_arcs) > 0
        for arc in apollo_arcs:
            assert arc.dollar_amount_millions == Decimal("600000")

    def test_dollar_amount_is_decimal(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert isinstance(arc.dollar_amount_millions, Decimal)

    def test_zero_raum_allowed(self, tmp_path):
        """Small Adviser with RAUM=0 can still produce arcs with amount=0."""
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        small_adviser_arcs = [
            arc for arc in facts if "99001" in arc.source_node_id
        ]
        for arc in small_adviser_arcs:
            assert arc.dollar_amount_millions == Decimal("0")

    def test_self_referential_arc_excluded(self, tmp_path):
        """Apollo lists itself as an IA → arc source == target → must be dropped."""
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        for arc in facts:
            assert arc.source_node_id != arc.target_node_id

    def test_sha256_matches_sched_r_file(self, tmp_path):
        period = Period("2024-Q4")
        handle = _make_handle(period, tmp_path)
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        paths = {p.name: p for p in handle.paths}
        expected_sha = handle.sha256_by_path[str(paths[_SCHED_R_FILENAME])]
        for arc in facts:
            assert arc.sha256_of_source == expected_sha

    def test_missing_firm_table_entry_skipped(self, tmp_path):
        """Schedule R row for a CRD not in firm table is silently dropped."""
        period = Period("2024-Q1")
        period_dir = tmp_path / str(period)
        period_dir.mkdir(parents=True)

        # Firm table only has CRD 99999; Schedule R has 99999 + unknown 00001.
        firm_content = (
            "CRD_NUMBER,SEC_NUMBER,LEGAL_NM,ASSETS_UNDER_MGMT_AMT\n"
            "99999,801-00001,Known Firm,1000000000\n"
        )
        sched_r_content = (
            "CRD_NUMBER,RELATED_PERSON_NM,RELATED_PERSON_CRD_NO,RELATIONSHIP_TYPE\n"
            "99999,Affiliate Insurance Co,0,Insurance Company\n"
            "00001,Orphan Affiliate,0,Insurance Company\n"
        )
        firm_path = period_dir / _FIRM_FILENAME
        sched_r_path = period_dir / _SCHED_R_FILENAME
        firm_path.write_text(firm_content)
        sched_r_path.write_text(sched_r_content)

        handle = RawDataHandle.from_paths("sec_adv", period, [firm_path, sched_r_path])
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)

        assert len(facts) == 1
        assert "99999" in facts[0].source_node_id

    def test_empty_handle_returns_empty(self, tmp_path):
        """A handle with no paths returns empty list without crashing."""
        period = Period("2024-Q1")
        handle = RawDataHandle(
            source_id="sec_adv",
            period=period,
            paths=(),
            sha256_by_path={},
        )
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        assert facts == []

    def test_only_firm_file_in_handle(self, tmp_path):
        """Handle missing the Schedule R file returns empty list."""
        period = Period("2024-Q1")
        period_dir = tmp_path / str(period)
        period_dir.mkdir(parents=True)
        firm_path = period_dir / _FIRM_FILENAME
        firm_path.write_bytes(FIRM_FIXTURE.read_bytes())
        handle = RawDataHandle.from_paths("sec_adv", period, [firm_path])
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)
        assert facts == []


# ──────────────────────────────────────────────────────────────────────────────
# SecAdvFetcher.validate
# ──────────────────────────────────────────────────────────────────────────────


class TestSecAdvFetcherValidate:
    def _make_arc(
        self,
        period: Period,
        source: str = "aam:crd:148760",
        target: str = "insurer:name:athene",
        amount: Decimal | None = None,
        arc_class: ArcClass = ArcClass.A11,
    ) -> ArcFact:
        return ArcFact(
            period=period,
            source_node_id=source,
            target_node_id=target,
            instrument_class=arc_class,
            dollar_amount_millions=amount if amount is not None else Decimal("600000"),
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.PROXY,
            provenance_source="sec_adv",
            provenance_url=_IAPD_PAGE_URL,
            provenance_filing="ADV/148760",
            provenance_page=None,
            provenance_field="Schedule_R.relationship_type",
            sha256_of_source="a" * 64,
        )

    def test_clean_facts_passes(self):
        period = Period("2024-Q4")
        arc = self._make_arc(period)
        fetcher = SecAdvFetcher()
        report = fetcher.validate([arc])
        assert report.is_clean

    def test_empty_facts_warns(self):
        fetcher = SecAdvFetcher()
        report = fetcher.validate([])
        codes = {i.code for i in report.issues}
        assert "NO_ARCS" in codes

    def test_wrong_arc_class_errors(self):
        period = Period("2024-Q4")
        arc = self._make_arc(period, arc_class=ArcClass.A3)
        fetcher = SecAdvFetcher()
        report = fetcher.validate([arc])
        assert not report.is_clean
        codes = {i.code for i in report.issues}
        assert "WRONG_ARC_CLASS" in codes

    def test_negative_raum_errors(self):
        period = Period("2024-Q4")
        arc = self._make_arc(period, amount=Decimal("-1"))
        fetcher = SecAdvFetcher()
        report = fetcher.validate([arc])
        assert not report.is_clean
        codes = {i.code for i in report.issues}
        assert "NEGATIVE_RAUM" in codes

    def test_unexpected_source_prefix_warns(self):
        period = Period("2024-Q4")
        arc = self._make_arc(period, source="entity:name:unexpected_source")
        fetcher = SecAdvFetcher()
        report = fetcher.validate([arc])
        codes = {i.code for i in report.issues}
        assert "UNEXPECTED_SOURCE_PREFIX" in codes

    def test_no_insurer_arcs_info(self):
        period = Period("2024-Q4")
        arc = self._make_arc(period, target="aam:name:sub_adviser")
        fetcher = SecAdvFetcher()
        report = fetcher.validate([arc])
        codes = {i.code for i in report.issues}
        assert "NO_INSURER_ARCS" in codes

    def test_report_is_clean_with_all_insurer_arcs(self):
        period = Period("2024-Q4")
        facts = [
            self._make_arc(period, target="insurer:crd:11111"),
            self._make_arc(period, target="insurer:name:athene"),
        ]
        fetcher = SecAdvFetcher()
        report = fetcher.validate(facts)
        assert report.is_clean

    def test_multiple_errors_all_reported(self):
        period = Period("2024-Q4")
        bad1 = self._make_arc(period, arc_class=ArcClass.A3)
        bad2 = self._make_arc(period, amount=Decimal("-5"))
        fetcher = SecAdvFetcher()
        report = fetcher.validate([bad1, bad2])
        assert not report.is_clean
        assert len([i for i in report.issues if i.severity == "error"]) >= 2


# ──────────────────────────────────────────────────────────────────────────────
# _parse_iapd_zip
# ──────────────────────────────────────────────────────────────────────────────


class TestParseIapdZip:
    def _make_zip(
        self,
        firm_content: str,
        sched_r_content: str,
        firm_name: str = "ia_firm.csv",
        sched_r_name: str = "ia_schedule_r.csv",
    ) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(firm_name, firm_content.encode())
            zf.writestr(sched_r_name, sched_r_content.encode())
        return buf.getvalue()

    def test_parses_firm_and_sched_r(self):
        firm = "CRD_NUMBER,SEC_NUMBER,LEGAL_NM,ASSETS_UNDER_MGMT_AMT\n148760,801-74140,Apollo,500000000000\n"
        sched_r = "CRD_NUMBER,RELATED_PERSON_NM,RELATED_PERSON_CRD_NO,RELATIONSHIP_TYPE\n148760,Athene,0,Insurance Company\n"
        zip_bytes = self._make_zip(firm, sched_r)
        firm_rows, sched_r_rows = _parse_iapd_zip(zip_bytes)
        assert len(firm_rows) == 1
        assert firm_rows[0]["crd"] == "148760"
        assert len(sched_r_rows) == 1
        assert sched_r_rows[0]["firm_crd"] == "148760"

    def test_uppercase_filenames(self):
        firm = "CRD_NUMBER,SEC_NUMBER,LEGAL_NM,ASSETS_UNDER_MGMT_AMT\n12345,801-00001,Firm,100000000\n"
        sched_r = "CRD_NUMBER,RELATED_PERSON_NM,RELATED_PERSON_CRD_NO,RELATIONSHIP_TYPE\n12345,Affiliate,0,Investment Adviser\n"
        zip_bytes = self._make_zip(firm, sched_r, "IA_FIRM_SEC.csv", "IA_SCHEDULE_R_SEC.csv")
        firm_rows, sched_r_rows = _parse_iapd_zip(zip_bytes)
        assert len(firm_rows) == 1
        assert len(sched_r_rows) == 1

    def test_missing_firm_file_returns_empty_firm_rows(self):
        sched_r = "CRD_NUMBER,RELATED_PERSON_NM,RELATED_PERSON_CRD_NO,RELATIONSHIP_TYPE\n12345,Aff,0,Other\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("ia_schedule_r.csv", sched_r.encode())
        firm_rows, _ = _parse_iapd_zip(buf.getvalue())
        assert firm_rows == []

    def test_skips_empty_crd_rows(self):
        firm = "CRD_NUMBER,SEC_NUMBER,LEGAL_NM,ASSETS_UNDER_MGMT_AMT\n,801-00000,No CRD,0\n"
        sched_r = "CRD_NUMBER,RELATED_PERSON_NM,RELATED_PERSON_CRD_NO,RELATIONSHIP_TYPE\n"
        zip_bytes = self._make_zip(firm, sched_r)
        firm_rows, sched_r_rows = _parse_iapd_zip(zip_bytes)
        assert firm_rows == []


# ──────────────────────────────────────────────────────────────────────────────
# Constants / invariants
# ──────────────────────────────────────────────────────────────────────────────


class TestConstants:
    def test_financial_and_service_types_disjoint(self):
        overlap = _FINANCIAL_RELATIONSHIP_TYPES & _SERVICE_RELATIONSHIP_TYPES
        assert overlap == frozenset(), f"Overlap: {overlap}"

    def test_usd_to_millions_conversion(self):
        assert Decimal("1000000") * _USD_TO_MILLIONS == Decimal("1")

    def test_cache_lifetime_positive(self):
        assert _CACHE_LIFETIME_DAYS > 0

    def test_iapd_page_url_is_sec(self):
        assert "sec.gov" in _IAPD_PAGE_URL

    def test_source_id(self):
        assert SecAdvFetcher.source_id == "sec_adv"

    def test_cadence(self):
        assert SecAdvFetcher.cadence == "quarterly"


# ──────────────────────────────────────────────────────────────────────────────
# Property-based tests
# ──────────────────────────────────────────────────────────────────────────────

_RELATIONSHIP_TYPES_LIST = list(_FINANCIAL_RELATIONSHIP_TYPES)


@given(
    raum_usd=st.integers(min_value=0, max_value=10_000_000_000_000),
    rel_type=st.sampled_from(_RELATIONSHIP_TYPES_LIST),
    related_crd=st.one_of(st.just(""), st.integers(min_value=1, max_value=999999).map(str)),
)
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_property_emitted_facts_pass_schema(raum_usd, rel_type, related_crd):
    """Any financial relationship type must produce a schema-valid ArcFact."""
    period = Period("2024-Q4")
    with tempfile.TemporaryDirectory() as td:
        period_dir = Path(td) / "2024-Q4"
        period_dir.mkdir(parents=True, exist_ok=True)

        firm_path = period_dir / _FIRM_FILENAME
        sched_r_path = period_dir / _SCHED_R_FILENAME

        firm_content = (
            "CRD_NUMBER,SEC_NUMBER,LEGAL_NM,ASSETS_UNDER_MGMT_AMT\n"
            f"999,801-99999,Test Adviser,{raum_usd}\n"
        )
        sched_r_content = (
            "CRD_NUMBER,RELATED_PERSON_NM,RELATED_PERSON_CRD_NO,RELATIONSHIP_TYPE\n"
            f"999,Related Entity Inc,{related_crd},{rel_type}\n"
        )
        firm_path.write_text(firm_content)
        sched_r_path.write_text(sched_r_content)

        handle = RawDataHandle.from_paths("sec_adv", period, [firm_path, sched_r_path])
        fetcher = SecAdvFetcher()
        facts = fetcher.parse(handle)

        for arc in facts:
            # Validates schema via __post_init__ — any exception = test failure.
            assert isinstance(arc, ArcFact)
            assert arc.instrument_class is ArcClass.A11
            assert isinstance(arc.dollar_amount_millions, Decimal)
            assert arc.dollar_amount_millions >= Decimal("0")
            assert arc.measurement_basis == "stock_eop"


@given(
    name=st.text(min_size=0, max_size=200),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_property_normalise_name_stable(name):
    """_normalise_name must be idempotent and produce only [a-z0-9_] chars."""
    slug = _normalise_name(name)
    assert len(slug) <= 64
    assert all(c.isalnum() or c == "_" for c in slug), f"Non-slug char in {slug!r}"
    # Idempotent: re-slugging a slug produces the same slug.
    assert _normalise_name(slug) == slug


@given(
    amount=st.integers(min_value=0, max_value=10**15),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_property_parse_raum_non_negative(amount):
    """_parse_raum must always return non-negative Decimal."""
    result = _parse_raum(str(amount))
    assert isinstance(result, Decimal)
    assert result >= Decimal("0")
