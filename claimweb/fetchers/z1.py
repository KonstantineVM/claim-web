"""FRB Z.1 Financial Accounts of the United States fetcher (project plan §10.1).

Source: https://www.federalreserve.gov/releases/z1/ (via FRB Data Download Program)
Cadence: quarterly, ~75 days after end-of-quarter.
Format: CSV files (one per table), downloaded from the FRB Data Download Program
        (``layout=seriescolumn``).
Populates: sectoral aggregate constraints (Law 3) for CLAIM-WEB reconstruction.

Tables fetched:
  L.116 — U.S. life insurance companies (assets and liabilities, by instrument)
  L.121 — Money market funds (assets and liabilities)
  L.207 — Open market paper (commercial paper, including FABCP)
  L.208 — Debt securities (FABN and similar)
  L.211 — Agency- and GSE-backed securities (FHLB consolidated obligations, agency MBS)
  L.226 — Repurchase agreements
  L.227 — Reverse repurchase agreements

Arc direction convention (project plan §1):
  source_node_id = issuer of the obligation
  target_node_id = holder of the claim

  For asset-side series (sector S *holds* the instrument):
    source = the issuing sector  →  target = sector S (the holder)
  For liability-side series (sector S *issues* the obligation):
    source = sector S (the borrower/issuer)  →  target = z1:all_holders
    (or the known counterparty sector if Z.1 discloses it)

Dollar amounts: FRB DDP serves Z.1 levels in Millions of USD.  The "Multiplier"
metadata row in each CSV is parsed and applied; Billions and Thousands are
converted to Millions before the ArcFact is emitted.

Data quality flag: DIRECT_MEASURED — Z.1 is the Federal Reserve's official
financial accounts statistical release.

Measurement basis: "stock_eop" — all L-table series are end-of-period stocks.
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

# FRB Data Download Program URL for Z.1 (all historical periods, per-table CSV)
_DDP_URL_TEMPLATE = (
    "https://www.federalreserve.gov/datadownload/Output.aspx"
    "?rel=Z1&series={table}&lastobs=&startdate=&enddate="
    "&filetype=csv&label=include&layout=seriescolumn"
)

# Z.1 tables we acquire (project plan §10.1)
_TARGET_TABLES: list[str] = ["L116", "L121", "L207", "L208", "L211", "L226", "L227"]

# Bundle is re-downloaded when the cached copy is older than this many days.
# Z.1 is released quarterly (~75 days after EoQ); 30 days gives a comfortable
# refresh window without excessive re-downloading.
_CACHE_LIFETIME_DAYS = 30

# Plausibility floor for life insurer total financial assets (millions)
_MIN_LIC_TOTAL_ASSETS_MM = Decimal("500_000")   # $500 billion

# ──────────────────────────────────────────────────────────────────────────────
# Series → ArcFact mapping
# ──────────────────────────────────────────────────────────────────────────────

# Arc direction:
#   (arc_class, source_node_id, target_node_id)
#
# Series IDs follow the FRED Financial Accounts coding convention:
#   FL = Financial accounts, level series (stock, end of period)
#   {3-digit sector code}{5-digit instrument code}
#   .Q = quarterly frequency
#
# Sector codes used here:
#   543 = Private life insurance companies
#   634 = Money market mutual funds
#   893/894/895 = All sectors aggregate
#   903 = Federal Home Loan Banks (GSE sub-sector)

_SERIES_MAP: dict[str, tuple[ArcClass, str, str]] = {
    # ── L.116 Life insurance companies ──────────────────────────────────────
    # Total financial assets (sector-wide asset total; Law 3 row-sum constraint)
    "FL543069905.Q": (ArcClass.A12, "z1:aggregate", "sector:life_insurance_companies"),
    # Checkable deposits + currency (asset; held at banks → A9)
    "FL543030005.Q": (ArcClass.A9, "sector:depository_institutions", "sector:life_insurance_companies"),
    # Money market fund shares (asset; life insurer holds MMF shares → A8)
    "FL543035005.Q": (ArcClass.A8, "sector:money_market_funds", "sector:life_insurance_companies"),
    # Agency- and GSE-backed securities (asset; includes FHLB COs, agency MBS → A10)
    "FL543054003.Q": (ArcClass.A10, "sector:gse", "sector:life_insurance_companies"),
    # Corporate and foreign bonds (asset → A12)
    "FL543063005.Q": (ArcClass.A12, "sector:corporate_bond_issuers", "sector:life_insurance_companies"),
    # Commercial paper (asset; includes FABCP → A2)
    "FL543064005.Q": (ArcClass.A2, "sector:fabn_spv", "sector:life_insurance_companies"),
    # Total liabilities (sector-wide liability total; Law 3 column-sum constraint)
    "FL543093005.Q": (ArcClass.A12, "sector:life_insurance_companies", "z1:aggregate"),
    # FHLB advances (liability; life insurer borrows from FHLB → A3)
    "FL543050005.Q": (ArcClass.A3, "sector:life_insurance_companies", "sector:fhlb"),
    # Repos (liability; life insurer sells securities under repo → A4)
    "FL543031005.Q": (ArcClass.A4, "sector:life_insurance_companies", "sector:repo_dealers"),
    # Reverse repos (asset; life insurer buys securities under repo → A4)
    "FL543025005.Q": (ArcClass.A4, "sector:repo_dealers", "sector:life_insurance_companies"),

    # ── L.121 Money market funds ─────────────────────────────────────────────
    # Total financial assets of MMF sector
    "FL634069905.Q": (ArcClass.A12, "z1:aggregate", "sector:money_market_funds"),
    # Treasury securities held by MMFs (asset → A10)
    "FL634061105.Q": (ArcClass.A10, "sector:federal_government", "sector:money_market_funds"),
    # Commercial paper held by MMFs (asset; FABCP major component → A2)
    "FL634064005.Q": (ArcClass.A2, "sector:fabn_spv", "sector:money_market_funds"),
    # Repos held by MMFs (asset; MMF lends cash via repo → A4)
    "FL634031005.Q": (ArcClass.A4, "sector:repo_dealers", "sector:money_market_funds"),
    # MMF shares outstanding (liability of MMF sector → A8)
    "FL634090005.Q": (ArcClass.A8, "sector:money_market_funds", "z1:all_holders"),

    # ── L.207 Open market paper ──────────────────────────────────────────────
    # Total open market paper (CP + FABCP) outstanding; all-sector aggregate
    "FL894064905.Q": (ArcClass.A2, "sector:fabn_spv", "z1:all_holders"),

    # ── L.208 Debt securities ────────────────────────────────────────────────
    # Total corporate and foreign bonds outstanding; all-sector aggregate
    "FL894022705.Q": (ArcClass.A12, "sector:corporate_bond_issuers", "z1:all_holders"),

    # ── L.211 Agency- and GSE-backed securities ──────────────────────────────
    # Total agency/GSE securities outstanding (includes FHLB consolidated obligations)
    "FL895061005.Q": (ArcClass.A10, "sector:gse", "z1:all_holders"),
    # MMF holdings of agency/GSE (short-duration agency notes held by prime MMFs)
    "FL634062005.Q": (ArcClass.A10, "sector:gse", "sector:money_market_funds"),

    # ── L.226 Repurchase agreements ──────────────────────────────────────────
    # Total repos outstanding (liabilities of dealers); all-sector aggregate
    "FL894031905.Q": (ArcClass.A4, "sector:repo_dealers", "z1:all_holders"),

    # ── L.227 Reverse repurchase agreements ──────────────────────────────────
    # Total reverse repos outstanding; all-sector aggregate
    "FL894025005.Q": (ArcClass.A4, "sector:repo_dealers", "z1:all_holders"),
}

# Series used as the life-insurer total-assets plausibility check
_LIC_TOTAL_ASSETS_SERIES = "FL543069905.Q"

# ──────────────────────────────────────────────────────────────────────────────
# Date → Period helpers
# ──────────────────────────────────────────────────────────────────────────────

_QUARTER_FROM_END_MONTH: dict[int, int] = {3: 1, 6: 2, 9: 3, 12: 4}
_QUARTER_FROM_START_MONTH: dict[int, int] = {1: 1, 4: 2, 7: 3, 10: 4}


def _date_str_to_period(date_str: str) -> Period | None:
    """Convert a Z.1 DDP date string to a Period.

    Handles:
    - ISO dates (YYYY-MM-DD): quarter inferred from month
    - "YYYY:QN" notation used by some FRED variants
    - "YYYY-QN" notation (already Period-compatible)
    """
    s = date_str.strip().strip('"')
    if not s:
        return None

    # "YYYY:QN" → "YYYY-QN"
    if len(s) == 7 and s[4] == ":" and s[5] == "Q":
        s = s[:4] + "-" + s[5:]

    # "YYYY-QN" → direct Period construction
    if len(s) == 7 and s[4] == "-" and s[5] == "Q":
        return _safe_period(s)

    # ISO date YYYY-MM-DD
    try:
        dt = date.fromisoformat(s)
    except ValueError:
        return None

    month = dt.month
    year = dt.year
    if month in _QUARTER_FROM_END_MONTH:
        return _safe_period(f"{year}-Q{_QUARTER_FROM_END_MONTH[month]}")
    if month in _QUARTER_FROM_START_MONTH:
        return _safe_period(f"{year}-Q{_QUARTER_FROM_START_MONTH[month]}")
    log.debug("Unexpected mid-quarter date in Z.1: %s", date_str)
    return None


def _safe_period(s: str) -> Period | None:
    try:
        return Period(s)
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Multiplier helper
# ──────────────────────────────────────────────────────────────────────────────

_MULTIPLIER_TO_FACTOR: dict[str, Decimal] = {
    "millions": Decimal("1"),
    "billions": Decimal("1000"),
    "thousands": Decimal("0.001"),
}


def _multiplier_factor(label: str) -> Decimal:
    """Return the factor to convert the raw series value to millions of USD."""
    return _MULTIPLIER_TO_FACTOR.get(label.lower().strip(), Decimal("1"))


# ──────────────────────────────────────────────────────────────────────────────
# DDP CSV parser
# ──────────────────────────────────────────────────────────────────────────────

def _parse_ddp_csv(
    content: str,
) -> tuple[list[str], dict[str, Decimal], dict[Period, dict[str, Decimal]]]:
    """Parse an FRB DDP CSV file with ``layout=seriescolumn``.

    The DDP format has a metadata preamble (rows whose first cell is a label
    such as "Unique Identifier", "Series Description", "Multiplier", "Currency")
    followed by an empty line, then a data section starting with a header row
    whose first cell is "Date" (case-insensitive), followed by one row per
    quarter.

    Returns
    -------
    series_ids
        Ordered list of FRED series identifiers found in the preamble or the
        data-section header.
    factors
        Mapping from series_id to the Decimal factor needed to convert the raw
        value to millions of USD.
    data
        Mapping from Period to {series_id: Decimal value}.
    """
    reader = csv.reader(io.StringIO(content))

    series_ids: list[str] = []
    raw_multipliers: dict[str, str] = {}
    data_header: list[str] = []
    data: dict[Period, dict[str, Decimal]] = {}
    in_data = False
    multiplier_found = False

    for row in reader:
        if not row:
            continue

        first = row[0].strip().strip('"')

        if not in_data:
            fl = first.lower()

            if fl == "unique identifier":
                ids = [c.strip().strip('"') for c in row[1:]]
                ids = [x for x in ids if x]
                if ids:
                    series_ids = ids

            elif fl == "multiplier" and not multiplier_found:
                multiplier_found = True
                for i, mult in enumerate(row[1:]):
                    if i < len(series_ids):
                        raw_multipliers[series_ids[i]] = mult.strip().strip('"')

            elif fl == "date":
                in_data = True
                data_header = [c.strip().strip('"') for c in row[1:]]
                if not series_ids:
                    series_ids = [x for x in data_header if x]

        else:
            if not first:
                continue
            period = _date_str_to_period(first)
            if period is None:
                continue

            row_data: dict[str, Decimal] = {}
            for i, raw_val in enumerate(row[1:]):
                if i >= len(data_header):
                    break
                sid = data_header[i]
                if not sid:
                    continue
                val_str = raw_val.strip().strip('"')
                if not val_str or val_str.upper() in {"NA", "N.A.", ".", "ND", ""}:
                    continue
                try:
                    row_data[sid] = Decimal(val_str)
                except InvalidOperation:
                    log.debug("Unparseable value %r for %s at %s", val_str, sid, period)

            if row_data:
                data[period] = row_data

    factors: dict[str, Decimal] = {
        sid: _multiplier_factor(raw_multipliers.get(sid, "Millions"))
        for sid in series_ids
    }
    return series_ids, factors, data


# ──────────────────────────────────────────────────────────────────────────────
# Z1Fetcher
# ──────────────────────────────────────────────────────────────────────────────


class Z1Fetcher(BaseFetcher):
    """Fetcher for FRB Z.1 Financial Accounts of the United States.

    Source: https://www.federalreserve.gov/releases/z1/
    Cadence: quarterly, ~75 days after end-of-quarter.
    Format: CSV files via the FRB Data Download Program (layout=seriescolumn).
    Populates: Law 3 sectoral constraints (project plan §10.1).
    """

    source_id: str = "z1"
    cadence: Literal["quarterly"] = "quarterly"

    def __init__(self, data_root: Path | str | None = None) -> None:
        if data_root is None:
            data_root = Path("data/raw") / self.source_id
        self._data_root = Path(data_root)
        self._bundle_dir = self._data_root / "bundle"
        self._manifest_path = self._bundle_dir / "_manifest.json"

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def list_available_periods(self) -> list[Period]:
        """Return sorted list of periods present in the cached Z.1 bundle.

        Downloads the bundle on first call if not already cached.
        """
        self._ensure_bundle()
        csv_path = self._bundle_dir / "L116.csv"
        if not csv_path.exists():
            return []
        content = csv_path.read_text(encoding="utf-8", errors="replace")
        _, _, data = _parse_ddp_csv(content)
        return sorted(data.keys())

    def acquire(self, period: Period) -> RawDataHandle:
        """Download (or read from cache) the Z.1 table CSV bundle.

        The Z.1 release contains complete historical data for all periods in a
        single download per table.  ``acquire`` therefore downloads all seven
        tables unconditionally (subject to the 30-day cache window) and returns
        a handle whose ``period`` field identifies which quarter should be
        extracted by ``parse``.

        Cached files live under ``data/raw/z1/bundle/``.
        """
        self._ensure_bundle()
        paths = [self._bundle_dir / f"{t}.csv" for t in _TARGET_TABLES]
        paths = [p for p in paths if p.exists()]
        return RawDataHandle.from_paths(self.source_id, period, paths)

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse the Z.1 bundle and return ArcFacts for ``handle.period``.

        For each table CSV in the handle, finds the row matching ``handle.period``
        and emits one ArcFact per mapped series.  Unmapped series are logged at
        DEBUG level and skipped.
        """
        target_period = handle.period
        facts: list[ArcFact] = []

        for path in handle.paths:
            table = path.stem  # e.g. "L116"
            content = path.read_text(encoding="utf-8", errors="replace")
            url = _DDP_URL_TEMPLATE.format(table=table)
            sha256 = handle.sha256_by_path.get(str(path), "0" * 64)

            series_ids, factors, data = _parse_ddp_csv(content)

            period_data = data.get(target_period)
            if period_data is None:
                log.debug("Z.1 %s: no data for period %s", table, target_period)
                continue

            for sid in series_ids:
                if sid not in _SERIES_MAP:
                    log.debug("Z.1 %s: unmapped series %s — skipping", table, sid)
                    continue

                raw_val = period_data.get(sid)
                if raw_val is None:
                    continue

                factor = factors.get(sid, Decimal("1"))
                amount_mm = (raw_val * factor).normalize()

                arc_class, src, tgt = _SERIES_MAP[sid]
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
                        provenance_url=url,
                        provenance_filing=f"Z1_{target_period}_{table}",
                        provenance_page=None,
                        provenance_field=sid,
                        sha256_of_source=sha256,
                    )
                )

        return facts

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Sanity-check the parsed Z.1 ArcFacts.

        Checks performed:
        1. At least one ArcFact was emitted (data parse was not empty).
        2. Life insurer total financial assets exceed the plausibility floor.
        3. All emitted ArcFacts have non-negative dollar amounts.
        """
        period = facts[0].period if facts else None
        report = ValidationReport(
            source_id=self.source_id,
            period=period or Period("2000-Q1"),
        )

        if not facts:
            report.error("NO_FACTS", "Z.1 parse produced zero ArcFacts")
            return report

        # Non-negative amounts
        for f in facts:
            if f.dollar_amount_millions < Decimal("0"):
                report.warning(
                    "NEGATIVE_AMOUNT",
                    f"Negative amount {f.dollar_amount_millions} for series "
                    f"{f.provenance_field} in {f.period}",
                )

        # Life insurer total assets plausibility
        lic_total = next(
            (
                f.dollar_amount_millions
                for f in facts
                if f.provenance_field == _LIC_TOTAL_ASSETS_SERIES
            ),
            None,
        )
        if lic_total is not None and lic_total < _MIN_LIC_TOTAL_ASSETS_MM:
            report.error(
                "LIC_TOTAL_ASSETS_IMPLAUSIBLE",
                f"Life insurer total financial assets {lic_total} MM is below "
                f"plausibility floor {_MIN_LIC_TOTAL_ASSETS_MM} MM",
            )

        return report

    # ──────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────

    def _ensure_bundle(self) -> None:
        """Download the Z.1 table CSVs if absent or stale."""
        if self._is_bundle_fresh():
            return
        self._download_bundle()

    def _is_bundle_fresh(self) -> bool:
        """Return True if all table CSVs exist and the manifest is recent."""
        if not self._manifest_path.exists():
            return False
        try:
            manifest = json.loads(self._manifest_path.read_text())
            fetched_at = datetime.fromisoformat(manifest["fetched_at"])
        except (KeyError, ValueError, json.JSONDecodeError):
            return False
        if datetime.utcnow() - fetched_at > timedelta(days=_CACHE_LIFETIME_DAYS):
            return False
        return all((self._bundle_dir / f"{t}.csv").exists() for t in _TARGET_TABLES)

    def _download_bundle(self) -> None:
        """Download all target tables from the FRB DDP and cache them."""
        self._bundle_dir.mkdir(parents=True, exist_ok=True)

        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            for table in _TARGET_TABLES:
                url = _DDP_URL_TEMPLATE.format(table=table)
                log.info("Downloading Z.1 %s from %s", table, url)
                resp = client.get(url)
                resp.raise_for_status()
                dest = self._bundle_dir / f"{table}.csv"
                dest.write_bytes(resp.content)
                log.info("Cached %s → %s (%d bytes)", table, dest, len(resp.content))

        manifest = {"fetched_at": datetime.utcnow().isoformat(), "tables": _TARGET_TABLES}
        self._manifest_path.write_text(json.dumps(manifest, indent=2))
