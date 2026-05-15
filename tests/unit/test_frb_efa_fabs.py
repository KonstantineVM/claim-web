"""Unit tests for claimweb.fetchers.frb_efa_fabs.

Covers:
- _parse_date: ISO and M/D/YYYY date formats, edge cases
- _date_to_period: month → quarter mapping
- _quarter_end_date: last calendar day per quarter
- _parse_fabs_csv: header detection, NA handling, metadata rows, multi-period
- _aggregate_to_quarters: end-of-quarter selection from daily data
- FrbEfaFabsFetcher.parse: fixture-based tests for Q3 and Q4 2024
- FrbEfaFabsFetcher.validate: clean path, empty, negative, implausible, sum check
- FrbEfaFabsFetcher.list_available_periods: returns sorted periods from fixture
- Property-based (hypothesis): ArcFact schema compliance for all emitted facts
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import date, datetime, timedelta
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
from claimweb.fetchers.frb_efa_fabs import (
    _BILLIONS_TO_MILLIONS,
    _CACHE_LIFETIME_DAYS,
    _COLUMN_MAP,
    _COMPONENT_COLUMNS,
    _COMPONENT_SUM_TOLERANCE,
    _EFA_FABS_URL,
    _FILENAME,
    _MIN_FABS_TOTAL_MM,
    _MONTH_TO_QUARTER,
    _QUARTER_END,
    _TOTAL_COLUMN,
    FrbEfaFabsFetcher,
    _aggregate_to_quarters,
    _date_to_period,
    _parse_date,
    _parse_fabs_csv,
    _quarter_end_date,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "frb_efa_fabs"
FIXTURE_FILE = FIXTURE_DIR / "fabs-chart-data-historical.txt"


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_handle(period: Period, tmp_path: Path) -> RawDataHandle:
    """Build a RawDataHandle pointing at the fixture file."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    dst = tmp_path / _FILENAME
    dst.write_bytes(FIXTURE_FILE.read_bytes())
    return RawDataHandle.from_paths("frb_efa_fabs", period, [dst])


# ──────────────────────────────────────────────────────────────────────────────
# _parse_date
# ──────────────────────────────────────────────────────────────────────────────


class TestParseDate:
    @pytest.mark.parametrize(
        "date_str, expected",
        [
            # ISO format
            ("2024-09-30", date(2024, 9, 30)),
            ("2024-12-31", date(2024, 12, 31)),
            ("1994-11-01", date(1994, 11, 1)),
            # M/D/YYYY (US format sometimes used in older FRB files)
            ("9/30/2024", date(2024, 9, 30)),
            ("12/31/2024", date(2024, 12, 31)),
            ("1/1/2000", date(2000, 1, 1)),
            # Whitespace tolerance
            ("  2024-09-30  ", date(2024, 9, 30)),
        ],
    )
    def test_known_formats(self, date_str: str, expected: date) -> None:
        result = _parse_date(date_str)
        assert result == expected, f"{date_str!r} → {result} ≠ {expected}"

    @pytest.mark.parametrize(
        "date_str",
        ["", "not-a-date", "2024/09/30", "YYYY-MM-DD", "2024-13-01"],
    )
    def test_invalid_returns_none(self, date_str: str) -> None:
        result = _parse_date(date_str)
        assert result is None, f"Expected None for {date_str!r}, got {result}"

    def test_empty_string_returns_none(self) -> None:
        assert _parse_date("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _parse_date("   ") is None


# ──────────────────────────────────────────────────────────────────────────────
# _date_to_period
# ──────────────────────────────────────────────────────────────────────────────


class TestDateToPeriod:
    @pytest.mark.parametrize(
        "d, expected",
        [
            (date(2024, 1, 15), "2024-Q1"),
            (date(2024, 3, 31), "2024-Q1"),
            (date(2024, 4, 1), "2024-Q2"),
            (date(2024, 6, 30), "2024-Q2"),
            (date(2024, 7, 1), "2024-Q3"),
            (date(2024, 9, 30), "2024-Q3"),
            (date(2024, 10, 1), "2024-Q4"),
            (date(2024, 12, 31), "2024-Q4"),
            (date(1994, 11, 1), "1994-Q4"),
        ],
    )
    def test_month_to_quarter(self, d: date, expected: str) -> None:
        assert _date_to_period(d) == Period(expected)

    def test_year_boundary(self) -> None:
        assert _date_to_period(date(2023, 12, 31)) == Period("2023-Q4")
        assert _date_to_period(date(2024, 1, 1)) == Period("2024-Q1")


# ──────────────────────────────────────────────────────────────────────────────
# _quarter_end_date
# ──────────────────────────────────────────────────────────────────────────────


class TestQuarterEndDate:
    @pytest.mark.parametrize(
        "period_str, expected",
        [
            ("2024-Q1", date(2024, 3, 31)),
            ("2024-Q2", date(2024, 6, 30)),
            ("2024-Q3", date(2024, 9, 30)),
            ("2024-Q4", date(2024, 12, 31)),
            ("2000-Q1", date(2000, 3, 31)),
        ],
    )
    def test_end_dates(self, period_str: str, expected: date) -> None:
        assert _quarter_end_date(Period(period_str)) == expected


# ──────────────────────────────────────────────────────────────────────────────
# _parse_fabs_csv
# ──────────────────────────────────────────────────────────────────────────────

_MINIMAL_CSV = """\
Date,FABS (US),FABS (Non-US),FABCP (US)
2024-07-01,175.3,55.2,NA
2024-09-30,180.2,56.8,13.0
"""

_WITH_METADATA_CSV = """\
Unique Identifier,FABS_US,FABS_NONUS,FABCP_US
Series Description,Total US FABS,Non-US FABS,US FABCP
Multiplier,1,1,1

Date,FABS (US),FABS (Non-US),FABCP (US)
2024-07-01,175.3,55.2,NA
2024-09-30,180.2,56.8,13.0
"""

_WITH_DOT_NA_CSV = """\
Date,FABS (US),FABN - Medium-Term (US)
2024-07-01,175.3,.
2024-09-30,180.2,103.5
"""

_MSLASH_DATE_CSV = """\
Date,FABS (US)
9/30/2024,180.2
12/31/2024,185.5
"""

_EMPTY_CSV = ""


class TestParseFabsCsv:
    def test_extracts_columns(self) -> None:
        columns, _ = _parse_fabs_csv(_MINIMAL_CSV)
        assert "fabs (us)" in columns
        assert "fabs (non-us)" in columns
        assert "fabcp (us)" in columns

    def test_columns_normalized_lowercase(self) -> None:
        columns, _ = _parse_fabs_csv(_MINIMAL_CSV)
        assert all(c == c.lower() for c in columns)
        assert all(c == c.strip() for c in columns)

    def test_parses_data_rows(self) -> None:
        _, daily = _parse_fabs_csv(_MINIMAL_CSV)
        assert date(2024, 7, 1) in daily
        assert date(2024, 9, 30) in daily

    def test_na_cells_absent_from_inner_dict(self) -> None:
        _, daily = _parse_fabs_csv(_MINIMAL_CSV)
        # FABCP (US) is NA on 2024-07-01
        assert "fabcp (us)" not in daily.get(date(2024, 7, 1), {})

    def test_na_cells_present_when_populated(self) -> None:
        _, daily = _parse_fabs_csv(_MINIMAL_CSV)
        assert "fabcp (us)" in daily.get(date(2024, 9, 30), {})
        assert daily[date(2024, 9, 30)]["fabcp (us)"] == Decimal("13.0")

    def test_dot_na_cells_absent(self) -> None:
        _, daily = _parse_fabs_csv(_WITH_DOT_NA_CSV)
        # FABN - Medium-Term (US) is "." on 2024-07-01
        assert "fabn - medium-term (us)" not in daily.get(date(2024, 7, 1), {})
        # But present on 2024-09-30
        assert "fabn - medium-term (us)" in daily.get(date(2024, 9, 30), {})

    def test_metadata_header_rows_skipped(self) -> None:
        columns, daily = _parse_fabs_csv(_WITH_METADATA_CSV)
        assert "fabs (us)" in columns
        assert date(2024, 7, 1) in daily

    def test_values_are_decimal(self) -> None:
        _, daily = _parse_fabs_csv(_MINIMAL_CSV)
        val = daily[date(2024, 9, 30)]["fabs (us)"]
        assert isinstance(val, Decimal)

    def test_values_match_source(self) -> None:
        _, daily = _parse_fabs_csv(_MINIMAL_CSV)
        assert daily[date(2024, 7, 1)]["fabs (us)"] == Decimal("175.3")
        assert daily[date(2024, 9, 30)]["fabs (us)"] == Decimal("180.2")

    def test_mslash_date_format(self) -> None:
        _, daily = _parse_fabs_csv(_MSLASH_DATE_CSV)
        assert date(2024, 9, 30) in daily
        assert date(2024, 12, 31) in daily

    def test_empty_content_returns_empty(self) -> None:
        columns, daily = _parse_fabs_csv(_EMPTY_CSV)
        assert columns == []
        assert daily == {}

    def test_multiple_periods_extracted(self) -> None:
        _, daily = _parse_fabs_csv(_MINIMAL_CSV)
        assert len(daily) == 2

    def test_fixture_file_parseable(self) -> None:
        content = FIXTURE_FILE.read_text()
        columns, daily = _parse_fabs_csv(content)
        assert len(columns) > 0
        assert len(daily) > 0

    def test_fixture_has_expected_columns(self) -> None:
        content = FIXTURE_FILE.read_text()
        columns, _ = _parse_fabs_csv(content)
        assert "fabs (us)" in columns
        assert "fabn - medium-term (us)" in columns
        assert "fabn - extendibles (us)" in columns
        assert "fabcp (us)" in columns


# ──────────────────────────────────────────────────────────────────────────────
# _aggregate_to_quarters
# ──────────────────────────────────────────────────────────────────────────────


class TestAggregateToQuarters:
    def test_selects_quarter_end_date(self) -> None:
        daily = {
            date(2024, 9, 27): {"fabs (us)": Decimal("180.0")},
            date(2024, 9, 30): {"fabs (us)": Decimal("180.2")},  # quarter end
        }
        q = _aggregate_to_quarters(daily)
        assert Period("2024-Q3") in q
        assert q[Period("2024-Q3")]["fabs (us)"] == Decimal("180.2")

    def test_selects_last_available_before_end(self) -> None:
        # If last day of quarter is missing, falls back to prior business day
        daily = {
            date(2024, 9, 27): {"fabs (us)": Decimal("180.0")},
            # No 2024-09-30 entry
        }
        q = _aggregate_to_quarters(daily)
        assert Period("2024-Q3") in q
        assert q[Period("2024-Q3")]["fabs (us)"] == Decimal("180.0")

    def test_multiple_quarters_extracted(self) -> None:
        daily = {
            date(2024, 9, 30): {"fabs (us)": Decimal("180.2")},
            date(2024, 12, 31): {"fabs (us)": Decimal("185.5")},
        }
        q = _aggregate_to_quarters(daily)
        assert Period("2024-Q3") in q
        assert Period("2024-Q4") in q

    def test_midquarter_entries_use_last(self) -> None:
        daily = {
            date(2024, 7, 1): {"fabs (us)": Decimal("175.0")},
            date(2024, 7, 15): {"fabs (us)": Decimal("176.0")},
            date(2024, 9, 30): {"fabs (us)": Decimal("180.2")},
        }
        q = _aggregate_to_quarters(daily)
        assert q[Period("2024-Q3")]["fabs (us)"] == Decimal("180.2")

    def test_empty_daily_data(self) -> None:
        q = _aggregate_to_quarters({})
        assert q == {}

    def test_different_years_separated(self) -> None:
        daily = {
            date(2023, 12, 31): {"fabs (us)": Decimal("170.0")},
            date(2024, 3, 31): {"fabs (us)": Decimal("173.0")},
        }
        q = _aggregate_to_quarters(daily)
        assert Period("2023-Q4") in q
        assert Period("2024-Q1") in q
        assert q[Period("2023-Q4")]["fabs (us)"] == Decimal("170.0")
        assert q[Period("2024-Q1")]["fabs (us)"] == Decimal("173.0")


# ──────────────────────────────────────────────────────────────────────────────
# FrbEfaFabsFetcher.parse  (fixture-based)
# ──────────────────────────────────────────────────────────────────────────────


class TestFrbEfaFabsFetcherParse:
    def test_parse_q3_returns_facts(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q3"), tmp_path / "h")
        facts = fetcher.parse(handle)
        assert len(facts) > 0

    def test_parse_q4_returns_facts(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        assert len(facts) > 0

    def test_parse_total_amount_billions_converted(self, tmp_path: Path) -> None:
        # Q4 fixture FABS (US) = 185.5 billion → 185500 million
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        total = next(f for f in facts if f.provenance_field == "fabs (us)")
        assert total.dollar_amount_millions == Decimal("185500")

    def test_parse_total_amount_q3(self, tmp_path: Path) -> None:
        # Q3 fixture FABS (US) = 180.2 billion → 180200 million
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q3"), tmp_path / "h")
        facts = fetcher.parse(handle)
        total = next(f for f in facts if f.provenance_field == "fabs (us)")
        assert total.dollar_amount_millions == Decimal("180200")

    def test_parse_arc_source_node(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.source_node_id == "sector:fabn_spv"

    def test_parse_total_arc_target_node(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        total = next(f for f in facts if f.provenance_field == "fabs (us)")
        assert total.target_node_id == "z1:all_holders"

    def test_parse_instrument_class_a2(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.instrument_class == ArcClass.A2

    def test_parse_measurement_basis_stock_eop(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.measurement_basis == "stock_eop"

    def test_parse_data_quality_direct_measured(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED

    def test_parse_provenance_url_set(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.provenance_url == _EFA_FABS_URL

    def test_parse_provenance_filing_set(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        for f in facts:
            assert "2024-Q4" in f.provenance_filing

    def test_parse_sha256_matches_file(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        expected_sha = list(handle.sha256_by_path.values())[0]
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.sha256_of_source == expected_sha

    def test_parse_period_attribute(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q3"), tmp_path / "h")
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.period == Period("2024-Q3")

    def test_parse_missing_period_returns_empty(self, tmp_path: Path) -> None:
        # Request a period not in the fixture (e.g., 2020-Q1)
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2020-Q1"), tmp_path / "h")
        facts = fetcher.parse(handle)
        assert facts == []

    def test_parse_empty_handle_returns_empty(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = RawDataHandle(
            source_id="frb_efa_fabs",
            period=Period("2024-Q4"),
            paths=(),
            sha256_by_path={},
        )
        facts = fetcher.parse(handle)
        assert facts == []

    def test_parse_dollar_amounts_are_decimal(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        for f in facts:
            assert isinstance(f.dollar_amount_millions, Decimal)

    def test_parse_non_us_columns_not_emitted(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        for f in facts:
            assert "non-us" not in f.provenance_field
            assert "total" not in f.provenance_field or f.provenance_field == _TOTAL_COLUMN

    def test_parse_fabcp_present_at_quarter_end(self, tmp_path: Path) -> None:
        # Fixture has FABCP populated at Q4 end (2024-12-31)
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        fabcp = next(
            (f for f in facts if f.provenance_field == "fabcp (us)"), None
        )
        assert fabcp is not None
        assert fabcp.dollar_amount_millions == Decimal("13000")

    def test_parse_fabcp_absent_when_na(self, tmp_path: Path) -> None:
        # In Q3, FABCP is NA until the quarter-end date (2024-09-30).
        # The aggregation selects 2024-09-30 which has FABCP = 13.0.
        # So FABCP should be present.
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q3"), tmp_path / "h")
        facts = fetcher.parse(handle)
        fabcp = next(
            (f for f in facts if f.provenance_field == "fabcp (us)"), None
        )
        # FABCP is populated on 2024-09-30 (end of Q3) in fixture
        assert fabcp is not None


# ──────────────────────────────────────────────────────────────────────────────
# FrbEfaFabsFetcher.validate
# ──────────────────────────────────────────────────────────────────────────────

_SHA256_DUMMY = "a" * 64


def _make_fact(
    period: str = "2024-Q4",
    field: str = "fabs (us)",
    amount: str = "180000",
    source: str = "sector:fabn_spv",
    target: str = "z1:all_holders",
) -> ArcFact:
    return ArcFact(
        period=Period(period),
        source_node_id=source,
        target_node_id=target,
        instrument_class=ArcClass.A2,
        dollar_amount_millions=Decimal(amount),
        measurement_basis="stock_eop",
        data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
        provenance_source="frb_efa_fabs",
        provenance_url=_EFA_FABS_URL,
        provenance_filing="EFA_FABS_2024-Q4",
        provenance_page=None,
        provenance_field=field,
        sha256_of_source=_SHA256_DUMMY,
    )


class TestFrbEfaFabsFetcherValidate:
    def test_validate_clean_path_is_clean(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = [_make_fact(amount="180000")]
        report = fetcher.validate(facts)
        assert report.is_clean

    def test_validate_empty_facts_is_error(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        report = fetcher.validate([])
        assert not report.is_clean
        codes = {i.code for i in report.issues}
        assert "NO_FACTS" in codes

    def test_validate_negative_amount_is_warning(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = [_make_fact(amount="-5000")]
        report = fetcher.validate(facts)
        codes = {i.code for i in report.issues}
        assert "NEGATIVE_AMOUNT" in codes

    def test_validate_negative_not_error_level(self, tmp_path: Path) -> None:
        # Total is above the floor; only a sub-component is negative (data anomaly).
        # The NEGATIVE_AMOUNT check is a warning, not an error.
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = [
            _make_fact(field="fabs (us)", amount="100000", target="z1:all_holders"),
            _make_fact(
                field="fabn - medium-term (us)",
                amount="-500",
                target="efa:fabn_mt_holders",
            ),
        ]
        report = fetcher.validate(facts)
        errors = [i for i in report.issues if i.severity == "error"]
        assert len(errors) == 0
        neg_warnings = [
            i for i in report.issues
            if i.severity == "warning" and i.code == "NEGATIVE_AMOUNT"
        ]
        assert len(neg_warnings) == 1

    def test_validate_implausible_total_is_error(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = [_make_fact(amount="100")]  # Only $100M — below $10B floor
        report = fetcher.validate(facts)
        assert not report.is_clean
        codes = {i.code for i in report.issues}
        assert "FABS_TOTAL_IMPLAUSIBLE" in codes

    def test_validate_plausible_total_no_error(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = [_make_fact(amount="150000")]
        report = fetcher.validate(facts)
        errors = [i for i in report.issues if i.severity == "error"]
        assert len(errors) == 0

    def test_validate_component_sum_check_no_warning_when_close(
        self, tmp_path: Path
    ) -> None:
        # Total = 100000, components sum to 100000 (exact match → no warning)
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = [
            _make_fact(field="fabs (us)", amount="100000", target="z1:all_holders"),
            _make_fact(
                field="fabn - medium-term (us)",
                amount="60000",
                target="efa:fabn_mt_holders",
            ),
            _make_fact(
                field="fabn - short-term (us)",
                amount="25000",
                target="efa:fabn_st_holders",
            ),
            _make_fact(
                field="fabn - extendibles (us)",
                amount="10000",
                target="efa:xfabs_holders",
            ),
            _make_fact(
                field="fabcp (us)", amount="5000", target="efa:fabcp_holders"
            ),
        ]
        report = fetcher.validate(facts)
        codes = {i.code for i in report.issues}
        assert "COMPONENTS_DONT_SUM_TO_TOTAL" not in codes

    def test_validate_component_sum_warning_when_far_off(
        self, tmp_path: Path
    ) -> None:
        # Total = 100000, components sum to 50000 (50% difference → warning)
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = [
            _make_fact(field="fabs (us)", amount="100000", target="z1:all_holders"),
            _make_fact(
                field="fabn - medium-term (us)",
                amount="50000",
                target="efa:fabn_mt_holders",
            ),
        ]
        report = fetcher.validate(facts)
        codes = {i.code for i in report.issues}
        assert "COMPONENTS_DONT_SUM_TO_TOTAL" in codes

    def test_validate_deduplicates_xfabs_alt_names(self, tmp_path: Path) -> None:
        # Both 'extendibles' and 'putable' map to efa:xfabs_holders;
        # only one should be counted in the component sum.
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = [
            _make_fact(field="fabs (us)", amount="100000", target="z1:all_holders"),
            _make_fact(
                field="fabn - extendibles (us)",
                amount="10000",
                target="efa:xfabs_holders",
            ),
            _make_fact(
                field="fabn - putable (us)",
                amount="10000",
                target="efa:xfabs_holders",
            ),
        ]
        report = fetcher.validate(facts)
        # Component sum should count xfabs only once = 10000, not 20000.
        # 10000 vs 100000 = 90% diff → warning expected (good, proves dedup works)
        codes = {i.code for i in report.issues}
        assert "COMPONENTS_DONT_SUM_TO_TOTAL" in codes

    def test_validate_fixture_parse_is_clean(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        handle = _make_handle(Period("2024-Q4"), tmp_path / "h")
        facts = fetcher.parse(handle)
        report = fetcher.validate(facts)
        assert report.is_clean, report.issues


# ──────────────────────────────────────────────────────────────────────────────
# FrbEfaFabsFetcher.list_available_periods  (fixture-based via patched cache)
# ──────────────────────────────────────────────────────────────────────────────


class TestFrbEfaFabsFetcherListPeriods:
    def test_returns_list(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        # Seed the cache with the fixture
        fetcher._cache_path.parent.mkdir(parents=True, exist_ok=True)
        fetcher._cache_path.write_bytes(FIXTURE_FILE.read_bytes())
        fetcher._manifest_path.write_text(
            json.dumps({"fetched_at": datetime.utcnow().isoformat()})
        )
        periods = fetcher.list_available_periods()
        assert isinstance(periods, list)

    def test_returns_sorted_periods(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        fetcher._cache_path.parent.mkdir(parents=True, exist_ok=True)
        fetcher._cache_path.write_bytes(FIXTURE_FILE.read_bytes())
        fetcher._manifest_path.write_text(
            json.dumps({"fetched_at": datetime.utcnow().isoformat()})
        )
        periods = fetcher.list_available_periods()
        assert periods == sorted(periods)

    def test_fixture_periods_q3_and_q4(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        fetcher._cache_path.parent.mkdir(parents=True, exist_ok=True)
        fetcher._cache_path.write_bytes(FIXTURE_FILE.read_bytes())
        fetcher._manifest_path.write_text(
            json.dumps({"fetched_at": datetime.utcnow().isoformat()})
        )
        periods = fetcher.list_available_periods()
        assert Period("2024-Q3") in periods
        assert Period("2024-Q4") in periods

    def test_empty_cache_returns_empty(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        with patch.object(fetcher, "_ensure_cached"):
            # Cache path doesn't exist → returns []
            periods = fetcher.list_available_periods()
            assert periods == []


# ──────────────────────────────────────────────────────────────────────────────
# Source ID and cadence
# ──────────────────────────────────────────────────────────────────────────────


class TestFrbEfaFabsFetcherAttributes:
    def test_source_id(self) -> None:
        fetcher = FrbEfaFabsFetcher()
        assert fetcher.source_id == "frb_efa_fabs"

    def test_cadence(self) -> None:
        fetcher = FrbEfaFabsFetcher()
        assert fetcher.cadence == "quarterly"

    def test_column_map_keys_are_lowercase(self) -> None:
        for k in _COLUMN_MAP:
            assert k == k.lower(), f"Column key {k!r} is not lower-case"

    def test_component_columns_subset_of_column_map(self) -> None:
        for col in _COMPONENT_COLUMNS:
            assert col in _COLUMN_MAP, f"{col!r} in _COMPONENT_COLUMNS but not in _COLUMN_MAP"

    def test_total_column_in_column_map(self) -> None:
        assert _TOTAL_COLUMN in _COLUMN_MAP

    def test_billions_to_millions_factor(self) -> None:
        assert _BILLIONS_TO_MILLIONS == Decimal("1000")

    def test_min_fabs_floor_is_decimal(self) -> None:
        assert isinstance(_MIN_FABS_TOTAL_MM, Decimal)


# ──────────────────────────────────────────────────────────────────────────────
# Cache freshness helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestCacheFreshness:
    def test_is_fresh_with_recent_manifest(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        fetcher._cache_path.parent.mkdir(parents=True, exist_ok=True)
        fetcher._cache_path.write_text("data")
        fetcher._manifest_path.write_text(
            json.dumps({"fetched_at": datetime.utcnow().isoformat()})
        )
        assert fetcher._is_cache_fresh() is True

    def test_not_fresh_with_old_manifest(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        fetcher._cache_path.parent.mkdir(parents=True, exist_ok=True)
        fetcher._cache_path.write_text("data")
        old_time = datetime.utcnow() - timedelta(days=_CACHE_LIFETIME_DAYS + 1)
        fetcher._manifest_path.write_text(
            json.dumps({"fetched_at": old_time.isoformat()})
        )
        assert fetcher._is_cache_fresh() is False

    def test_not_fresh_without_manifest(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        assert fetcher._is_cache_fresh() is False

    def test_not_fresh_without_cache_file(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        fetcher._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        fetcher._manifest_path.write_text(
            json.dumps({"fetched_at": datetime.utcnow().isoformat()})
        )
        # Cache file itself is missing
        assert fetcher._is_cache_fresh() is False

    def test_not_fresh_with_corrupt_manifest(self, tmp_path: Path) -> None:
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        fetcher._cache_path.parent.mkdir(parents=True, exist_ok=True)
        fetcher._cache_path.write_text("data")
        fetcher._manifest_path.write_text("not valid json{{{")
        assert fetcher._is_cache_fresh() is False


# ──────────────────────────────────────────────────────────────────────────────
# Property-based tests (hypothesis)
# ──────────────────────────────────────────────────────────────────────────────

# Strategy: generate a valid EFA FABS CSV string with one or more data rows
# and verify that the fetcher's output satisfies the ArcFact schema.

_VALID_COLUMNS = [
    "FABS (US)",
    "FABS (Non-US)",
    "FABS (Total)",
    "FABN - Medium-Term (US)",
    "FABN - Short-Term (US)",
    "FABN - Extendibles (US)",
    "FABCP (US)",
]


def _make_fabs_csv(rows: list[tuple[str, list[str]]]) -> str:
    """Build a minimal EFA FABS CSV from (date_str, [value_str, ...]) rows."""
    header = "Date," + ",".join(_VALID_COLUMNS)
    lines = [header]
    for date_str, vals in rows:
        padded = vals + ["NA"] * (len(_VALID_COLUMNS) - len(vals))
        lines.append(date_str + "," + ",".join(padded[: len(_VALID_COLUMNS)]))
    return "\n".join(lines) + "\n"


_pos_decimal_str = st.decimals(
    min_value="0.1", max_value="999.9", places=1, allow_nan=False, allow_infinity=False
).map(str)

_quarter_end_dates = st.sampled_from([
    "2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31",
    "2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31",
])


@given(
    date_str=_quarter_end_dates,
    amount=_pos_decimal_str,
)
@settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow])
def test_property_emitted_facts_pass_arcfact_schema(
    date_str: str, amount: str
) -> None:
    """All ArcFacts emitted by parse() satisfy the ArcFact schema invariants."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        csv_content = _make_fabs_csv([(date_str, [amount])])
        fixture = tmp_path / _FILENAME
        fixture.write_text(csv_content)
        d = _parse_date(date_str)
        assert d is not None
        period = _date_to_period(d)
        handle = RawDataHandle.from_paths("frb_efa_fabs", period, [fixture])
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.measurement_basis == "stock_eop"
            assert f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED
            assert isinstance(f.dollar_amount_millions, Decimal)
            assert f.dollar_amount_millions >= Decimal("0")
            assert f.provenance_url != ""
            assert f.provenance_field != ""
            assert len(f.sha256_of_source) == 64


@given(
    date_str=_quarter_end_dates,
    amount=_pos_decimal_str,
)
@settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow])
def test_property_amounts_converted_from_billions(
    date_str: str, amount: str
) -> None:
    """Dollar amounts are multiplied by 1000 (billions → millions)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        csv_content = _make_fabs_csv([(date_str, [amount])])
        fixture = tmp_path / _FILENAME
        fixture.write_text(csv_content)
        d = _parse_date(date_str)
        assert d is not None
        period = _date_to_period(d)
        handle = RawDataHandle.from_paths("frb_efa_fabs", period, [fixture])
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = fetcher.parse(handle)
        if facts:
            total = next((f for f in facts if f.provenance_field == "fabs (us)"), None)
            if total is not None:
                expected = (Decimal(amount) * _BILLIONS_TO_MILLIONS).normalize()
                assert total.dollar_amount_millions == expected


@given(
    date_str=_quarter_end_dates,
    amount=_pos_decimal_str,
)
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_property_validate_clean_facts_no_error(
    date_str: str, amount: str
) -> None:
    """Clean FABS facts above the plausibility floor produce a clean report."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        csv_content = _make_fabs_csv([(date_str, [amount])])
        fixture = tmp_path / _FILENAME
        fixture.write_text(csv_content)
        d = _parse_date(date_str)
        assert d is not None
        period = _date_to_period(d)
        handle = RawDataHandle.from_paths("frb_efa_fabs", period, [fixture])
        fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
        facts = fetcher.parse(handle)
        if not facts:
            return
        total = next((f for f in facts if f.provenance_field == "fabs (us)"), None)
        if total is None or total.dollar_amount_millions < _MIN_FABS_TOTAL_MM:
            return
        report = fetcher.validate(facts)
        errors = [i for i in report.issues if i.severity == "error"]
        assert len(errors) == 0, errors


def test_property_parse_run_returns_list(tmp_path: Path) -> None:
    """run() convenience method returns (list[ArcFact], ValidationReport)."""
    fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
    with patch.object(fetcher, "_ensure_cached"):
        fetcher._cache_path.parent.mkdir(parents=True, exist_ok=True)
        fetcher._cache_path.write_bytes(FIXTURE_FILE.read_bytes())
        facts, report = fetcher.run(Period("2024-Q4"))
        assert isinstance(facts, list)
        assert isinstance(report, ValidationReport)


# ──────────────────────────────────────────────────────────────────────────────
# Integration test (excluded from fast suite)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_integration_acquire_and_parse_real_data(tmp_path: Path) -> None:
    """Acquire the live EFA FABS dataset from the FRB and parse 2024-Q4."""
    fetcher = FrbEfaFabsFetcher(data_root=tmp_path)
    handle = fetcher.acquire(Period("2024-Q4"))
    assert handle.paths, "Expected at least one file in the handle"
    facts = fetcher.parse(handle)
    assert len(facts) > 0, "Expected ArcFacts from live data"
    report = fetcher.validate(facts)
    assert report.is_clean, report.issues
    total = next((f for f in facts if f.provenance_field == _TOTAL_COLUMN), None)
    assert total is not None
    assert total.dollar_amount_millions > _MIN_FABS_TOTAL_MM
