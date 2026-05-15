"""Unit tests for claimweb.fetchers.z1.

Covers:
- _date_str_to_period: various date-string formats → Period
- _multiplier_factor: label → Decimal conversion factor
- _parse_ddp_csv: FRB DDP CSV format → (series_ids, factors, data)
- Z1Fetcher.parse: full parse on fixture CSVs → ArcFact list
- Z1Fetcher.validate: clean path, empty facts, negative amounts, implausible totals
- Z1Fetcher.list_available_periods: returns sorted list from fixture bundle
- Property-based: all emitted ArcFacts satisfy the ArcFact schema constraints
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from claimweb.fetchers.base import (
    ArcFact,
    DataQualityFlag,
    Period,
    RawDataHandle,
    ValidationReport,
)
from claimweb.fetchers.z1 import (
    _DDP_URL_TEMPLATE,
    _LIC_TOTAL_ASSETS_SERIES,
    _MIN_LIC_TOTAL_ASSETS_MM,
    _SERIES_MAP,
    _TARGET_TABLES,
    Z1Fetcher,
    _date_str_to_period,
    _multiplier_factor,
    _parse_ddp_csv,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "z1"


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_handle(tables: list[str], period: Period, tmp_path: Path) -> RawDataHandle:
    """Build a RawDataHandle pointing at fixture CSVs for the given tables."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in tables:
        src = FIXTURE_DIR / f"{t}.csv"
        assert src.exists(), f"Fixture not found: {src}"
        dst = tmp_path / f"{t}.csv"
        dst.write_bytes(src.read_bytes())
        paths.append(dst)
    return RawDataHandle.from_paths("z1", period, paths)


def _all_tables_handle(period: Period, tmp_path: Path) -> RawDataHandle:
    return _make_handle(_TARGET_TABLES, period, tmp_path)


# ──────────────────────────────────────────────────────────────────────────────
# _date_str_to_period
# ──────────────────────────────────────────────────────────────────────────────


class TestDateStrToPeriod:
    @pytest.mark.parametrize(
        "date_str, expected",
        [
            # ISO end-of-quarter dates
            ("2024-03-31", "2024-Q1"),
            ("2024-06-30", "2024-Q2"),
            ("2024-09-30", "2024-Q3"),
            ("2024-12-31", "2024-Q4"),
            # ISO start-of-quarter dates
            ("2024-01-01", "2024-Q1"),
            ("2024-04-01", "2024-Q2"),
            ("2024-07-01", "2024-Q3"),
            ("2024-10-01", "2024-Q4"),
            # YYYY:QN notation
            ("2023:Q1", "2023-Q1"),
            ("2023:Q4", "2023-Q4"),
            # YYYY-QN notation (already Period-compatible)
            ("2022-Q2", "2022-Q2"),
            # Whitespace tolerance
            ("  2024-12-31  ", "2024-Q4"),
        ],
    )
    def test_known_formats(self, date_str: str, expected: str) -> None:
        result = _date_str_to_period(date_str)
        assert result == Period(expected), f"{date_str!r} → {result} ≠ {expected}"

    @pytest.mark.parametrize(
        "date_str",
        ["", "not-a-date", "2024-02-15", "YYYY-QN", "2024/12/31"],
    )
    def test_invalid_inputs_return_none(self, date_str: str) -> None:
        # mid-quarter or malformed → None
        result = _date_str_to_period(date_str)
        # mid-month dates that don't map to quarter boundaries return None
        # malformed strings return None
        if date_str in {"", "not-a-date", "YYYY-QN", "2024/12/31"}:
            assert result is None, f"Expected None for {date_str!r}, got {result}"
        # "2024-02-15" is mid-quarter: None or a Period but we only assert no crash
        # (behavior: None expected for mid-quarter)
        else:
            assert result is None, f"Expected None for mid-quarter {date_str!r}"


# ──────────────────────────────────────────────────────────────────────────────
# _multiplier_factor
# ──────────────────────────────────────────────────────────────────────────────


class TestMultiplierFactor:
    @pytest.mark.parametrize(
        "label, expected_factor",
        [
            ("Millions", Decimal("1")),
            ("millions", Decimal("1")),
            ("MILLIONS", Decimal("1")),
            ("Billions", Decimal("1000")),
            ("billions", Decimal("1000")),
            ("Thousands", Decimal("0.001")),
            ("thousands", Decimal("0.001")),
            ("", Decimal("1")),            # unknown defaults to Millions
            ("Unknown", Decimal("1")),
        ],
    )
    def test_known_labels(self, label: str, expected_factor: Decimal) -> None:
        assert _multiplier_factor(label) == expected_factor

    def test_billions_converts_to_millions(self) -> None:
        """A value of 1.0 with Billions multiplier becomes 1000 in millions."""
        factor = _multiplier_factor("Billions")
        assert Decimal("1.0") * factor == Decimal("1000")


# ──────────────────────────────────────────────────────────────────────────────
# _parse_ddp_csv
# ──────────────────────────────────────────────────────────────────────────────


_MINIMAL_CSV = """\
Unique Identifier,SERIESAAA.Q,SERIESBBB.Q
Series Description,Series A description,Series B description
Multiplier,Millions,Billions
Currency,USD,USD

Date,SERIESAAA.Q,SERIESBBB.Q
2024-03-31,1000.0,2.0
2024-06-30,1100.0,2.5
"""

_NO_PREAMBLE_CSV = """\
Date,SERIESAAA.Q,SERIESBBB.Q
2024-03-31,1000.0,2.0
2024-06-30,1100.0,2.5
"""

_WITH_NA_CSV = """\
Unique Identifier,SERIESAAA.Q,SERIESBBB.Q
Multiplier,Millions,Millions

Date,SERIESAAA.Q,SERIESBBB.Q
2024-03-31,1000.0,NA
2024-06-30,.,2000.0
"""

_BILLIONS_CSV = """\
Unique Identifier,SERIESAAA.Q
Multiplier,Billions

Date,SERIESAAA.Q
2024-12-31,10.0
"""


class TestParseDdpCsv:
    def test_extracts_series_ids(self) -> None:
        series_ids, _, _ = _parse_ddp_csv(_MINIMAL_CSV)
        assert "SERIESAAA.Q" in series_ids
        assert "SERIESBBB.Q" in series_ids

    def test_applies_millions_multiplier(self) -> None:
        _, factors, _ = _parse_ddp_csv(_MINIMAL_CSV)
        assert factors["SERIESAAA.Q"] == Decimal("1")

    def test_applies_billions_multiplier(self) -> None:
        _, factors, _ = _parse_ddp_csv(_MINIMAL_CSV)
        assert factors["SERIESBBB.Q"] == Decimal("1000")

    def test_data_parsed_for_known_period(self) -> None:
        _, _, data = _parse_ddp_csv(_MINIMAL_CSV)
        p = Period("2024-Q1")
        assert p in data
        assert data[p]["SERIESAAA.Q"] == Decimal("1000.0")

    def test_multiple_periods_extracted(self) -> None:
        _, _, data = _parse_ddp_csv(_MINIMAL_CSV)
        assert Period("2024-Q1") in data
        assert Period("2024-Q2") in data

    def test_na_values_skipped(self) -> None:
        _, _, data = _parse_ddp_csv(_WITH_NA_CSV)
        # Q1: SERIESBBB.Q is NA → should be absent for that period
        assert "SERIESBBB.Q" not in data.get(Period("2024-Q1"), {})
        # Q2: SERIESAAA.Q is "." → absent
        assert "SERIESAAA.Q" not in data.get(Period("2024-Q2"), {})

    def test_dot_na_values_skipped(self) -> None:
        _, _, data = _parse_ddp_csv(_WITH_NA_CSV)
        assert "SERIESAAA.Q" not in data.get(Period("2024-Q2"), {})
        assert "SERIESBBB.Q" in data.get(Period("2024-Q2"), {})

    def test_no_preamble_still_parses(self) -> None:
        """CSV without Unique Identifier preamble: series IDs from Date row."""
        series_ids, _, data = _parse_ddp_csv(_NO_PREAMBLE_CSV)
        assert "SERIESAAA.Q" in series_ids
        assert Period("2024-Q1") in data

    def test_billions_raw_value_kept_as_raw(self) -> None:
        """Raw value is stored as-is; caller applies the factor."""
        _, _, data = _parse_ddp_csv(_BILLIONS_CSV)
        p = Period("2024-Q4")
        assert data[p]["SERIESAAA.Q"] == Decimal("10.0")

    def test_empty_content_returns_empty(self) -> None:
        series_ids, factors, data = _parse_ddp_csv("")
        assert series_ids == []
        assert data == {}

    def test_quoted_fields_stripped(self) -> None:
        quoted_csv = (
            '"Unique Identifier","SERIESAAA.Q"\n'
            '"Multiplier","Millions"\n'
            "\n"
            '"Date","SERIESAAA.Q"\n'
            '"2024-12-31","500.0"\n'
        )
        series_ids, _, data = _parse_ddp_csv(quoted_csv)
        assert "SERIESAAA.Q" in series_ids
        assert data[Period("2024-Q4")]["SERIESAAA.Q"] == Decimal("500.0")


# ──────────────────────────────────────────────────────────────────────────────
# Z1Fetcher.parse — unit tests with fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def fetcher(tmp_path: Path) -> Z1Fetcher:
    return Z1Fetcher(data_root=tmp_path / "raw" / "z1")


class TestZ1FetcherParse:
    def test_parse_returns_arc_facts(self, fetcher: Z1Fetcher, tmp_path: Path) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert len(facts) > 0

    def test_parse_all_facts_have_correct_period(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        period = Period("2024-Q4")
        handle = _all_tables_handle(period, tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.period == period for f in facts)

    def test_parse_all_facts_direct_measured(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED for f in facts)

    def test_parse_all_facts_stock_eop_basis(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.measurement_basis == "stock_eop" for f in facts)

    def test_parse_provenance_source_is_z1(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.provenance_source == "z1" for f in facts)

    def test_parse_all_facts_have_sha256(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(len(f.sha256_of_source) == 64 for f in facts)

    def test_parse_all_amounts_are_decimal(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(isinstance(f.dollar_amount_millions, Decimal) for f in facts)

    def test_parse_l116_lic_total_assets_present(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _make_handle(["L116"], Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        lic_total_facts = [f for f in facts if f.provenance_field == _LIC_TOTAL_ASSETS_SERIES]
        assert len(lic_total_facts) == 1
        # Fixture has 9300000.0 for 2024-Q4
        assert lic_total_facts[0].dollar_amount_millions == Decimal("9300000.0")

    def test_parse_l116_fhlb_advances_correct_direction(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        """FHLB advances are a liability of life insurers: source=life_insurance, target=fhlb."""
        handle = _make_handle(["L116"], Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        fhlb_facts = [
            f for f in facts
            if f.provenance_field == "FL543050005.Q"
        ]
        assert len(fhlb_facts) == 1
        assert fhlb_facts[0].source_node_id == "sector:life_insurance_companies"
        assert fhlb_facts[0].target_node_id == "sector:fhlb"

    def test_parse_l116_mmf_shares_correct_direction(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        """MMF shares are assets of life insurers: source=mmf (issuer), target=life_insurance."""
        handle = _make_handle(["L116"], Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        mmf_facts = [f for f in facts if f.provenance_field == "FL543035005.Q"]
        assert len(mmf_facts) == 1
        assert mmf_facts[0].source_node_id == "sector:money_market_funds"
        assert mmf_facts[0].target_node_id == "sector:life_insurance_companies"

    def test_parse_l208_billions_multiplier_applied(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        """L208 fixture uses Billions multiplier; parser must convert to Millions."""
        handle = _make_handle(["L208"], Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert len(facts) >= 1
        # Fixture: 59000.0 billions → 59000.0 * 1000 = 59_000_000 millions
        debt_facts = [f for f in facts if f.provenance_field == "FL894022705.Q"]
        assert len(debt_facts) == 1
        assert debt_facts[0].dollar_amount_millions == Decimal("59000000")

    def test_parse_missing_period_returns_empty(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        """Requesting a period not in the fixture returns no facts."""
        handle = _make_handle(["L116"], Period("2000-Q1"), tmp_path)
        facts = fetcher.parse(handle)
        # 2000-Q1 is not in the fixture
        assert facts == []

    def test_parse_empty_handle_returns_empty(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        """A handle with no paths produces no facts."""
        handle = RawDataHandle(
            source_id="z1",
            period=Period("2024-Q4"),
            paths=(),
            sha256_by_path={},
        )
        facts = fetcher.parse(handle)
        assert facts == []

    def test_parse_unmapped_series_skipped(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        """Series IDs not in _SERIES_MAP are silently skipped."""
        csv_with_unknown = (
            "Unique Identifier,UNKNOWNXXX.Q,FL543069905.Q\n"
            "Multiplier,Millions,Millions\n\n"
            "Date,UNKNOWNXXX.Q,FL543069905.Q\n"
            "2024-12-31,999.0,9300000.0\n"
        )
        csv_path = tmp_path / "L116.csv"
        csv_path.write_text(csv_with_unknown)
        handle = RawDataHandle.from_paths("z1", Period("2024-Q4"), [csv_path])
        facts = fetcher.parse(handle)
        # Only the mapped series should appear
        assert all(f.provenance_field != "UNKNOWNXXX.Q" for f in facts)
        assert any(f.provenance_field == "FL543069905.Q" for f in facts)

    def test_parse_provenance_url_contains_table_name(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _make_handle(["L116"], Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all("L116" in f.provenance_url for f in facts)

    def test_parse_provenance_filing_contains_period(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _make_handle(["L116"], Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all("2024-Q4" in (f.provenance_filing or "") for f in facts)

    def test_parse_l121_mmf_shares_outstanding(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _make_handle(["L121"], Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        mmf_shares = [f for f in facts if f.provenance_field == "FL634090005.Q"]
        assert len(mmf_shares) == 1
        assert mmf_shares[0].source_node_id == "sector:money_market_funds"

    def test_parse_multiple_tables_all_present(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        tables_seen: set[str] = set()
        for f in facts:
            # provenance_filing = "Z1_{period}_{table}"
            parts = (f.provenance_filing or "").split("_")
            if len(parts) >= 3:
                tables_seen.add(parts[-1])
        # All 7 tables should contribute facts
        assert len(tables_seen) == 7

    def test_parse_all_node_ids_nonempty(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        assert all(f.source_node_id for f in facts)
        assert all(f.target_node_id for f in facts)


# ──────────────────────────────────────────────────────────────────────────────
# Z1Fetcher.validate
# ──────────────────────────────────────────────────────────────────────────────


class TestZ1FetcherValidate:
    def test_validate_clean_facts_is_clean(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        report = fetcher.validate(facts)
        assert report.is_clean, [i.message for i in report.issues]

    def test_validate_empty_facts_errors(self, fetcher: Z1Fetcher) -> None:
        report = fetcher.validate([])
        assert not report.is_clean
        assert any(i.code == "NO_FACTS" for i in report.issues)

    def test_validate_negative_amount_warns(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        # Inject a negative amount
        from dataclasses import replace
        bad_fact = replace(facts[0], dollar_amount_millions=Decimal("-100"))
        report = fetcher.validate([bad_fact] + facts[1:])
        assert any(i.code == "NEGATIVE_AMOUNT" for i in report.issues)

    def test_validate_implausible_lic_total_assets_errors(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        # Replace LIC total assets with a tiny value
        from dataclasses import replace
        modified = [
            replace(f, dollar_amount_millions=Decimal("1"))
            if f.provenance_field == _LIC_TOTAL_ASSETS_SERIES
            else f
            for f in facts
        ]
        report = fetcher.validate(modified)
        assert not report.is_clean
        assert any(
            i.code == "LIC_TOTAL_ASSETS_IMPLAUSIBLE" for i in report.issues
        )

    def test_validate_source_id_correct(
        self, fetcher: Z1Fetcher, tmp_path: Path
    ) -> None:
        handle = _all_tables_handle(Period("2024-Q4"), tmp_path)
        facts = fetcher.parse(handle)
        report = fetcher.validate(facts)
        assert report.source_id == "z1"


# ──────────────────────────────────────────────────────────────────────────────
# Z1Fetcher.list_available_periods
# ──────────────────────────────────────────────────────────────────────────────


class TestZ1ListAvailablePeriods:
    def test_returns_sorted_list(self, fetcher: Z1Fetcher, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "raw" / "z1" / "bundle"
        bundle_dir.mkdir(parents=True)

        # Copy fixture L116 into bundle
        src = FIXTURE_DIR / "L116.csv"
        (bundle_dir / "L116.csv").write_bytes(src.read_bytes())

        # Copy remaining tables too (required by _is_bundle_fresh)
        for t in _TARGET_TABLES:
            fsrc = FIXTURE_DIR / f"{t}.csv"
            if fsrc.exists():
                (bundle_dir / f"{t}.csv").write_bytes(fsrc.read_bytes())

        # Write manifest so _is_bundle_fresh passes
        manifest = {
            "fetched_at": "2099-01-01T00:00:00",
            "tables": _TARGET_TABLES,
        }
        (bundle_dir / "_manifest.json").write_text(json.dumps(manifest))

        periods = fetcher.list_available_periods()
        assert len(periods) >= 1
        assert periods == sorted(periods)
        assert Period("2024-Q4") in periods

    def test_returns_period_objects(self, fetcher: Z1Fetcher, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "raw" / "z1" / "bundle"
        bundle_dir.mkdir(parents=True)
        src = FIXTURE_DIR / "L116.csv"
        (bundle_dir / "L116.csv").write_bytes(src.read_bytes())
        for t in _TARGET_TABLES:
            fsrc = FIXTURE_DIR / f"{t}.csv"
            if fsrc.exists():
                (bundle_dir / f"{t}.csv").write_bytes(fsrc.read_bytes())
        manifest = {"fetched_at": "2099-01-01T00:00:00", "tables": _TARGET_TABLES}
        (bundle_dir / "_manifest.json").write_text(json.dumps(manifest))

        periods = fetcher.list_available_periods()
        assert all(isinstance(p, Period) for p in periods)


# ──────────────────────────────────────────────────────────────────────────────
# Z1Fetcher constructor / source_id / cadence
# ──────────────────────────────────────────────────────────────────────────────


class TestZ1FetcherAttributes:
    def test_source_id(self) -> None:
        f = Z1Fetcher()
        assert f.source_id == "z1"

    def test_cadence(self) -> None:
        f = Z1Fetcher()
        assert f.cadence == "quarterly"

    def test_custom_data_root(self, tmp_path: Path) -> None:
        f = Z1Fetcher(data_root=tmp_path / "my_data")
        assert f._data_root == tmp_path / "my_data"

    def test_default_data_root(self) -> None:
        f = Z1Fetcher()
        assert "z1" in str(f._data_root)


# ──────────────────────────────────────────────────────────────────────────────
# Series map invariants
# ──────────────────────────────────────────────────────────────────────────────


class TestSeriesMap:
    def test_all_series_ids_end_dot_q(self) -> None:
        for sid in _SERIES_MAP:
            assert sid.endswith(".Q"), f"Series {sid} does not end with .Q"

    def test_all_series_ids_start_fl(self) -> None:
        for sid in _SERIES_MAP:
            assert sid.startswith("FL"), f"Series {sid} does not start with FL"

    def test_no_duplicate_entries(self) -> None:
        seen: set[str] = set()
        for sid in _SERIES_MAP:
            assert sid not in seen, f"Duplicate series ID: {sid}"
            seen.add(sid)

    def test_all_source_nodes_nonempty(self) -> None:
        for sid, (_, src, _) in _SERIES_MAP.items():
            assert src, f"Empty source_node_id for series {sid}"

    def test_all_target_nodes_nonempty(self) -> None:
        for sid, (_, _, tgt) in _SERIES_MAP.items():
            assert tgt, f"Empty target_node_id for series {sid}"

    def test_lic_series_uses_life_insurance_node(self) -> None:
        """All L.116 life insurance series reference sector:life_insurance_companies."""
        lic_series = [sid for sid in _SERIES_MAP if "543" in sid]
        assert len(lic_series) > 0
        for sid in lic_series:
            _, src, tgt = _SERIES_MAP[sid]
            node_str = src + tgt
            assert "life_insurance" in node_str, (
                f"Series {sid} does not reference life_insurance_companies: "
                f"src={src!r}, tgt={tgt!r}"
            )

    def test_fhlb_advances_arc_direction(self) -> None:
        """FHLB advances (FL543050005.Q): source=life_insurance, target=fhlb."""
        sid = "FL543050005.Q"
        if sid in _SERIES_MAP:
            _, src, tgt = _SERIES_MAP[sid]
            assert "life_insurance" in src
            assert "fhlb" in tgt

    def test_mmf_shares_arc_direction(self) -> None:
        """MMF shares held by life insurers (FL543035005.Q): source=mmf, target=life_insurance."""
        sid = "FL543035005.Q"
        if sid in _SERIES_MAP:
            _, src, tgt = _SERIES_MAP[sid]
            assert "money_market" in src
            assert "life_insurance" in tgt


# ──────────────────────────────────────────────────────────────────────────────
# Property-based tests
# ──────────────────────────────────────────────────────────────────────────────


@given(
    period_str=st.sampled_from(["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4", "2023-Q4"]),
)
@settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_parse_emits_valid_arc_facts(
    period_str: str, tmp_path: Path
) -> None:
    """All ArcFacts emitted by Z1Fetcher.parse() satisfy the ArcFact schema."""
    fetcher = Z1Fetcher(data_root=tmp_path / "raw" / "z1")
    period = Period(period_str)
    tables = [t for t in _TARGET_TABLES if (FIXTURE_DIR / f"{t}.csv").exists()]
    handle = _make_handle(tables, period, tmp_path / period_str)
    facts = fetcher.parse(handle)

    for f in facts:
        # ArcFact constructor validates; if it survived parse, it's valid.
        # Additional assertions on invariants:
        assert isinstance(f.dollar_amount_millions, Decimal)
        assert f.measurement_basis == "stock_eop"
        assert f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED
        assert f.provenance_source == "z1"
        assert f.source_node_id
        assert f.target_node_id
        assert f.provenance_url
        assert f.provenance_field


@given(
    raw_val=st.decimals(
        min_value=Decimal("0"),
        max_value=Decimal("1E10"),
        allow_nan=False,
        allow_infinity=False,
    ),
    multiplier=st.sampled_from(["Millions", "Billions", "Thousands"]),
)
@settings(max_examples=50)
def test_property_multiplier_application_is_associative(
    raw_val: Decimal, multiplier: str
) -> None:
    """Multiplier application is consistent: factor * raw_val is always Decimal."""
    factor = _multiplier_factor(multiplier)
    result = raw_val * factor
    assert isinstance(result, Decimal)


@given(
    date_str=st.one_of(
        st.just("2024-03-31"),
        st.just("2024-06-30"),
        st.just("2024-09-30"),
        st.just("2024-12-31"),
        st.just("2024-01-01"),
        st.just("2024-04-01"),
        st.just("2024-07-01"),
        st.just("2024-10-01"),
        st.just("2024:Q1"),
        st.just("2024-Q4"),
    )
)
@settings(max_examples=20)
def test_property_date_to_period_is_valid_period(date_str: str) -> None:
    """For all known valid date strings, _date_str_to_period returns a valid Period."""
    result = _date_str_to_period(date_str)
    assert result is not None
    assert isinstance(result, Period)
    assert 1 <= result.quarter <= 4
    assert result.year >= 2000
