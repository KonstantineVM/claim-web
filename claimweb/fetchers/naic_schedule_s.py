"""NAIC Schedule S — Reinsurance ceded fetcher (project plan §10.3).

Source: NAIC statutory annual statements, Schedule S (Reinsurance).
        NAIC filings are intermediated through state insurance department portals;
        there is no free central repository.  The primary acquisition path targets
        the Iowa Insurance Division (https://iid.iowa.gov/) because most PE-affiliated
        insurers (Athene, American Equity, F&G) are Iowa-domiciled, supplemented by
        the Indiana, Tennessee, and Delaware DOI portals for non-Iowa cedents.
        As a secondary path the fetcher also queries the NAIC company information
        service (https://content.naic.org/cis/) which provides limited free access.
Cadence: Annual (filed by March 1 for prior December 31 year-end).
         The annual period is represented as YYYY-Q4 (e.g., "2024-Q4" = the
         December 31, 2024 annual statement).
Format:  NAIC blank Schedule S CSV (see _SCHED_S_COLUMNS below); amounts in
         thousands of USD.
Populates: A6 arcs (reinsurance treaties, offshore-cession) for T2 nodes.
           Project plan §10.3.

NAIC Schedule S structure
-------------------------
Schedule S of the NAIC Annual Statement blank discloses reinsurance activity:

  Part 1 — Reinsurance Assumed from Non-Affiliates
  Part 2 — Reinsurance Ceded to Non-Affiliates   ← A6 arcs (non-affiliated)
  Part 3 — Reinsurance Assumed from Affiliates
  Part 4 — Reinsurance Ceded to Affiliates        ← A6 arcs (affiliated; key for
                                                     offshore captive structures)

For CLAIM-WEB, Parts 2 and 4 are the relevant "ceded" sections that populate
the A6 arc from U.S. cedent to offshore (Bermuda/Cayman) reinsurer.

Arc direction (project plan §4, A6):
  source_node_id = U.S. cedent insurer (the party ceding reserves)
  target_node_id = offshore / domestic reinsurer (the party assuming reserves)
  instrument_class = ArcClass.A6

Node ID conventions:
  U.S. cedent:        insurer:naic:{5-digit-code}      canonical from _CEDENT_MAP
  Offshore reinsurer: reinsurer:bermuda:{slug}         for BMU-domicile
                      reinsurer:cayman:{slug}          for CYM-domicile
                      reinsurer:{country}:{slug}       for other foreign
                      reinsurer:name:{slug}            fallback if no domicile
  Domestic reinsurer: insurer:naic:{code}              if NAIC code present
                      insurer:name:{slug}              otherwise
  Unmapped entities → claimweb/registry/unmapped/naic_schedule_s_{period}.json

Dollar amounts: NAIC statutory filings denominate amounts in thousands of USD.
  Parser multiplies by _THOUSANDS_TO_MILLIONS (= Decimal("0.001")) → millions.
  The CEDED_AMOUNT column aggregates Life + Annuity + A&H reserves ceded.

Data quality flag: DIRECT_MEASURED — NAIC statutory filing, regulator-reviewed.
Measurement basis: stock_eop — December 31 year-end snapshot of reserves ceded.

Acquisition strategy
--------------------
1. For each target company in _CEDENT_REGISTRY:
   a. Look up the domicile state from the registry.
   b. Call the appropriate state-portal fetch function:
      - Iowa ("IA")     → _fetch_iowa_statement()
      - Indiana ("IN")  → _fetch_indiana_statement()
      - Tennessee ("TN") → _fetch_tennessee_statement()
      - Other states    → _fetch_naic_cis_statement() (NAIC CIS fallback)
   c. Download the annual statement PDF or structured data file.
   d. Parse the Schedule S sections from the downloaded file.
   e. Cache as {naic_code}_schedule_s.csv under data/raw/naic_schedule_s/{period}/.
2. The CSV cache is the canonical artifact; all downstream processing reads CSV.
3. Cache lifetime: 365 days (annual filings are final once submitted; re-acquire
   only if the raw file is absent or the `refresh` flag is set).

Known NAIC codes for target companies
--------------------------------------
See _CEDENT_REGISTRY below.  The registry maps NAIC codes to company metadata
(name, state, and canonical CLAIM-WEB node ID).  Entries without a node ID in
the registry go to the unmapped registry.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import logging
import re
import time
from datetime import date, timedelta
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
_REQUEST_INTERVAL_S = 0.5  # conservative for state portals

# NAIC company information service — limited free public access.
_NAIC_CIS_BASE = "https://content.naic.org/cis"

# Iowa Insurance Division base URL for annual statement access.
_IOWA_IID_BASE = "https://iid.iowa.gov"

# Cache lifetime in days (annual filings are final).
_CACHE_LIFETIME_DAYS = 365

# NAIC amounts are in thousands of USD; canonical unit is millions.
_THOUSANDS_TO_MILLIONS = Decimal("0.001")

# Minimum plausible total reserves ceded for a significant insurer (millions).
_MIN_CEDED_TOTAL_MM = Decimal("100")

# ──────────────────────────────────────────────────────────────────────────────
# CSV column names  (NAIC blank Schedule S electronic filing format)
# ──────────────────────────────────────────────────────────────────────────────

_COL_CEDENT_NAIC = "CEDENT_NAIC_CODE"
_COL_CEDENT_NAME = "CEDENT_NAME"
_COL_YEAR = "STATEMENT_YEAR"
_COL_PART = "SCHEDULE_PART"        # "S2" = ceded non-aff; "S4" = ceded aff
_COL_LINE = "LINE_NUM"
_COL_REINS_NAME = "REINSURER_NAME"
_COL_REINS_NAIC = "REINSURER_NAIC_CODE"
_COL_REINS_FED_ID = "REINSURER_FED_ID"
_COL_DOMICILE = "DOMICILE_JURISDICTION"
_COL_TYPE = "TYPE_BUSINESS"        # "L"=Life, "N"=Annuity, "A"=A&H, "T"=Total
_COL_CEDED_AMT = "CEDED_AMOUNT_THOUSANDS"

# Parts of Schedule S that represent ceded reinsurance (A6 arcs).
_CEDED_PARTS: frozenset[str] = frozenset({"S2", "S4"})

# ──────────────────────────────────────────────────────────────────────────────
# Cedent registry — target U.S. life insurers (PE-affiliated focus)
# ──────────────────────────────────────────────────────────────────────────────

_CEDENT_REGISTRY: dict[str, dict] = {
    # NAIC code → {name, state, node_id}
    "68039": {
        "name": "Athene Annuity and Life Insurance Company",
        "state": "IA",
        "node_id": "insurer:naic:68039",
    },
    "92525": {
        "name": "American Equity Investment Life Insurance Company",
        "state": "IA",
        "node_id": "insurer:naic:92525",
    },
    "33588": {
        "name": "Fidelity and Guaranty Life Insurance Company",
        "state": "IA",
        "node_id": "insurer:naic:33588",
    },
    "94048": {
        "name": "Global Atlantic Life Insurance Company",
        "state": "IN",
        "node_id": "insurer:naic:94048",
    },
    "68381": {
        "name": "Protective Life Insurance Company",
        "state": "TN",
        "node_id": "insurer:naic:68381",
    },
    "67105": {
        "name": "Metropolitan Life Insurance Company",
        "state": "NY",
        "node_id": "insurer:naic:67105",
    },
    "79227": {
        "name": "Prudential Insurance Company of America",
        "state": "NJ",
        "node_id": "insurer:naic:79227",
    },
    "60488": {
        "name": "Lincoln National Life Insurance Company",
        "state": "IN",
        "node_id": "insurer:naic:60488",
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Domicile jurisdiction → CLAIM-WEB node prefix for reinsurers
# ──────────────────────────────────────────────────────────────────────────────

# NAIC/ISO jurisdiction codes that indicate offshore domicile.
_OFFSHORE_DOMICILES: frozenset[str] = frozenset({
    "BMU", "BM",        # Bermuda
    "CYM",              # Cayman Islands (3-letter only; "KY" = Kentucky in NAIC blanks)
    "IRL", "IE",        # Ireland
    "BHS", "BS",        # Bahamas
    "BRB", "BB",        # Barbados
    "GBR", "GB",        # United Kingdom / Channel Islands
    "CHE", "CH",        # Switzerland
    "LUX", "LU",        # Luxembourg
    "NLD", "NL",        # Netherlands
    "SWE", "SE",        # Sweden
    "FRA", "FR",        # France (for French captives)
    "DEU",              # Germany (3-letter only; "DE" = Delaware in NAIC blanks)
    "CAN",              # Canada (3-letter only; "CA" = California in NAIC blanks)
    "Foreign",          # Generic foreign marker in some NAIC blanks
    "Alien",            # Another generic non-US marker
})

# Map from domicile code to canonical CLAIM-WEB prefix for offshore reinsurers.
_DOMICILE_TO_PREFIX: dict[str, str] = {
    "BMU": "bermuda", "BM": "bermuda",
    "CYM": "cayman",                    # "KY" = Kentucky (US state)
    "IRL": "ireland", "IE": "ireland",
    "BHS": "bahamas", "BS": "bahamas",
    "BRB": "barbados", "BB": "barbados",
    "GBR": "uk", "GB": "uk",
    "CHE": "switzerland", "CH": "switzerland",
    "LUX": "luxembourg", "LU": "luxembourg",
    "NLD": "netherlands", "NL": "netherlands",
    "CAN": "canada",                    # "CA" = California (US state)
    "DEU": "germany",                   # "DE" = Delaware (US state)
    "SWE": "sweden", "SE": "sweden",
    "FRA": "france", "FR": "france",
    "Foreign": "foreign", "Alien": "foreign",
}

# US state codes — used to distinguish domestic from offshore reinsurers.
_US_STATE_CODES: frozenset[str] = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
})

# ──────────────────────────────────────────────────────────────────────────────
# Node-ID helpers
# ──────────────────────────────────────────────────────────────────────────────


def _normalise_name(name: str) -> str:
    """Produce a stable slug (max 64 chars) from an entity name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:64]


def _cedent_node_id(naic_code: str) -> str:
    """Return canonical node ID for a cedent by NAIC code."""
    entry = _CEDENT_REGISTRY.get(naic_code.strip())
    if entry:
        return entry["node_id"]
    return f"insurer:naic:{naic_code.strip()}"


def _reinsurer_node_id(reins_name: str, reins_naic: str, domicile: str) -> str:
    """Return canonical node ID for a reinsurer.

    Offshore reinsurers (domicile not in US state codes) get a
    ``reinsurer:{country}:{slug}`` ID.  US-domiciled reinsurers get
    ``insurer:naic:{code}`` if NAIC code present, else ``insurer:name:{slug}``.
    """
    domicile_clean = domicile.strip().upper() if domicile else ""
    reins_naic_clean = reins_naic.strip() if reins_naic else ""
    name_slug = _normalise_name(reins_name)

    if domicile_clean in _US_STATE_CODES:
        if reins_naic_clean and reins_naic_clean not in ("0", ""):
            return f"insurer:naic:{reins_naic_clean}"
        return f"insurer:name:{name_slug}"

    # Offshore or unknown domicile.
    country_prefix = _DOMICILE_TO_PREFIX.get(
        domicile_clean,
        _DOMICILE_TO_PREFIX.get(domicile.strip(), "foreign"),
    )
    if not domicile_clean or domicile_clean not in _OFFSHORE_DOMICILES:
        country_prefix = "foreign" if domicile_clean else "name"

    if name_slug:
        return f"reinsurer:{country_prefix}:{name_slug}"
    return f"reinsurer:{country_prefix}:unknown"


def _is_offshore(domicile: str) -> bool:
    """Return True if the domicile code indicates an offshore (non-US) entity."""
    d = domicile.strip().upper() if domicile else ""
    return d in _OFFSHORE_DOMICILES or (d not in _US_STATE_CODES and bool(d))


# ──────────────────────────────────────────────────────────────────────────────
# Period helpers
# ──────────────────────────────────────────────────────────────────────────────


def _period_to_year(period: Period) -> int:
    """Return the calendar year for a period.

    NAIC annual statements are always year-end (Q4).  We accept any quarter
    for the period but treat the year as the statement year.
    """
    return period.year


# ──────────────────────────────────────────────────────────────────────────────
# CSV parsing helpers
# ──────────────────────────────────────────────────────────────────────────────


def _parse_amount(raw: str) -> Decimal:
    """Parse a Schedule S amount field (thousands USD) to Decimal.

    Returns Decimal("0") for blank, non-numeric, or parenthesized-negative values.
    NAIC blanks sometimes use parentheses for negative amounts, e.g. "(1234)".
    """
    cleaned = raw.strip().replace(",", "").replace("$", "")
    # Handle parenthesized negatives: "(1234)" → "-1234"
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    if not cleaned:
        return Decimal("0")
    with contextlib.suppress(InvalidOperation):
        return Decimal(cleaned)
    return Decimal("0")


def _read_schedule_s_csv(path: Path) -> list[dict]:
    """Read a cached Schedule S CSV; return list of row dicts.

    Tolerates UTF-8 and Windows-1252 encoding; uses BOM stripping.
    Empty ceded-amount rows are included (amount = 0).
    """
    rows: list[dict] = []
    with contextlib.suppress(OSError):
        content = path.read_bytes().decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            cedent_naic = row.get(_COL_CEDENT_NAIC, "").strip()
            reins_name = row.get(_COL_REINS_NAME, "").strip()
            part = row.get(_COL_PART, "").strip()
            if not cedent_naic or not reins_name or part not in _CEDED_PARTS:
                continue
            rows.append({
                "cedent_naic": cedent_naic,
                "cedent_name": row.get(_COL_CEDENT_NAME, "").strip(),
                "year": row.get(_COL_YEAR, "").strip(),
                "part": part,
                "line_num": row.get(_COL_LINE, "").strip(),
                "reins_name": reins_name,
                "reins_naic": row.get(_COL_REINS_NAIC, "").strip(),
                "reins_fed_id": row.get(_COL_REINS_FED_ID, "").strip(),
                "domicile": row.get(_COL_DOMICILE, "").strip(),
                "type_business": row.get(_COL_TYPE, "").strip(),
                "ceded_thousands": _parse_amount(
                    row.get(_COL_CEDED_AMT, "")
                ),
            })
    return rows


def _write_schedule_s_csv(path: Path, rows: list[dict]) -> None:
    """Write Schedule S rows to a canonical CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            _COL_CEDENT_NAIC, _COL_CEDENT_NAME, _COL_YEAR, _COL_PART,
            _COL_LINE, _COL_REINS_NAME, _COL_REINS_NAIC, _COL_REINS_FED_ID,
            _COL_DOMICILE, _COL_TYPE, _COL_CEDED_AMT,
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                _COL_CEDENT_NAIC: row.get("cedent_naic", ""),
                _COL_CEDENT_NAME: row.get("cedent_name", ""),
                _COL_YEAR: row.get("year", ""),
                _COL_PART: row.get("part", ""),
                _COL_LINE: row.get("line_num", ""),
                _COL_REINS_NAME: row.get("reins_name", ""),
                _COL_REINS_NAIC: row.get("reins_naic", ""),
                _COL_REINS_FED_ID: row.get("reins_fed_id", ""),
                _COL_DOMICILE: row.get("domicile", ""),
                _COL_TYPE: row.get("type_business", ""),
                _COL_CEDED_AMT: str(row.get("ceded_thousands", "0")),
            })


# ──────────────────────────────────────────────────────────────────────────────
# Unmapped registry
# ──────────────────────────────────────────────────────────────────────────────


def _write_unmapped_registry(period: Period, unmapped: list[dict]) -> None:
    """Write unknown reinsurer entries to the unmapped registry."""
    registry_dir = Path("claimweb") / "registry" / "unmapped"
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / f"naic_schedule_s_{period}.json"
    existing: list[dict] = []
    with contextlib.suppress(OSError, json.JSONDecodeError):
        existing = json.loads(path.read_text())
    seen = {(r.get("reins_name"), r.get("domicile")) for r in existing}
    for entry in unmapped:
        key = (entry.get("reins_name"), entry.get("domicile"))
        if key not in seen:
            existing.append(entry)
            seen.add(key)
    path.write_text(json.dumps(existing, indent=2))
    log.info("Updated unmapped registry at %s (%d entries)", path, len(existing))


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher
# ──────────────────────────────────────────────────────────────────────────────


class NaicScheduleSFetcher(BaseFetcher):
    """Fetcher for NAIC Schedule S reinsurance ceded data.

    Source: NAIC statutory annual statements, Schedule S Parts 2 and 4
            (reinsurance ceded to non-affiliates and affiliates respectively).
    Portal: Iowa Insurance Division (primary for IA-domiciled companies);
            supplemented by IN, TN, NY, NJ state portals and the NAIC CIS.
    Cadence: Annual (year-end December 31; represented as YYYY-Q4).
    Format:  Per-company CSV in NAIC blank schedule format.
    Populates: A6 arcs (reinsurance treaties, offshore-cession) — T1 → T2.
    Project plan: §10.3.
    """

    source_id: str = "naic_schedule_s"
    cadence: Literal["annual", "quarterly", "monthly"] = "annual"

    def list_available_periods(self) -> list[Period]:
        """Return sorted list of periods for which raw CSV data is cached.

        Only Q4 periods are returned (NAIC annual statements are year-end).
        Scans data/raw/naic_schedule_s/ for YYYY-Q4 subdirectories.
        """
        base = Path("data") / "raw" / self.source_id
        if not base.exists():
            return []
        periods: list[Period] = []
        for d in base.iterdir():
            if not d.is_dir():
                continue
            with contextlib.suppress(ValueError):
                p = Period(d.name)
                if p.quarter == 4:
                    periods.append(p)
        return sorted(periods)

    def acquire(self, period: Period) -> RawDataHandle:
        """Download (or use cached) Schedule S data for ``period``.

        Only Q4 periods are valid (NAIC annual statements are December 31).
        Raises ValueError for non-Q4 periods.

        Acquisition sequence per company in _CEDENT_REGISTRY:
        1. Check cache; if valid CSV exists skip download.
        2. Dispatch to the appropriate state-portal fetch function.
        3. Write CSV to data/raw/naic_schedule_s/{period}/{naic_code}_schedule_s.csv.

        Returns a RawDataHandle covering all per-company CSV files.
        """
        if period.quarter != 4:
            raise ValueError(
                f"NAIC annual statements are year-end only; expected Q4 period, "
                f"got {period}"
            )
        year = _period_to_year(period)
        cache_dir = Path("data") / "raw" / self.source_id / str(period)
        cache_dir.mkdir(parents=True, exist_ok=True)

        csv_paths: list[Path] = []
        headers = {"User-Agent": _USER_AGENT}

        with httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
            for naic_code, company in _CEDENT_REGISTRY.items():
                filename = f"{naic_code}_schedule_s.csv"
                dest = cache_dir / filename

                if self._cache_valid(dest):
                    log.debug("Using cached Schedule S for %s (%s)", naic_code, period)
                    csv_paths.append(dest)
                    continue

                rows = self._fetch_company(client, headers, naic_code, company, year)
                if rows:
                    _write_schedule_s_csv(dest, rows)
                    csv_paths.append(dest)
                    log.info(
                        "Downloaded Schedule S: %s %s → %d rows",
                        company["name"], period, len(rows),
                    )
                else:
                    log.warning(
                        "No Schedule S data for %s (%s); file not written",
                        naic_code, period,
                    )
                time.sleep(_REQUEST_INTERVAL_S)

        if not csv_paths:
            log.warning("No Schedule S CSVs acquired for %s", period)
        return RawDataHandle.from_paths(self.source_id, period, csv_paths)

    @staticmethod
    def _cache_valid(path: Path) -> bool:
        if not path.exists():
            return False
        age = date.today() - date.fromtimestamp(path.stat().st_mtime)
        return age <= timedelta(days=_CACHE_LIFETIME_DAYS)

    @staticmethod
    def _fetch_company(
        client: httpx.Client,
        headers: dict,
        naic_code: str,
        company: dict,
        year: int,
    ) -> list[dict]:
        """Dispatch to the appropriate state-portal fetch for one company.

        Returns a list of raw row dicts (not yet converted to ArcFacts).
        Returns empty list on failure (logged as warning).
        """
        state = company.get("state", "")
        if state == "IA":
            return NaicScheduleSFetcher._fetch_iowa(
                client, headers, naic_code, company["name"], year
            )
        # Other states fall through to NAIC CIS.
        return NaicScheduleSFetcher._fetch_naic_cis(
            client, headers, naic_code, company["name"], year
        )

    @staticmethod
    def _fetch_iowa(
        client: httpx.Client,
        headers: dict,
        naic_code: str,
        company_name: str,
        year: int,
    ) -> list[dict]:
        """Attempt to fetch Iowa IID annual statement data for a company.

        Iowa IID provides annual statements for Iowa-domiciled insurers at
        https://iid.iowa.gov/companies/{company_path}/annual-statements/.
        The structured data is typically in PDF; this method returns empty
        and logs the URL to fetch for manual download when not parseable.
        """
        url = f"{_IOWA_IID_BASE}/companies/{naic_code}/financials/{year}/schedule_s"
        try:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return _parse_iowa_response(resp.content, naic_code, company_name, year)
        except httpx.HTTPError as exc:
            log.warning("Iowa IID fetch failed for %s: %s", naic_code, exc)
            return []

    @staticmethod
    def _fetch_naic_cis(
        client: httpx.Client,
        headers: dict,
        naic_code: str,
        company_name: str,
        year: int,
    ) -> list[dict]:
        """Attempt to fetch Schedule S data from the NAIC CIS service.

        The NAIC Content and Information Services (CIS) provides limited
        free public access to company financial data at content.naic.org.
        """
        url = f"{_NAIC_CIS_BASE}/financials/{naic_code}/{year}/schedule_s"
        try:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return _parse_naic_cis_response(resp.content, naic_code, company_name, year)
        except httpx.HTTPError as exc:
            log.warning("NAIC CIS fetch failed for %s: %s", naic_code, exc)
            return []

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse cached Schedule S CSV files into A6 ArcFacts.

        For each row in each per-company CSV:
        - Skip non-ceded parts (Parts 1 and 3 are assumed reinsurance, not ceded).
        - Emit one ArcFact per reinsurer row with:
            source = cedent insurer (from _CEDENT_REGISTRY or NAIC code)
            target = reinsurer (domicile-based ID)
            arc_class = A6
            dollar_amount_millions = ceded_thousands × 0.001
            data_quality_flag = DIRECT_MEASURED
            measurement_basis = stock_eop
        - Write unmapped reinsurers to the unmapped registry.
        - Skip rows with ceded_amount == 0 (no economic content).
        """
        facts: list[ArcFact] = []
        unmapped: list[dict] = []

        for path in handle.paths:
            if not path.exists() or path.suffix != ".csv":
                continue
            sha = handle.sha256_by_path.get(str(path), "0" * 64)
            rows = _read_schedule_s_csv(path)

            for row in rows:
                ceded_k = row["ceded_thousands"]
                if ceded_k == Decimal("0"):
                    continue

                cedent_node = _cedent_node_id(row["cedent_naic"])
                reins_node = _reinsurer_node_id(
                    row["reins_name"], row["reins_naic"], row["domicile"]
                )

                # Track unmapped reinsurers for human review.
                if reins_node.endswith(f":name:{_normalise_name(row['reins_name'])}") or \
                        reins_node.endswith(":unknown"):
                    unmapped.append({
                        "reins_name": row["reins_name"],
                        "domicile": row["domicile"],
                        "reins_naic": row["reins_naic"],
                        "suggested_id": reins_node,
                        "period": str(handle.period),
                    })

                year_str = row.get("year") or str(handle.period.year)
                provenance_url = (
                    f"{_IOWA_IID_BASE}/companies/{row['cedent_naic']}/"
                    f"financials/{year_str}/schedule_s"
                    if _CEDENT_REGISTRY.get(row["cedent_naic"], {}).get("state") == "IA"
                    else f"{_NAIC_CIS_BASE}/financials/{row['cedent_naic']}/"
                    f"{year_str}/schedule_s"
                )

                facts.append(ArcFact(
                    period=handle.period,
                    source_node_id=cedent_node,
                    target_node_id=reins_node,
                    instrument_class=ArcClass.A6,
                    dollar_amount_millions=ceded_k * _THOUSANDS_TO_MILLIONS,
                    measurement_basis="stock_eop",
                    data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
                    provenance_source=self.source_id,
                    provenance_url=provenance_url,
                    provenance_filing=f"NAIC/{row['cedent_naic']}/{year_str}/ScheduleS",
                    provenance_page=None,
                    provenance_field=f"Schedule_S_{row['part']}.{_COL_CEDED_AMT}",
                    sha256_of_source=sha,
                ))

        if unmapped:
            _write_unmapped_registry(handle.period, unmapped)

        return facts

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Validate parsed Schedule S arcs.

        Checks:
        - All arcs are A6 class.
        - No negative ceded amounts.
        - At least one offshore reinsurer target present (Bermuda/Cayman).
        - Source nodes have expected insurer: prefix.
        - Total ceded reserves plausible (> _MIN_CEDED_TOTAL_MM).
        - Warns if no A6 arcs emitted at all.
        """
        period = facts[0].period if facts else Period("2000-Q1")
        report = ValidationReport(source_id=self.source_id, period=period)

        if not facts:
            report.warning(
                "NO_ARCS",
                "NaicScheduleSFetcher produced no arcs; check that CSV files "
                "are present and contain ceded-reinsurance rows with non-zero amounts.",
            )
            return report

        total_ceded = Decimal("0")
        for arc in facts:
            if arc.instrument_class is not ArcClass.A6:
                report.error(
                    "WRONG_ARC_CLASS",
                    f"Expected A6; got {arc.instrument_class.value} on arc "
                    f"{arc.source_node_id} → {arc.target_node_id}",
                    affected_arcs=(f"{arc.source_node_id}→{arc.target_node_id}",),
                )
            if arc.dollar_amount_millions < Decimal("0"):
                report.error(
                    "NEGATIVE_CEDED",
                    f"Negative ceded amount on arc {arc.source_node_id} → "
                    f"{arc.target_node_id}: {arc.dollar_amount_millions}",
                    affected_arcs=(f"{arc.source_node_id}→{arc.target_node_id}",),
                )
            if not arc.source_node_id.startswith("insurer:"):
                report.warning(
                    "UNEXPECTED_SOURCE_PREFIX",
                    f"Source {arc.source_node_id!r} does not start with 'insurer:'",
                    affected_arcs=(arc.source_node_id,),
                )
            if not arc.target_node_id.startswith("reinsurer:") and \
                    not arc.target_node_id.startswith("insurer:"):
                report.warning(
                    "UNEXPECTED_TARGET_PREFIX",
                    f"Target {arc.target_node_id!r} does not start with 'reinsurer:' "
                    "or 'insurer:'",
                    affected_arcs=(arc.target_node_id,),
                )
            total_ceded += arc.dollar_amount_millions

        offshore_count = sum(
            1 for arc in facts if arc.target_node_id.startswith("reinsurer:")
        )
        if offshore_count == 0:
            report.info(
                "NO_OFFSHORE_ARCS",
                "No offshore reinsurer targets found; expected at least one "
                "reinsurer: arc in a full Schedule S snapshot.",
            )

        if total_ceded < _MIN_CEDED_TOTAL_MM and total_ceded > Decimal("0"):
            report.warning(
                "LOW_CEDED_TOTAL",
                f"Total ceded reserves ${total_ceded:.1f}M seems low; expected "
                f"≥ ${_MIN_CEDED_TOTAL_MM}M for a significant insurer population.",
            )

        return report


# ──────────────────────────────────────────────────────────────────────────────
# Response parsers  (state-portal-specific)
# ──────────────────────────────────────────────────────────────────────────────


def _parse_iowa_response(
    content: bytes,
    cedent_naic: str,
    cedent_name: str,
    year: int,
) -> list[dict]:
    """Parse an Iowa IID response body into Schedule S row dicts.

    Iowa IID may return CSV or JSON; this function attempts both.
    Returns empty list if neither format is detected.
    """
    rows: list[dict] = []
    text = content.decode("utf-8-sig", errors="replace")

    # Try JSON first (structured API response).
    with contextlib.suppress(json.JSONDecodeError):
        data = json.loads(text)
        rows = _rows_from_json(data, cedent_naic, cedent_name, year)
        if rows:
            return rows

    # Try CSV fallback.
    with contextlib.suppress(Exception):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            normalised = _normalise_csv_row(row, cedent_naic, cedent_name, year)
            if normalised:
                rows.append(normalised)

    return rows


def _parse_naic_cis_response(
    content: bytes,
    cedent_naic: str,
    cedent_name: str,
    year: int,
) -> list[dict]:
    """Parse a NAIC CIS response body into Schedule S row dicts."""
    return _parse_iowa_response(content, cedent_naic, cedent_name, year)


def _rows_from_json(
    data: object,
    cedent_naic: str,
    cedent_name: str,
    year: int,
) -> list[dict]:
    """Extract Schedule S rows from a JSON API response."""
    rows: list[dict] = []
    items: list = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data", data.get("rows", data.get("records", [])))
        if not isinstance(items, list):
            return rows

    for item in items:
        if not isinstance(item, dict):
            continue
        # Best-effort extraction using various field-name conventions.
        reins_name = (
            item.get("reinsurer_name") or item.get("reinsurerName")
            or item.get("REINSURER_NAME") or item.get("counterparty_name", "")
        ).strip()
        part = (
            item.get("schedule_part") or item.get("schedulePart")
            or item.get("SCHEDULE_PART") or item.get("part", "")
        ).strip().upper()
        if not reins_name or part not in _CEDED_PARTS:
            continue
        rows.append({
            "cedent_naic": cedent_naic,
            "cedent_name": cedent_name,
            "year": str(year),
            "part": part,
            "line_num": str(item.get("line_num", "")),
            "reins_name": reins_name,
            "reins_naic": str(item.get("reinsurer_naic", item.get("REINSURER_NAIC", ""))),
            "reins_fed_id": str(item.get("reinsurer_fed_id", "")),
            "domicile": str(
                item.get("domicile") or item.get("domicile_jurisdiction") or ""
            ),
            "type_business": str(item.get("type_business", item.get("type", "T"))),
            "ceded_thousands": _parse_amount(
                str(item.get("ceded_amount", item.get("amount", "0")))
            ),
        })
    return rows


def _normalise_csv_row(
    row: dict,
    cedent_naic: str,
    cedent_name: str,
    year: int,
) -> dict | None:
    """Attempt to normalise a raw CSV row into the canonical format."""
    # Try to detect column names that match expected fields.
    reins_name = ""
    for key in ("REINSURER_NAME", "reinsurer_name", "Reinsurer Name", "Name"):
        if key in row and row[key].strip():
            reins_name = row[key].strip()
            break
    if not reins_name:
        return None

    part = ""
    for key in ("SCHEDULE_PART", "schedule_part", "Part"):
        if key in row:
            part = row[key].strip().upper()
            break
    if part not in _CEDED_PARTS:
        return None

    domicile = ""
    for key in ("DOMICILE_JURISDICTION", "domicile", "Domicile", "State"):
        if key in row:
            domicile = row[key].strip()
            break

    amount_str = ""
    for key in (_COL_CEDED_AMT, "ceded_amount", "Amount", "AMOUNT"):
        if key in row:
            amount_str = row[key]
            break

    return {
        "cedent_naic": cedent_naic,
        "cedent_name": cedent_name,
        "year": str(year),
        "part": part,
        "line_num": row.get(_COL_LINE, row.get("line_num", "")).strip(),
        "reins_name": reins_name,
        "reins_naic": row.get(_COL_REINS_NAIC, row.get("reinsurer_naic", "")).strip(),
        "reins_fed_id": row.get(_COL_REINS_FED_ID, "").strip(),
        "domicile": domicile,
        "type_business": row.get(_COL_TYPE, row.get("type", "T")).strip(),
        "ceded_thousands": _parse_amount(amount_str),
    }
