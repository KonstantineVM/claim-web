"""Unit tests for claimweb.fetchers.sec_xbrl.

Covers:
- _end_date_to_period: SEC end-date string → Period conversion
- _period_to_end_date: Period → quarter-end date
- _extract_best_fact: XBRL entry selection logic
- SecXbrlFetcher.parse: fixture-based parse → ArcFact list
- SecXbrlFetcher.validate: clean path, empty facts, negative amounts, implausible
- SecXbrlFetcher.list_available_periods: with manifest setup
- LIFE_INSURERS panel: integrity checks
- _TAG_MAP: integrity checks
- Property-based: all emitted ArcFacts satisfy the schema
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
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
from claimweb.fetchers.sec_xbrl import (
    LIFE_INSURERS,
    _ASSETS_TAG,
    _CIK_TO_ENTITY,
    _MIN_TOTAL_ASSETS_MM,
    _TAG_MAP,
    _USD_TO_MM,
    SecXbrlFetcher,
    _end_date_to_period,
    _extract_best_fact,
    _period_to_end_date,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "sec_xbrl"
MET_CIK = "0001099219"
MET_FIXTURE = FIXTURE_DIR / f"CIK{MET_CIK}.json"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_handle(
    paths: list[Path], period: Period
) -> RawDataHandle:
    """Build a RawDataHandle from a list of JSON fixture paths."""
    return RawDataHandle.from_paths("sec_xbrl", period, paths)


def _met_handle(period: Period, tmp_path: Path) -> RawDataHandle:
    """Build a handle pointing to the MetLife fixture for the given period."""
    dest = tmp_path / f"CIK{MET_CIK}.json"
    dest.write_bytes(MET_FIXTURE.read_bytes())
    return _make_handle([dest], period)


def _setup_bundle(tmp_path: Path, ciks: list[str], fixture_path: Path) -> Path:
    """Copy fixture file as each CIK's JSON; write a fresh manifest."""
    bundle_dir = tmp_path / "raw" / "sec_xbrl" / "bundle"
    bundle_dir.mkdir(parents=True)
    for cik in ciks:
        (bundle_dir / f"CIK{cik}.json").write_bytes(fixture_path.read_bytes())
    manifest = {
        "fetched_at": "2099-01-01T00:00:00",
        "ciks": ciks,
    }
    (bundle_dir / "_manifest.json").write_text(json.dumps(manifest))
    return bundle_dir


# ──────────────────────────────────────────────────────────────────────────────
# _end_date_to_period
# ──────────────────────────────────────────────────────────────────────────────


class TestEndDateToPeriod:
    @pytest.mark.parametrize(
        "end_date, expected",
        [
            ("2024-03-31", "2024-Q1"),
            ("2024-06-30", "2024-Q2"),
            ("2024-09-30", "2024-Q3"),
            ("2024-12-31", "2024-Q4"),
            ("2000-03-31", "2000-Q1"),
            ("2023-12-31", "2023-Q4"),
        ],
    )
    def test_valid_quarter_ends(self, end_date: str, expected: str) -> None:
        result = _end_date_to_period(end_date)
        assert result == Period(expected)

    @pytest.mark.parametrize(
        "end_date",
        [
            "2024-01-31",   # January (not a quarter-end month)
            "2024-04-30",   # April (not a quarter-end month)
            "2024-02-29",   # February
            "2024-03-30",   # Wrong day
            "2024-06-29",   # Wrong day
            "not-a-date",
            "",
        ],
    )
    def test_non_quarter_end_returns_none(self, end_date: str) -> None:
        assert _end_date_to_period(end_date) is None

    def test_returns_period_object(self) -> None:
        result = _end_date_to_period("2024-12-31")
        assert isinstance(result, Period)

    def test_year_and_quarter_correct(self) -> None:
        p = _end_date_to_period("2023-09-30")
        assert p is not None
        assert p.year == 2023
        assert p.quarter == 3


# ──────────────────────────────────────────────────────────────────────────────
# _period_to_end_date
# ──────────────────────────────────────────────────────────────────────────────


class TestPeriodToEndDate:
    @pytest.mark.parametrize(
        "period_str, expected_date",
        [
            ("2024-Q1", date(2024, 3, 31)),
            ("2024-Q2", date(2024, 6, 30)),
            ("2024-Q3", date(2024, 9, 30)),
            ("2024-Q4", date(2024, 12, 31)),
            ("2000-Q1", date(2000, 3, 31)),
        ],
    )
    def test_quarter_end_dates(self, period_str: str, expected_date: date) -> None:
        assert _period_to_end_date(Period(period_str)) == expected_date

    def test_roundtrip(self) -> None:
        """end_date_to_period(_period_to_end_date(p)) == p."""
        for p_str in ["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"]:
            p = Period(p_str)
            end_date = _period_to_end_date(p)
            roundtrip = _end_date_to_period(end_date.isoformat())
            assert roundtrip == p


# ──────────────────────────────────────────────────────────────────────────────
# _extract_best_fact
# ──────────────────────────────────────────────────────────────────────────────


class TestExtractBestFact:
    def _entry(
        self,
        end: str,
        val: int,
        form: str = "10-K",
        filed: str = "2025-02-14",
        frame: str | None = "CY2024I",
        accn: str = "0001099219-25-000001",
    ) -> dict:
        e: dict = {
            "end": end, "val": val, "form": form,
            "filed": filed, "accn": accn,
        }
        if frame is not None:
            e["frame"] = frame
        return e

    def test_returns_none_if_no_match(self) -> None:
        entries = [self._entry("2024-09-30", 100_000_000)]
        assert _extract_best_fact(entries, Period("2024-Q4")) is None

    def test_returns_amount_in_millions(self) -> None:
        entries = [self._entry("2024-12-31", 1_000_000_000)]
        result = _extract_best_fact(entries, Period("2024-Q4"))
        assert result is not None
        amount_mm, _, _ = result
        assert amount_mm == Decimal("1000")

    def test_usd_to_mm_conversion(self) -> None:
        raw_usd = 734_000_000_000
        entries = [self._entry("2024-12-31", raw_usd)]
        result = _extract_best_fact(entries, Period("2024-Q4"))
        assert result is not None
        amount_mm, _, _ = result
        assert amount_mm == Decimal(str(raw_usd)) * _USD_TO_MM

    def test_prefers_primary_form_over_amendment(self) -> None:
        entries = [
            self._entry("2024-12-31", 734_000_000_000, form="10-K",
                        filed="2025-02-14", accn="primary"),
            self._entry("2024-12-31", 734_100_000_000, form="10-K/A",
                        filed="2025-03-01", frame=None, accn="amendment"),
        ]
        result = _extract_best_fact(entries, Period("2024-Q4"))
        assert result is not None
        _, accn, _ = result
        assert accn == "primary"

    def test_prefers_framed_over_unframed_within_primary(self) -> None:
        entries = [
            self._entry("2024-12-31", 180_000_000_000, frame="CY2024I",
                        accn="total"),
            self._entry("2024-12-31", 45_000_000_000, frame=None,
                        accn="segment"),
        ]
        result = _extract_best_fact(entries, Period("2024-Q4"))
        assert result is not None
        _, accn, _ = result
        assert accn == "total"

    def test_prefers_latest_filed_among_ties(self) -> None:
        entries = [
            self._entry("2024-12-31", 100_000_000, filed="2025-02-10",
                        accn="earlier"),
            self._entry("2024-12-31", 200_000_000, filed="2025-02-20",
                        accn="later"),
        ]
        result = _extract_best_fact(entries, Period("2024-Q4"))
        assert result is not None
        _, accn, _ = result
        assert accn == "later"

    def test_returns_accn_and_form(self) -> None:
        entries = [
            self._entry("2024-12-31", 1_000_000_000, form="10-K",
                        accn="0001099219-25-000012")
        ]
        result = _extract_best_fact(entries, Period("2024-Q4"))
        assert result is not None
        _, accn, form = result
        assert accn == "0001099219-25-000012"
        assert form == "10-K"

    def test_falls_back_to_amendment_if_no_primary(self) -> None:
        entries = [self._entry("2024-12-31", 5_000_000_000, form="10-K/A")]
        result = _extract_best_fact(entries, Period("2024-Q4"))
        assert result is not None

    def test_returns_decimal(self) -> None:
        entries = [self._entry("2024-12-31", 1_000_000_000)]
        result = _extract_best_fact(entries, Period("2024-Q4"))
        assert result is not None
        amount_mm, _, _ = result
        assert isinstance(amount_mm, Decimal)

    def test_empty_entries(self) -> None:
        assert _extract_best_fact([], Period("2024-Q4")) is None


# ──────────────────────────────────────────────────────────────────────────────
# SecXbrlFetcher.parse — fixture-based
# ──────────────────────────────────────────────────────────────────────────────


class TestSecXbrlParse:
    def test_parse_emits_facts_for_q4(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert len(facts) > 0

    def test_parse_emits_assets_fact(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assets = [f for f in facts if f.provenance_field == "Assets"]
        assert len(assets) == 1
        assert assets[0].dollar_amount_millions == Decimal("734000")

    def test_parse_emits_fhlb_arc(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        fhlb = [f for f in facts if f.provenance_field == "AdvancesFromFederalHomeLoanBanks"]
        assert len(fhlb) == 1
        assert fhlb[0].instrument_class == ArcClass.A3
        assert fhlb[0].source_node_id == "insurer:MET"
        assert fhlb[0].target_node_id == "sector:fhlb"
        assert fhlb[0].dollar_amount_millions == Decimal("10000")

    def test_parse_emits_repo_arc(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        repo = [
            f for f in facts
            if f.provenance_field == "SecuritiesSoldUnderAgreementsToRepurchase"
        ]
        assert len(repo) == 1
        assert repo[0].instrument_class == ArcClass.A4
        assert repo[0].source_node_id == "insurer:MET"
        assert repo[0].dollar_amount_millions == Decimal("3200")

    def test_parse_emits_policyholder_balance(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        pab = [f for f in facts if f.provenance_field == "PolicyholderAccountBalance"]
        assert len(pab) == 1
        assert pab[0].instrument_class == ArcClass.A1
        # Prefers framed entry (180 B) over unframed segment entry (45 B)
        assert pab[0].dollar_amount_millions == Decimal("180000")

    def test_parse_emits_sec_lending_arc(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        sec_lend = [
            f for f in facts
            if f.provenance_field
            == "PayablesForCollateralUnderSecuritiesLoanedAndOtherTransactions"
        ]
        assert len(sec_lend) == 1
        assert sec_lend[0].instrument_class == ArcClass.A5
        assert sec_lend[0].dollar_amount_millions == Decimal("8500")

    def test_parse_q3_finds_correct_facts(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q3"), tmp_path)
        facts = fetcher.parse(handle)
        # Assets and FHLB have Q3 entries; repos and policyholder do not
        asset_facts = [f for f in facts if f.provenance_field == "Assets"]
        assert len(asset_facts) == 1
        assert asset_facts[0].dollar_amount_millions == Decimal("726853")

    def test_parse_empty_for_unknown_period(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2010-Q1"), tmp_path)
        facts = fetcher.parse(handle)
        assert facts == []

    def test_parse_sets_data_quality_flag(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED

    def test_parse_sets_measurement_basis(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.measurement_basis == "stock_eop"

    def test_parse_sets_provenance_source(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.provenance_source == "sec_xbrl"

    def test_parse_sets_provenance_url(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        for f in facts:
            assert "data.sec.gov" in f.provenance_url
            assert MET_CIK in f.provenance_url

    def test_parse_sets_provenance_filing(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.provenance_filing is not None
            assert "insurer:MET" in f.provenance_filing

    def test_parse_sha256_is_64_chars(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        for f in facts:
            assert len(f.sha256_of_source) == 64

    def test_parse_period_matches_handle(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        target = Period("2024-Q4")
        handle = _met_handle(target, tmp_path)
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.period == target

    def test_parse_assets_direction_is_aggregate_to_entity(
        self, tmp_path: Path
    ) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assets = [f for f in facts if f.provenance_field == "Assets"]
        assert assets[0].source_node_id == "z1:aggregate"
        assert assets[0].target_node_id == "insurer:MET"

    def test_parse_liabilities_direction_is_entity_to_aggregate(
        self, tmp_path: Path
    ) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        liabilities = [f for f in facts if f.provenance_field == "Liabilities"]
        assert liabilities[0].source_node_id == "insurer:MET"
        assert liabilities[0].target_node_id == "z1:aggregate"

    def test_parse_skips_unknown_cik(self, tmp_path: Path) -> None:
        unknown_payload = {
            "cik": "9999999999",
            "entityName": "Unknown Corp",
            "facts": {"us-gaap": {}},
        }
        dest = tmp_path / "CIK9999999999.json"
        dest.write_text(json.dumps(unknown_payload))
        handle = _make_handle([dest], Period("2024-Q4"))
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        facts = fetcher.parse(handle)
        assert facts == []

    def test_parse_handles_integer_cik_in_json(self, tmp_path: Path) -> None:
        payload = json.loads(MET_FIXTURE.read_text())
        payload["cik"] = 1099219   # integer, not string
        dest = tmp_path / f"CIK{MET_CIK}.json"
        dest.write_text(json.dumps(payload))
        handle = _make_handle([dest], Period("2024-Q4"))
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        facts = fetcher.parse(handle)
        assert len(facts) > 0


# ──────────────────────────────────────────────────────────────────────────────
# SecXbrlFetcher.validate
# ──────────────────────────────────────────────────────────────────────────────


class TestSecXbrlValidate:
    def _make_asset_fact(
        self, amount_mm: Decimal = Decimal("100000")
    ) -> ArcFact:
        return ArcFact(
            period=Period("2024-Q4"),
            source_node_id="z1:aggregate",
            target_node_id="insurer:MET",
            instrument_class=ArcClass.A12,
            dollar_amount_millions=amount_mm,
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
            provenance_source="sec_xbrl",
            provenance_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0001099219.json",
            provenance_filing="insurer:MET_2024-Q4_0001099219-25-000012",
            provenance_page=None,
            provenance_field="Assets",
            sha256_of_source="a" * 64,
        )

    def test_validate_clean_facts(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path)
        handle = _met_handle(Period("2024-Q4"), tmp_path)
        facts = SecXbrlFetcher(data_root=tmp_path).parse(handle)
        report = fetcher.validate(facts)
        assert report.is_clean

    def test_validate_empty_facts_is_error(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path)
        report = fetcher.validate([])
        assert not report.is_clean
        codes = [i.code for i in report.issues]
        assert "NO_FACTS" in codes

    def test_validate_negative_amount_is_warning(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path)
        bad = self._make_asset_fact(Decimal("-1"))
        report = fetcher.validate([bad])
        warnings = [i for i in report.issues if i.severity == "warning"]
        assert any(i.code == "NEGATIVE_AMOUNT" for i in warnings)

    def test_validate_implausible_assets_is_error(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path)
        tiny = self._make_asset_fact(Decimal("1"))  # $1 million — implausible
        report = fetcher.validate([tiny])
        assert not report.is_clean
        codes = [i.code for i in report.issues]
        assert "ASSETS_IMPLAUSIBLE" in codes

    def test_validate_plausible_assets_is_clean(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path)
        plausible = self._make_asset_fact(Decimal("500000"))
        report = fetcher.validate([plausible])
        assert report.is_clean

    def test_validate_source_id(self, tmp_path: Path) -> None:
        fetcher = SecXbrlFetcher(data_root=tmp_path)
        report = fetcher.validate([self._make_asset_fact()])
        assert report.source_id == "sec_xbrl"


# ──────────────────────────────────────────────────────────────────────────────
# SecXbrlFetcher.list_available_periods
# ──────────────────────────────────────────────────────────────────────────────


class TestSecXbrlListAvailablePeriods:
    def test_returns_sorted_periods(self, tmp_path: Path) -> None:
        _setup_bundle(tmp_path, list(LIFE_INSURERS.values()), MET_FIXTURE)
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        periods = fetcher.list_available_periods()
        assert len(periods) >= 1
        assert periods == sorted(periods)

    def test_returns_period_objects(self, tmp_path: Path) -> None:
        _setup_bundle(tmp_path, list(LIFE_INSURERS.values()), MET_FIXTURE)
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        periods = fetcher.list_available_periods()
        assert all(isinstance(p, Period) for p in periods)

    def test_includes_q4_2024(self, tmp_path: Path) -> None:
        _setup_bundle(tmp_path, list(LIFE_INSURERS.values()), MET_FIXTURE)
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        periods = fetcher.list_available_periods()
        assert Period("2024-Q4") in periods

    def test_includes_q3_2024(self, tmp_path: Path) -> None:
        _setup_bundle(tmp_path, list(LIFE_INSURERS.values()), MET_FIXTURE)
        fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
        periods = fetcher.list_available_periods()
        assert Period("2024-Q3") in periods


# ──────────────────────────────────────────────────────────────────────────────
# SecXbrlFetcher attributes
# ──────────────────────────────────────────────────────────────────────────────


class TestSecXbrlFetcherAttributes:
    def test_source_id(self) -> None:
        assert SecXbrlFetcher().source_id == "sec_xbrl"

    def test_cadence(self) -> None:
        assert SecXbrlFetcher().cadence == "quarterly"


# ──────────────────────────────────────────────────────────────────────────────
# LIFE_INSURERS panel integrity
# ──────────────────────────────────────────────────────────────────────────────


class TestLifeInsurersPanel:
    def test_nonempty(self) -> None:
        assert len(LIFE_INSURERS) > 0

    def test_ciks_are_10_digit_strings(self) -> None:
        for entity_id, cik in LIFE_INSURERS.items():
            assert len(cik) == 10, f"{entity_id}: CIK {cik!r} is not 10 digits"
            assert cik.isdigit(), f"{entity_id}: CIK {cik!r} contains non-digits"

    def test_entity_ids_start_with_insurer_prefix(self) -> None:
        for entity_id in LIFE_INSURERS:
            assert entity_id.startswith("insurer:"), (
                f"{entity_id!r} does not start with 'insurer:'"
            )

    def test_ciks_unique(self) -> None:
        ciks = list(LIFE_INSURERS.values())
        assert len(ciks) == len(set(ciks)), "Duplicate CIKs in LIFE_INSURERS"

    def test_entity_ids_unique(self) -> None:
        ids = list(LIFE_INSURERS.keys())
        assert len(ids) == len(set(ids)), "Duplicate entity IDs in LIFE_INSURERS"

    def test_reverse_map_consistency(self) -> None:
        for entity_id, cik in LIFE_INSURERS.items():
            assert _CIK_TO_ENTITY[cik] == entity_id

    def test_met_cik_present(self) -> None:
        assert "insurer:MET" in LIFE_INSURERS
        assert LIFE_INSURERS["insurer:MET"] == MET_CIK

    def test_at_least_ten_entities(self) -> None:
        assert len(LIFE_INSURERS) >= 10


# ──────────────────────────────────────────────────────────────────────────────
# _TAG_MAP integrity
# ──────────────────────────────────────────────────────────────────────────────


class TestTagMapIntegrity:
    def test_nonempty(self) -> None:
        assert len(_TAG_MAP) > 0

    def test_all_values_are_three_tuples(self) -> None:
        for tag, mapping in _TAG_MAP.items():
            assert len(mapping) == 3, f"Tag {tag!r} mapping is not a 3-tuple"

    def test_arc_classes_are_valid(self) -> None:
        for tag, (arc_class, _, _) in _TAG_MAP.items():
            assert isinstance(arc_class, ArcClass), (
                f"Tag {tag!r}: arc_class is not an ArcClass"
            )

    def test_assets_tag_in_map(self) -> None:
        assert _ASSETS_TAG in _TAG_MAP

    def test_fhlb_tag_maps_to_a3(self) -> None:
        assert "AdvancesFromFederalHomeLoanBanks" in _TAG_MAP
        arc_class, _, tgt = _TAG_MAP["AdvancesFromFederalHomeLoanBanks"]
        assert arc_class == ArcClass.A3
        assert "fhlb" in tgt

    def test_repo_tag_maps_to_a4(self) -> None:
        assert "SecuritiesSoldUnderAgreementsToRepurchase" in _TAG_MAP
        arc_class, _, _ = _TAG_MAP["SecuritiesSoldUnderAgreementsToRepurchase"]
        assert arc_class == ArcClass.A4

    def test_sec_lending_tag_maps_to_a5(self) -> None:
        tag = "PayablesForCollateralUnderSecuritiesLoanedAndOtherTransactions"
        assert tag in _TAG_MAP
        arc_class, _, _ = _TAG_MAP[tag]
        assert arc_class == ArcClass.A5

    def test_entity_id_placeholder_in_templates(self) -> None:
        for tag, (_, src, tgt) in _TAG_MAP.items():
            assert "{entity_id}" in src or "{entity_id}" in tgt, (
                f"Tag {tag!r}: neither template contains {{entity_id}}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# Property-based tests
# ──────────────────────────────────────────────────────────────────────────────


@given(
    period_str=st.sampled_from(["2024-Q3", "2024-Q4"]),
)
@settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_parse_emits_valid_arc_facts(
    period_str: str, tmp_path: Path
) -> None:
    """All ArcFacts emitted by SecXbrlFetcher.parse() satisfy the ArcFact schema."""
    fetcher = SecXbrlFetcher(data_root=tmp_path / "raw" / "sec_xbrl")
    period = Period(period_str)
    handle = _met_handle(period, tmp_path)
    facts = fetcher.parse(handle)

    for f in facts:
        assert isinstance(f.dollar_amount_millions, Decimal)
        assert f.dollar_amount_millions >= Decimal("0")
        assert f.measurement_basis == "stock_eop"
        assert f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED
        assert f.provenance_source == "sec_xbrl"
        assert f.source_node_id
        assert f.target_node_id
        assert f.provenance_url
        assert f.provenance_field
        assert len(f.sha256_of_source) == 64


@given(
    raw_usd=st.integers(min_value=0, max_value=10**15),
)
@settings(max_examples=50)
def test_property_usd_to_mm_conversion_exact(raw_usd: int) -> None:
    """USD → millions conversion uses Decimal arithmetic exactly."""
    amount_mm = Decimal(str(raw_usd)) * _USD_TO_MM
    assert isinstance(amount_mm, Decimal)
    expected = Decimal(str(raw_usd)) / Decimal("1000000")
    assert amount_mm == expected


@given(
    period_str=st.sampled_from(
        ["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4", "2000-Q1", "2030-Q4"]
    ),
)
@settings(max_examples=20)
def test_property_period_end_date_roundtrip(period_str: str) -> None:
    """Period → end_date → Period roundtrip is identity."""
    p = Period(period_str)
    end_date = _period_to_end_date(p)
    roundtrip = _end_date_to_period(end_date.isoformat())
    assert roundtrip == p
