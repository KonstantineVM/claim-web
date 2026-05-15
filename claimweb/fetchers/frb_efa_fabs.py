"""FRB Enhanced Financial Accounts — FABS dataset fetcher (project plan §10.9).

Source: https://www.federalreserve.gov/releases/efa/efa-project-funding-agreement-backed-securities.htm
Data file: https://www.federalreserve.gov/releases/efa/fabs-chart-data-historical.txt
Cadence: daily series, aggregated to quarterly end-of-period snapshots.
Format: CSV (.txt extension), daily rows, values in billions of USD.
Populates: A2 arcs (FABNs / Funding Agreement-Backed Notes, project plan §4).

The FABS dataset (Foley-Fisher, Meisenzahl, Narajabad, Perozek, Verani 2016)
tracks daily outstanding amounts of funding agreement-backed securities:

  FABS (US)                  — total US FABS outstanding (FABN+FABCP+FABR), billions
  FABN - Medium-Term (US)    — FABN with fixed terms > 397 days, billions
  FABN - Short-Term (US)     — FABN with fixed terms ≤ 397 days, billions
  FABN - Extendibles (US)    — FABN with embedded put options (XFABS), billions
                               This is the instrument behind the 2007 run.
  FABN - Putable (US)        — Alternative name for the extendible/XFABS category
                               in some file vintages.
  FABCP (US)                 — Funding Agreement-backed Commercial Paper, billions.
                               Quarterly-only: populated only at quarter-end dates.

Arc direction (project plan §1):
  source_node_id = sector:fabn_spv   (SPVs that issue the FABN / FABCP)
  target_node_id = z1:all_holders    for the aggregate "FABS (US)" total
  target_node_id = efa:*_holders     for instrument-level sub-components

Dollar amounts: source file is in billions of USD; multiplied by 1000 → millions.

Data quality: DIRECT_MEASURED — FRB publishes this data based on Bloomberg,
  DTCC, and Moody's transaction records (Foley-Fisher et al. 2016 methodology).
Measurement basis: stock_eop — end-of-quarter snapshot selected as the last
  available daily observation on or before the final calendar day of the quarter.

Non-US and Total columns present in the file are not mapped; CLAIM-WEB models
  the US-domiciled issuer circuit only. The "FABS (US)" total may exceed the sum
  of its mapped sub-components because FABR (Funding Agreement-backed Repurchase
  Agreements) is included in the aggregate but reported separately.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import httpx

from claimweb.fetchers.base import (
    ArcClass,
    ArcFact,
    BaseFetcher,
    DataQualityFlag,
    Period,
    RawDataHandle,
    ValidationReport,
)

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_USER_AGENT = (
    "CLAIM-WEB academic research; "
    "contact: researchers studying systemic risk in life insurance sector"
)
_REQUEST_TIMEOUT = 120.0

_EFA_FABS_URL = (
    "https://www.federalreserve.gov/releases/efa/fabs-chart-data-historical.txt"
)
_FILENAME = "fabs-chart-data-historical.txt"

# Re-download when cached copy is older than this many days (data updated daily).
_CACHE_LIFETIME_DAYS = 1

# Source file values are in billions; project canonical unit is millions.
_BILLIONS_TO_MILLIONS = Decimal("1000")

# Plausibility floor for total US FABS outstanding (millions).
# Market has always exceeded $10B since 1994 inception.
_MIN_FABS_TOTAL_MM = Decimal("10_000")

# Tolerance for component-sum cross-check: FABR (repo) is included in FABS (US)
# total but not reported separately, so the sub-components will be below total.
_COMPONENT_SUM_TOLERANCE = Decimal("0.30")  # 30%

# ──────────────────────────────────────────────────────────────────────────────
# Column → arc mapping
# ──────────────────────────────────────────────────────────────────────────────

# Keys are normalized column headers (lower-cased, stripped).
# Only US-issuer columns are mapped; Non-US and Total columns are ignored.
_COLUMN_MAP: dict[str, tuple[ArcClass, str, str]] = {
    # Aggregate total US FABS outstanding (Law 3 sectoral constraint)
    "fabs (us)": (ArcClass.A2, "sector:fabn_spv", "z1:all_holders"),
    # FABN medium-term (fixed term > 397 days)
    "fabn - medium-term (us)": (ArcClass.A2, "sector:fabn_spv", "efa:fabn_mt_holders"),
    # FABN short-term (fixed term ≤ 397 days)
    "fabn - short-term (us)": (ArcClass.A2, "sector:fabn_spv", "efa:fabn_st_holders"),
    # FABN extendibles = XFABS (the 2007 run instrument)
    "fabn - extendibles (us)": (ArcClass.A2, "sector:fabn_spv", "efa:xfabs_holders"),
    # FABN putable (alternative name for extendible/XFABS in some file vintages)
    "fabn - putable (us)": (ArcClass.A2, "sector:fabn_spv", "efa:xfabs_holders"),
    # FABCP (quarterly-only in source)
    "fabcp (us)": (ArcClass.A2, "sector:fabn_spv", "efa:fabcp_holders"),
}

_TOTAL_COLUMN = "fabs (us)"

# Sub-components whose sum ≈ FABS (US) (modulo FABR).
# Both "extendibles" and "putable" name the same series; dedup by (src, tgt).
_COMPONENT_COLUMNS = frozenset({
    "fabn - medium-term (us)",
    "fabn - short-term (us)",
    "fabn - extendibles (us)",
    "fabn - putable (us)",
    "fabcp (us)",
})

# ──────────────────────────────────────────────────────────────────────────────
# Date helpers
# ──────────────────────────────────────────────────────────────────────────────

_QUARTER_END: dict[int, tuple[int, int]] = {
    1: (3, 31),
    2: (6, 30),
    3: (9, 30),
    4: (12, 31),
}
_MONTH_TO_QUARTER: dict[int, int] = {
    1: 1, 2: 1, 3: 1,
    4: 2, 5: 2, 6: 2,
    7: 3, 8: 3, 9: 3,
    10: 4, 11: 4, 12: 4,
}


def _parse_date(date_str: str) -> date | None:
    """Parse a date string from the EFA FABS file.

    Handles ISO YYYY-MM-DD and US M/D/YYYY formats.
    """
    s = date_str.strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass
    parts = s.split("/")
    if len(parts) == 3:
        try:
            m, d_val, y = int(parts[0]), int(parts[1]), int(parts[2])
            return date(y, m, d_val)
        except (ValueError, OverflowError):
            pass
    return None


def _date_to_period(d: date) -> Period:
    """Return the CLAIM-WEB Period (quarter) that contains the given date."""
    return Period(f"{d.year}-Q{_MONTH_TO_QUARTER[d.month]}")


def _quarter_end_date(period: Period) -> date:
    """Return the last calendar day of the given quarter."""
    month, day = _QUARTER_END[period.quarter]
    return date(period.year, month, day)


# ──────────────────────────────────────────────────────────────────────────────
# CSV parser
# ──────────────────────────────────────────────────────────────────────────────


def _parse_fabs_csv(
    content: str,
) -> tuple[list[str], dict[date, dict[str, Decimal]]]:
    """Parse the EFA FABS historical text file.

    The file has FRB DDP-style metadata header rows before the data section.
    The data section begins at the row whose first cell is ``Date``
    (case-insensitive). Columns are normalized to lower-case stripped strings.

    Returns
    -------
    columns
        Ordered list of normalized column headers (excluding the Date column).
    daily_data
        Mapping from date → {normalized_column: raw Decimal value in billions}.
        NA / blank / "." cells are omitted from the inner dict.
    """
    reader = csv.reader(io.StringIO(content))
    columns: list[str] = []
    daily_data: dict[date, dict[str, Decimal]] = {}
    header_found = False

    for row in reader:
        if not row:
            continue
        first = row[0].strip()
        if not first:
            continue

        if not header_found:
            if first.lower() == "date":
                columns = [c.strip().lower() for c in row[1:] if c.strip()]
                header_found = True
            continue

        d = _parse_date(first)
        if d is None:
            continue

        row_data: dict[str, Decimal] = {}
        for i, raw_val in enumerate(row[1:]):
            if i >= len(columns):
                break
            col = columns[i]
            if not col:
                continue
            val_str = raw_val.strip()
            if not val_str or val_str.upper() in {"NA", "N.A.", ".", "ND"}:
                continue
            try:
                row_data[col] = Decimal(val_str)
            except InvalidOperation:
                log.debug(
                    "FrbEfaFabsFetcher: unparseable %r for column %r at %s",
                    val_str,
                    col,
                    d,
                )

        if row_data:
            daily_data[d] = row_data

    return columns, daily_data


def _aggregate_to_quarters(
    daily_data: dict[date, dict[str, Decimal]],
) -> dict[Period, dict[str, Decimal]]:
    """Aggregate daily data to quarterly end-of-period snapshots.

    For each quarter represented in the data, selects the last available
    observation on or before the final calendar day of the quarter.
    """
    periods: set[Period] = {_date_to_period(d) for d in daily_data}
    all_dates = sorted(daily_data.keys())
    result: dict[Period, dict[str, Decimal]] = {}

    for period in periods:
        end = _quarter_end_date(period)
        candidates = [
            d for d in all_dates
            if _date_to_period(d) == period and d <= end
        ]
        if not candidates:
            continue
        result[period] = daily_data[candidates[-1]]

    return result


# ──────────────────────────────────────────────────────────────────────────────
# FrbEfaFabsFetcher
# ──────────────────────────────────────────────────────────────────────────────


class FrbEfaFabsFetcher(BaseFetcher):
    """Fetcher for the FRB Enhanced Financial Accounts FABS dataset.

    Source: https://www.federalreserve.gov/releases/efa/efa-project-funding-agreement-backed-securities.htm
    Cadence: daily series, aggregated to quarterly end-of-period snapshots.
    Format: CSV (.txt), values in billions USD.
    Populates: A2 arcs (FABNs), project plan §10.9.
    """

    source_id: str = "frb_efa_fabs"
    cadence: Literal["quarterly"] = "quarterly"

    def __init__(self, data_root: Path | str | None = None) -> None:
        if data_root is None:
            data_root = Path("data/raw") / self.source_id
        self._data_root = Path(data_root)
        self._cache_path = self._data_root / _FILENAME
        self._manifest_path = self._data_root / "_manifest.json"

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def list_available_periods(self) -> list[Period]:
        """Return sorted list of quarters present in the cached FABS data."""
        self._ensure_cached()
        if not self._cache_path.exists():
            return []
        content = self._cache_path.read_text(encoding="utf-8", errors="replace")
        _, daily_data = _parse_fabs_csv(content)
        quarterly = _aggregate_to_quarters(daily_data)
        return sorted(quarterly.keys())

    def acquire(self, period: Period) -> RawDataHandle:
        """Download (or read from cache) the EFA FABS historical file.

        The single historical file contains complete daily data from November
        1994.  ``acquire`` downloads the file subject to the 1-day cache window
        and returns a handle; ``parse`` extracts the target period.
        """
        self._ensure_cached()
        paths = [self._cache_path] if self._cache_path.exists() else []
        return RawDataHandle.from_paths(self.source_id, period, paths)

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse the EFA FABS file and return ArcFacts for ``handle.period``.

        Daily values are aggregated to quarterly end-of-period snapshots.
        Only US-issuer columns listed in ``_COLUMN_MAP`` are emitted; Non-US,
        Total, and unrecognised columns are skipped.
        """
        target_period = handle.period
        facts: list[ArcFact] = []

        if not handle.paths:
            log.warning("FrbEfaFabsFetcher: no paths in handle for %s", target_period)
            return facts

        path = handle.paths[0]
        content = path.read_text(encoding="utf-8", errors="replace")
        sha256 = handle.sha256_by_path.get(str(path), "0" * 64)

        _, daily_data = _parse_fabs_csv(content)
        quarterly = _aggregate_to_quarters(daily_data)

        period_data = quarterly.get(target_period)
        if period_data is None:
            log.debug("FrbEfaFabsFetcher: no data for period %s", target_period)
            return facts

        for col, raw_val in period_data.items():
            if col not in _COLUMN_MAP:
                continue
            arc_class, src, tgt = _COLUMN_MAP[col]
            amount_mm = (raw_val * _BILLIONS_TO_MILLIONS).normalize()
            facts.append(
                ArcFact(
                    period=target_period,
                    source_node_id=src,
                    target_node_id=tgt,
                    instrument_class=arc_class,
                    dollar_amount_millions=amount_mm,
                    measurement_basis="stock_eop",
                    data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
                    provenance_source=self.source_id,
                    provenance_url=_EFA_FABS_URL,
                    provenance_filing=f"EFA_FABS_{target_period}",
                    provenance_page=None,
                    provenance_field=col,
                    sha256_of_source=sha256,
                )
            )

        return facts

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Sanity-check the parsed EFA FABS ArcFacts.

        Checks:
        1. At least one ArcFact was emitted.
        2. All amounts are non-negative.
        3. Total US FABS outstanding exceeds the plausibility floor.
        4. Sub-component sum within 30% of total (FABR explains gap if present).
        """
        period = facts[0].period if facts else None
        report = ValidationReport(
            source_id=self.source_id,
            period=period or Period("2000-Q1"),
        )

        if not facts:
            report.error("NO_FACTS", "EFA FABS parse produced zero ArcFacts")
            return report

        for f in facts:
            if f.dollar_amount_millions < Decimal("0"):
                report.warning(
                    "NEGATIVE_AMOUNT",
                    f"Negative amount {f.dollar_amount_millions} for "
                    f"{f.provenance_field} in {f.period}",
                )

        total_fact = next(
            (f for f in facts if f.provenance_field == _TOTAL_COLUMN), None
        )
        if total_fact is not None and total_fact.dollar_amount_millions < _MIN_FABS_TOTAL_MM:
            report.error(
                "FABS_TOTAL_IMPLAUSIBLE",
                f"Total US FABS outstanding {total_fact.dollar_amount_millions} MM "
                f"is below plausibility floor {_MIN_FABS_TOTAL_MM} MM",
            )

        if total_fact is not None and total_fact.dollar_amount_millions > Decimal("0"):
            # Deduplicate by (source, target) to handle alternative column names
            # for the same series (extendibles vs putable both → efa:xfabs_holders).
            seen: set[tuple[str, str]] = set()
            component_sum = Decimal("0")
            for f in facts:
                if f.provenance_field in _COMPONENT_COLUMNS:
                    key = (f.source_node_id, f.target_node_id)
                    if key not in seen:
                        component_sum += f.dollar_amount_millions
                        seen.add(key)
            if component_sum > Decimal("0"):
                pct_diff = (
                    abs(component_sum - total_fact.dollar_amount_millions)
                    / total_fact.dollar_amount_millions
                )
                if pct_diff > _COMPONENT_SUM_TOLERANCE:
                    report.warning(
                        "COMPONENTS_DONT_SUM_TO_TOTAL",
                        f"Component sum {component_sum} MM differs from total "
                        f"{total_fact.dollar_amount_millions} MM by {pct_diff:.1%} "
                        f"(>{_COMPONENT_SUM_TOLERANCE:.0%}); FABR may explain gap",
                    )

        return report

    # ──────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────

    def _ensure_cached(self) -> None:
        """Download the EFA FABS file if absent or stale."""
        if self._is_cache_fresh():
            return
        self._download()

    def _is_cache_fresh(self) -> bool:
        if not self._manifest_path.exists() or not self._cache_path.exists():
            return False
        try:
            manifest = json.loads(self._manifest_path.read_text())
            fetched_at = datetime.fromisoformat(manifest["fetched_at"])
        except (KeyError, ValueError, json.JSONDecodeError):
            return False
        return datetime.utcnow() - fetched_at <= timedelta(days=_CACHE_LIFETIME_DAYS)

    def _download(self) -> None:
        """Download the EFA FABS historical file from the FRB."""
        self._data_root.mkdir(parents=True, exist_ok=True)
        log.info("Downloading EFA FABS data from %s", _EFA_FABS_URL)
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            resp = client.get(_EFA_FABS_URL)
            resp.raise_for_status()
            self._cache_path.write_bytes(resp.content)
            log.info(
                "Cached EFA FABS → %s (%d bytes)",
                self._cache_path,
                len(resp.content),
            )
        manifest = {"fetched_at": datetime.utcnow().isoformat(), "url": _EFA_FABS_URL}
        self._manifest_path.write_text(json.dumps(manifest, indent=2))
