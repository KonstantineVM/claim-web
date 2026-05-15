"""Unit tests for claimweb.fetchers.fhlb_combined.

Covers:
- _label_to_period: human-readable quarter labels → Period
- _canonicalize_member_name: known and unknown names
- _slug: safe slug generation
- FhlbCombinedFetcher.parse: full parse on the 2024-Q4 fixture PDF
- FhlbCombinedFetcher.validate: clean path and error/warning conditions
- Property-based: all emitted ArcFacts satisfy the ArcFact schema
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from claimweb.fetchers.base import (
    ArcClass,
    ArcFact,
    DataQualityFlag,
    Period,
    RawDataHandle,
    ValidationReport,
)
from claimweb.fetchers.fhlb_combined import (
    _FHLB_SYSTEM_NODE,
    _INSURER_AGGREGATE_NODE,
    _canonicalize_member_name,
    _label_to_period,
    _slug,
    FhlbCombinedFetcher,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "fhlb_combined"
FIXTURE_PDF = FIXTURE_DIR / "2024-Q4-combined-financial-report.pdf"


@pytest.fixture()
def fetcher(tmp_path: Path) -> FhlbCombinedFetcher:
    return FhlbCombinedFetcher(data_root=tmp_path / "raw" / "fhlb_combined")


@pytest.fixture()
def fixture_handle() -> RawDataHandle:
    """A RawDataHandle pointing at the 2024-Q4 fixture PDF."""
    assert FIXTURE_PDF.exists(), (
        f"Fixture PDF not found: {FIXTURE_PDF}\n"
        "Run: python tests/fixtures/fhlb_combined/generate_fixture.py"
    )
    return RawDataHandle.from_paths("fhlb_combined", Period("2024-Q4"), [FIXTURE_PDF])


# ---------------------------------------------------------------------------
# _label_to_period
# ---------------------------------------------------------------------------


class TestLabelToPeriod:
    @pytest.mark.parametrize(
        "label, expected",
        [
            ("For the Quarter Ended December 31, 2024", "2024-Q4"),
            ("For the Quarter Ended September 30, 2023", "2023-Q3"),
            ("For the Quarter Ended June 30, 2022", "2022-Q2"),
            ("For the Quarter Ended March 31, 2021", "2021-Q1"),
            ("Fourth Quarter 2024", "2024-Q4"),
            ("Third Quarter 2024", "2024-Q3"),
            ("Second Quarter 2023", "2023-Q2"),
            ("First Quarter 2023", "2023-Q1"),
            ("Q4 2024", "2024-Q4"),
            ("Q1 2020", "2020-Q1"),
            ("2024-Q4", "2024-Q4"),
            ("2020 Q1", "2020-Q1"),
        ],
    )
    def test_parses_known_formats(self, label: str, expected: str) -> None:
        result = _label_to_period(label)
        assert result == Period(expected), f"{label!r} → {result} ≠ {expected}"

    def test_returns_none_for_unrecognized(self) -> None:
        assert _label_to_period("Annual Report 2024") is None
        assert _label_to_period("") is None
        assert _label_to_period("not a quarter label") is None


# ---------------------------------------------------------------------------
# _canonicalize_member_name
# ---------------------------------------------------------------------------


class TestCanonicalizeMemberName:
    def test_known_metlife(self) -> None:
        node_id = _canonicalize_member_name(
            "MetLife Insurance Company of Connecticut"
        )
        assert node_id == "insurer:MET_CTIC"

    def test_known_lincoln_national(self) -> None:
        node_id = _canonicalize_member_name(
            "Lincoln National Life Insurance Company"
        )
        assert node_id == "insurer:LNC"

    def test_known_athene(self) -> None:
        node_id = _canonicalize_member_name(
            "Athene Annuity and Life Insurance Company"
        )
        assert node_id == "insurer:ATH_ALIC"

    def test_case_insensitive_match(self) -> None:
        node_id = _canonicalize_member_name(
            "metlife insurance company of connecticut"
        )
        assert node_id == "insurer:MET_CTIC"

    def test_unknown_returns_none(self) -> None:
        assert _canonicalize_member_name("Nonexistent Insurance Co") is None
        assert _canonicalize_member_name("") is None


# ---------------------------------------------------------------------------
# _slug
# ---------------------------------------------------------------------------


class TestSlug:
    def test_basic(self) -> None:
        s = _slug("MetLife Insurance Company of Connecticut")
        assert s == "metlife_insurance_company_of_connecticut"

    def test_truncates_at_60(self) -> None:
        long_name = "A" * 100
        assert len(_slug(long_name)) <= 60

    def test_strips_special_chars(self) -> None:
        s = _slug("ABC & DEF, Inc.")
        assert "&" not in s
        assert "," not in s
        assert "." not in s

    def test_handles_unicode(self) -> None:
        s = _slug("Société Générale")
        assert isinstance(s, str)
        assert len(s) > 0


# ---------------------------------------------------------------------------
# FhlbCombinedFetcher.parse — fixture-based
# ---------------------------------------------------------------------------


class TestFhlbCombinedFetcherParse:
    def test_parse_returns_facts(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        assert len(facts) > 0, "parse() must emit at least one ArcFact"

    def test_parse_emits_aggregate_arc(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        agg = [f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE]
        assert len(agg) == 1, "Exactly one aggregate insurance-member arc expected"

    def test_aggregate_arc_amount_in_millions(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        agg = next(f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE)
        # Fixture has 89.7 billion = 89,700 million
        assert agg.dollar_amount_millions == Decimal("89700.0"), (
            f"Expected 89700.0 (89.7B converted to M), got {agg.dollar_amount_millions}"
        )

    def test_aggregate_arc_target_is_fhlb_system(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        agg = next(f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE)
        assert agg.target_node_id == _FHLB_SYSTEM_NODE

    def test_aggregate_arc_instrument_class_a3(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        agg = next(f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE)
        assert agg.instrument_class is ArcClass.A3

    def test_aggregate_arc_direct_measured(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        agg = next(f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE)
        assert agg.data_quality_flag is DataQualityFlag.DIRECT_MEASURED

    def test_aggregate_arc_stock_eop(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        agg = next(f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE)
        assert agg.measurement_basis == "stock_eop"

    def test_aggregate_arc_period(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        agg = next(f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE)
        assert agg.period == Period("2024-Q4")

    def test_aggregate_arc_provenance(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        agg = next(f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE)
        assert agg.provenance_source == "fhlb_combined"
        assert "fhlb" in agg.provenance_url.lower()
        assert "Insurance Companies" in agg.provenance_field

    def test_parse_emits_named_member_arcs(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        named = [f for f in facts if f.source_node_id != _INSURER_AGGREGATE_NODE]
        assert len(named) >= 3, "Expected at least 3 named-member arcs from fixture"

    def test_known_members_get_canonical_ids(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        named = {f.source_node_id for f in facts if f.source_node_id != _INSURER_AGGREGATE_NODE}
        assert "insurer:MET_CTIC" in named, "MetLife Connecticut should resolve to insurer:MET_CTIC"
        assert "insurer:LNC" in named, "Lincoln National should resolve to insurer:LNC"
        assert "insurer:ATH_ALIC" in named, "Athene ALIC should resolve to insurer:ATH_ALIC"

    def test_named_member_amounts_in_millions(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        met = next(
            f for f in facts if f.source_node_id == "insurer:MET_CTIC"
        )
        # Fixture has MetLife CT at 8,234 millions
        assert met.dollar_amount_millions == Decimal("8234"), (
            f"Expected 8234 M, got {met.dollar_amount_millions}"
        )

    def test_all_facts_are_decimal(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        for fact in facts:
            assert isinstance(fact.dollar_amount_millions, Decimal), (
                f"{fact.source_node_id}: dollar_amount_millions is not Decimal"
            )

    def test_all_facts_have_sha256(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        expected_sha = fixture_handle.sha256_by_path[str(FIXTURE_PDF)]
        for fact in facts:
            assert fact.sha256_of_source == expected_sha

    def test_sha256_matches_file(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        digest = hashlib.sha256(FIXTURE_PDF.read_bytes()).hexdigest()
        assert fixture_handle.sha256_by_path[str(FIXTURE_PDF)] == digest


# ---------------------------------------------------------------------------
# FhlbCombinedFetcher.validate — clean path
# ---------------------------------------------------------------------------


class TestFhlbCombinedFetcherValidate:
    def test_validate_clean_on_fixture_parse(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        report = fetcher.validate(facts)
        assert report.is_clean, (
            f"Validation errors on fixture: "
            + "; ".join(i.message for i in report.issues if i.severity == "error")
        )

    def test_validate_no_facts_raises_error(
        self, fetcher: FhlbCombinedFetcher
    ) -> None:
        report = fetcher.validate([])
        assert not report.is_clean
        assert any(i.code == "NO_FACTS" for i in report.issues)

    def test_validate_missing_aggregate_is_error(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        # Remove the aggregate arc
        named_only = [f for f in facts if f.source_node_id != _INSURER_AGGREGATE_NODE]
        report = fetcher.validate(named_only)
        assert not report.is_clean
        assert any(i.code == "MISSING_AGGREGATE" for i in report.issues)

    def test_validate_named_exceeds_aggregate_is_error(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        # Inflate the aggregate to be smaller than named sum by replacing it
        agg = next(f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE)
        # Sum of named members from fixture = 8234 + 6789 + 5432 + 4321 + 3876 = 28652
        # Set aggregate to 1000 (less than sum)
        from dataclasses import replace
        tiny_agg = ArcFact(
            period=agg.period,
            source_node_id=agg.source_node_id,
            target_node_id=agg.target_node_id,
            instrument_class=agg.instrument_class,
            dollar_amount_millions=Decimal("1000"),
            measurement_basis=agg.measurement_basis,
            data_quality_flag=agg.data_quality_flag,
            provenance_source=agg.provenance_source,
            provenance_url=agg.provenance_url,
            provenance_filing=agg.provenance_filing,
            provenance_page=agg.provenance_page,
            provenance_field=agg.provenance_field,
            sha256_of_source=agg.sha256_of_source,
        )
        modified = [tiny_agg] + [f for f in facts if f.source_node_id != _INSURER_AGGREGATE_NODE]
        report = fetcher.validate(modified)
        assert not report.is_clean
        assert any(i.code == "NAMED_EXCEEDS_AGGREGATE" for i in report.issues)

    def test_validate_low_amount_gives_warning(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        facts = fetcher.parse(fixture_handle)
        agg = next(f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE)
        # Replace with a suspiciously low value (1 billion = 1000 million, but
        # our threshold is 10 billion → warning at 1000 million)
        low_agg = ArcFact(
            period=agg.period,
            source_node_id=agg.source_node_id,
            target_node_id=agg.target_node_id,
            instrument_class=agg.instrument_class,
            dollar_amount_millions=Decimal("1000"),
            measurement_basis=agg.measurement_basis,
            data_quality_flag=agg.data_quality_flag,
            provenance_source=agg.provenance_source,
            provenance_url=agg.provenance_url,
            provenance_filing=agg.provenance_filing,
            provenance_page=agg.provenance_page,
            provenance_field=agg.provenance_field,
            sha256_of_source=agg.sha256_of_source,
        )
        named_only = [f for f in facts if f.source_node_id != _INSURER_AGGREGATE_NODE]
        modified = [low_agg]  # No named arcs so NAMED_EXCEEDS_AGGREGATE won't fire
        report = fetcher.validate(modified)
        assert any(i.code == "LOW_INSURANCE_TOTAL" for i in report.issues)


# ---------------------------------------------------------------------------
# FhlbCombinedFetcher.run — convenience method
# ---------------------------------------------------------------------------


class TestFhlbCombinedFetcherRun:
    def test_run_returns_facts_and_report(
        self, fetcher: FhlbCombinedFetcher, fixture_handle: RawDataHandle
    ) -> None:
        with patch.object(fetcher, "acquire", return_value=fixture_handle):
            facts, report = fetcher.run(Period("2024-Q4"))
        assert len(facts) > 0
        assert isinstance(report, ValidationReport)
        assert report.is_clean


# ---------------------------------------------------------------------------
# Property-based: all emitted ArcFacts satisfy schema
# ---------------------------------------------------------------------------


class TestFhlbCombinedFetcherProperties:
    @settings(max_examples=1)
    @given(st.just(None))
    def test_all_emitted_arcfacts_valid(self, _: None) -> None:
        """Every ArcFact from parse() must survive ArcFact construction without error.

        This is almost tautological (parse() calls the constructor), but it also
        exercises the to_dict/from_dict round-trip for all emitted facts.
        """
        if not FIXTURE_PDF.exists():
            pytest.skip("Fixture PDF not found")
        fetcher = FhlbCombinedFetcher(data_root=Path("/tmp/fhlb_test_raw"))
        handle = RawDataHandle.from_paths(
            "fhlb_combined", Period("2024-Q4"), [FIXTURE_PDF]
        )
        facts = fetcher.parse(handle)
        for fact in facts:
            d = fact.to_dict()
            restored = ArcFact.from_dict(d)
            assert restored == fact


# ---------------------------------------------------------------------------
# Integration test (marked; not run in fast suite)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFhlbCombinedFetcherIntegration:
    def test_list_available_periods_returns_periods(
        self, fetcher: FhlbCombinedFetcher
    ) -> None:
        periods = fetcher.list_available_periods()
        assert len(periods) > 0
        assert all(isinstance(p, Period) for p in periods)

    def test_acquire_and_parse_recent_period(
        self, fetcher: FhlbCombinedFetcher
    ) -> None:
        periods = fetcher.list_available_periods()
        most_recent = periods[-1]
        handle = fetcher.acquire(most_recent)
        facts = fetcher.parse(handle)
        report = fetcher.validate(facts)
        assert len(facts) > 0
        # Integration result is informational; log warnings but don't assert is_clean
        # (the real report may have formatting variations the fixture doesn't capture)
        for issue in report.issues:
            if issue.severity == "error":
                raise AssertionError(f"Validation error: {issue.message}")
