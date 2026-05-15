"""NAIC Schedule D Part 1 — Long-term bond holdings fetcher (project plan §10.3).

Source: NAIC statutory annual statements, Schedule D Part 1 (Long-term bonds).
        NAIC filings are intermediated through state insurance department portals;
        there is no free central repository.  The primary acquisition path targets
        the Iowa Insurance Division (https://iid.iowa.gov/) because most PE-affiliated
        insurers (Athene, American Equity, F&G, Global Atlantic) are Iowa-domiciled,
        supplemented by the Indiana, New York, New Jersey, and Ohio DOI portals for
        non-Iowa domiciled companies.
        As a secondary path the fetcher also queries the NAIC company information
        service (https://content.naic.org/cis/) which provides limited free access.
Cadence: Annual (filed by March 1 for prior December 31 year-end).
         The annual period is represented as YYYY-Q4 (e.g., "2024-Q4" = the
         December 31, 2024 annual statement).
Format:  NAIC blank Schedule D Part 1 CSV (see _SCHED_D_COLUMNS below);
         par/book values in thousands of USD.
Populates: A7 arcs (CLO mezzanine tranches), A10 arcs (Treasuries and agency
           MBS), and A12 arcs (corporate bonds and residual).  The insurer is
           always the HOLDER (target node); the bond issuer is the SOURCE node.
           Project plan §10.3.

NAIC Schedule D structure
--------------------------
Schedule D of the NAIC Annual Statement blank discloses invested-asset holdings:

  Part 1 — Long-term bonds                ← A7 / A10 / A12 arcs (this fetcher)
  Part 2 — Long-term stocks
  Part 3 — Short-term investments
  Part 4 — Mortgage loans
  Part 5 — Other invested assets
  Part 6 — Summary

Only Part 1 (long-term bonds) is acquired here, because that is where the
CLO mezzanine, Treasury, and corporate bond holdings appear.

Arc direction (project plan §1 and §4):
  source_node_id = bond issuer (the entity that has the liability)
  target_node_id = insurer holder (the entity that holds the asset)

Arc classification by security type:
  A7 — CLO/CDO mezzanine tranches (structured credit with illiquid underlying)
  A10 — U.S. Treasuries, GSE securities, agency MBS
  A12 — Corporate bonds and residual fixed-income (everything else)

Node ID conventions:
  Insurer holder:   insurer:naic:{5-digit-code}      canonical from _INSURER_REGISTRY
  Treasury/GSE:     issuer:us_treasury               for Treasuries, T-bills, T-notes
                    issuer:agency_mbs:{slug}          for GSE-guaranteed MBS
  CLO issuer:       issuer:clo:{cusip_prefix}         CUSIP-keyed for CLO vehicles
                    issuer:clo:name:{slug}            fallback when CUSIP unavailable
  Corporate issuer: issuer:corp:{cusip_prefix}         CUSIP-keyed
                    issuer:corp:name:{slug}            fallback when CUSIP unavailable
  Unmapped:         → claimweb/registry/unmapped/naic_schedule_d_{period}.json

Dollar amounts: NAIC statutory filings denominate amounts in thousands of USD.
  Parser multiplies by _THOUSANDS_TO_MILLIONS (= Decimal("0.001")) → millions.
  The BOOK_VALUE_THOUSANDS column (amortized cost / book value) is used as the
  primary amount.  If book value is absent, PAR_VALUE_THOUSANDS is used as a
  fallback (flagged as PROXY).

Data quality flag: DIRECT_MEASURED — NAIC statutory filing, regulator-reviewed.
Measurement basis: stock_eop — December 31 year-end snapshot of bond holdings.

Acquisition strategy
--------------------
1. For each target company in _INSURER_REGISTRY:
   a. Look up the domicile state from the registry.
   b. Call the appropriate state-portal fetch function:
      - Iowa ("IA")     → _fetch_iowa_statement()
      - Other states    → _fetch_naic_cis_statement() (NAIC CIS fallback)
   c. Download the annual statement data (PDF or structured file).
   d. Parse the Schedule D Part 1 section.
   e. Cache as {naic_code}_schedule_d.csv under data/raw/naic_schedule_d/{period}/.
2. The CSV cache is the canonical artifact; all downstream processing reads CSV.
3. Cache lifetime: 365 days (annual filings are final once submitted).
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

# Iowa Insurance Division base URL for annual statement access.
_IOWA_IID_BASE = "https://iid.iowa.gov"

# NAIC company information service — limited free public access.
_NAIC_CIS_BASE = "https://content.naic.org/cis"

# Cache lifetime in days (annual filings are final).
_CACHE_LIFETIME_DAYS = 365

# NAIC amounts are in thousands of USD; canonical unit is millions.
_THOUSANDS_TO_MILLIONS = Decimal("0.001")

# Minimum plausible total holdings for a significant life insurer (millions).
_MIN_HOLDINGS_TOTAL_MM = Decimal("1000")

# ──────────────────────────────────────────────────────────────────────────────
# CSV column names  (NAIC blank Schedule D Part 1 electronic filing format)
# ──────────────────────────────────────────────────────────────────────────────

_COL_INSURER_NAIC = "INSURER_NAIC_CODE"
_COL_INSURER_NAME = "INSURER_NAME"
_COL_YEAR = "STATEMENT_YEAR"
_COL_CUSIP = "CUSIP"
_COL_DESCRIPTION = "SECURITY_DESCRIPTION"
_COL_ISSUER_NAME = "ISSUER_NAME"
_COL_ISSUER_NAIC = "ISSUER_NAIC_CODE"
_COL_SECURITY_TYPE = "SECURITY_TYPE"   # "CLO","CMO","MBS","UST","CORP","MUNI","OTHER"
_COL_NAIC_DESIG = "NAIC_DESIGNATION"   # "1".."6" (credit quality)
_COL_MATURITY = "MATURITY_DATE"
_COL_PAR_VALUE = "PAR_VALUE_THOUSANDS"
_COL_BOOK_VALUE = "BOOK_VALUE_THOUSANDS"
_COL_FAIR_VALUE = "FAIR_VALUE_THOUSANDS"

# ──────────────────────────────────────────────────────────────────────────────
# Insurer registry — target U.S. life insurers (PE-affiliated focus)
# ──────────────────────────────────────────────────────────────────────────────

_INSURER_REGISTRY: dict[str, dict] = {
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
        "state": "IA",
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
# Security classification keywords
# ──────────────────────────────────────────────────────────────────────────────

# Keywords in security description or type field → A7 (CLO/structured credit).
_CLO_TYPE_CODES: frozenset[str] = frozenset({"CLO", "CDO", "CMO"})
_CLO_DESC_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bCLO\b", re.IGNORECASE),
    re.compile(r"\bCDO\b", re.IGNORECASE),
    re.compile(r"COLLATERALIZED\s+LOAN\s+OBLIGATION", re.IGNORECASE),
    re.compile(r"COLLATERALIZED\s+DEBT\s+OBLIGATION", re.IGNORECASE),
)

# Keywords / type codes → A10 (Treasuries and agency MBS).
_GOV_TYPE_CODES: frozenset[str] = frozenset({"UST", "USTR", "AGY", "AGYMBS", "MBS"})
_GOV_DESC_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"U\.?S\.?\s+TREASURY", re.IGNORECASE),
    re.compile(r"US\s+TREAS", re.IGNORECASE),
    re.compile(r"UNITED\s+STATES\s+TREAS", re.IGNORECASE),
    re.compile(r"FNMA|FHLMC|GNMA|FREDDIE|FANNIE|GINNIE", re.IGNORECASE),
    re.compile(r"FEDERAL\s+(HOME\s+LOAN|NATIONAL\s+MORTGAGE|NATIONAL\s+MTGE)", re.IGNORECASE),
    re.compile(r"GOVT\s+(NAT|NATL)\s+(MTGE|MORTGAGE)", re.IGNORECASE),
)

# CUSIP prefix for US Treasuries: first digit = '9' for agency, first 6 chars
# of CUSIP for specific Treasury identifiers.
_TREASURY_CUSIP_PREFIXES: tuple[str, ...] = (
    "912810",  # long-term Treasury bonds
    "912828",  # Treasury notes
    "912796",  # Treasury bills (CMBs)
    "9128",    # broader Treasury prefix
    "912833",  # TIPS
    "91282",   # recent Treasuries
)
_AGENCY_CUSIP_PREFIXES: tuple[str, ...] = (
    "3135",    # FNMA (Fannie Mae)
    "3137",    # FHLMC (Freddie Mac)
    "38375",   # GNMA (Ginnie Mae)
    "38376",   # GNMA II
    "3130",    # FHLB bonds (A3 arc - but if insurer holds FHLB bonds as investments...)
)

# ──────────────────────────────────────────────────────────────────────────────
# Node-ID helpers
# ──────────────────────────────────────────────────────────────────────────────


def _normalise_name(name: str) -> str:
    """Produce a stable slug (max 64 chars) from an entity name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:64]


def _insurer_node_id(naic_code: str) -> str:
    """Return canonical node ID for an insurer by NAIC code."""
    entry = _INSURER_REGISTRY.get(naic_code.strip())
    if entry:
        return entry["node_id"]
    return f"insurer:naic:{naic_code.strip()}"


def _issuer_node_id(
    cusip: str,
    issuer_name: str,
    security_type: str,
    arc_class: ArcClass,
) -> str:
    """Return canonical source node ID for a bond issuer.

    Priority:
    1. CUSIP-keyed ID (stable, unique per series) for structured/corporate.
    2. Well-known canonical IDs for Treasuries and agencies.
    3. Name-slugged fallback.
    """
    cusip_clean = cusip.strip().upper()
    name_slug = _normalise_name(issuer_name)

    if arc_class is ArcClass.A10:
        # Determine if Treasury or agency.
        if cusip_clean and any(
            cusip_clean.startswith(p) for p in _TREASURY_CUSIP_PREFIXES
        ):
            return "issuer:us_treasury"
        if cusip_clean and any(
            cusip_clean.startswith(p) for p in _AGENCY_CUSIP_PREFIXES
        ):
            if "FNMA" in issuer_name.upper() or "FANNIE" in issuer_name.upper():
                return "issuer:agency:fnma"
            if "FHLMC" in issuer_name.upper() or "FREDDIE" in issuer_name.upper():
                return "issuer:agency:fhlmc"
            if "GNMA" in issuer_name.upper() or "GINNIE" in issuer_name.upper():
                return "issuer:agency:gnma"
            return f"issuer:agency:{name_slug[:32]}" if name_slug else "issuer:agency:unknown"
        # Generic gov't / agency fallback.
        if name_slug:
            return f"issuer:gov:{name_slug[:48]}"
        return "issuer:us_treasury"

    if arc_class is ArcClass.A7:
        cusip_prefix = cusip_clean[:6] if len(cusip_clean) >= 6 else cusip_clean
        if cusip_prefix:
            return f"issuer:clo:{cusip_prefix}"
        if name_slug:
            return f"issuer:clo:name:{name_slug[:48]}"
        return "issuer:clo:unknown"

    # A12 — corporate bond
    cusip_prefix = cusip_clean[:6] if len(cusip_clean) >= 6 else cusip_clean
    if cusip_prefix:
        return f"issuer:corp:{cusip_prefix}"
    if name_slug:
        return f"issuer:corp:name:{name_slug[:48]}"
    return "issuer:corp:unknown"


def _classify_security(
    cusip: str,
    description: str,
    security_type: str,
    naic_designation: str,
) -> ArcClass:
    """Classify a Schedule D Part 1 security into an arc class.

    Classification hierarchy:
    1. CLO/CDO → A7 (structured credit, illiquid underlying).
    2. Treasury / agency MBS → A10.
    3. Everything else → A12 (corporate bonds, residual).

    The NAIC designation (1–6) is not used for classification — it indicates
    credit quality, not instrument type.
    """
    type_clean = security_type.strip().upper()
    desc_clean = description.strip()
    cusip_clean = cusip.strip().upper()

    # Check for CLO/CDO structured credit.
    if type_clean in _CLO_TYPE_CODES:
        return ArcClass.A7
    for pat in _CLO_DESC_PATTERNS:
        if pat.search(desc_clean):
            return ArcClass.A7

    # Check for Treasuries / agency MBS.
    if type_clean in _GOV_TYPE_CODES:
        return ArcClass.A10
    if cusip_clean and any(
        cusip_clean.startswith(p) for p in _TREASURY_CUSIP_PREFIXES
    ):
        return ArcClass.A10
    if cusip_clean and any(
        cusip_clean.startswith(p) for p in _AGENCY_CUSIP_PREFIXES
    ):
        return ArcClass.A10
    for pat in _GOV_DESC_PATTERNS:
        if pat.search(desc_clean):
            return ArcClass.A10

    return ArcClass.A12


# ──────────────────────────────────────────────────────────────────────────────
# Amount parsing
# ──────────────────────────────────────────────────────────────────────────────


def _parse_amount(raw: str) -> Decimal:
    """Parse a Schedule D amount field (thousands USD) to Decimal.

    Returns Decimal("0") for blank, non-numeric, or parenthesized-negative.
    NAIC blanks sometimes use parentheses for negative amounts: "(1234)" → "-1234".
    """
    cleaned = raw.strip().replace(",", "").replace("$", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    if not cleaned:
        return Decimal("0")
    with contextlib.suppress(InvalidOperation):
        return Decimal(cleaned)
    return Decimal("0")


# ──────────────────────────────────────────────────────────────────────────────
# CSV read/write helpers
# ──────────────────────────────────────────────────────────────────────────────

_SCHED_D_FIELDNAMES = [
    _COL_INSURER_NAIC,
    _COL_INSURER_NAME,
    _COL_YEAR,
    _COL_CUSIP,
    _COL_DESCRIPTION,
    _COL_ISSUER_NAME,
    _COL_ISSUER_NAIC,
    _COL_SECURITY_TYPE,
    _COL_NAIC_DESIG,
    _COL_MATURITY,
    _COL_PAR_VALUE,
    _COL_BOOK_VALUE,
    _COL_FAIR_VALUE,
]


def _read_schedule_d_csv(path: Path) -> list[dict]:
    """Read a cached Schedule D Part 1 CSV; return list of row dicts.

    Tolerates UTF-8 and Windows-1252 encoding; strips BOM.
    Rows with both par and book value = 0 are included (caller skips them).
    """
    rows: list[dict] = []
    with contextlib.suppress(OSError):
        content = path.read_bytes().decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            insurer_naic = row.get(_COL_INSURER_NAIC, "").strip()
            description = row.get(_COL_DESCRIPTION, "").strip()
            if not insurer_naic or not description:
                continue
            rows.append({
                "insurer_naic": insurer_naic,
                "insurer_name": row.get(_COL_INSURER_NAME, "").strip(),
                "year": row.get(_COL_YEAR, "").strip(),
                "cusip": row.get(_COL_CUSIP, "").strip(),
                "description": description,
                "issuer_name": row.get(_COL_ISSUER_NAME, "").strip(),
                "issuer_naic": row.get(_COL_ISSUER_NAIC, "").strip(),
                "security_type": row.get(_COL_SECURITY_TYPE, "").strip(),
                "naic_designation": row.get(_COL_NAIC_DESIG, "").strip(),
                "maturity": row.get(_COL_MATURITY, "").strip(),
                "par_thousands": _parse_amount(row.get(_COL_PAR_VALUE, "")),
                "book_thousands": _parse_amount(row.get(_COL_BOOK_VALUE, "")),
                "fair_thousands": _parse_amount(row.get(_COL_FAIR_VALUE, "")),
            })
    return rows


def _write_schedule_d_csv(path: Path, rows: list[dict]) -> None:
    """Write Schedule D Part 1 rows to a canonical CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_SCHED_D_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                _COL_INSURER_NAIC: row.get("insurer_naic", ""),
                _COL_INSURER_NAME: row.get("insurer_name", ""),
                _COL_YEAR: row.get("year", ""),
                _COL_CUSIP: row.get("cusip", ""),
                _COL_DESCRIPTION: row.get("description", ""),
                _COL_ISSUER_NAME: row.get("issuer_name", ""),
                _COL_ISSUER_NAIC: row.get("issuer_naic", ""),
                _COL_SECURITY_TYPE: row.get("security_type", ""),
                _COL_NAIC_DESIG: row.get("naic_designation", ""),
                _COL_MATURITY: row.get("maturity", ""),
                _COL_PAR_VALUE: str(row.get("par_thousands", "0")),
                _COL_BOOK_VALUE: str(row.get("book_thousands", "0")),
                _COL_FAIR_VALUE: str(row.get("fair_thousands", "0")),
            })


# ──────────────────────────────────────────────────────────────────────────────
# Unmapped registry
# ──────────────────────────────────────────────────────────────────────────────


def _write_unmapped_registry(period: Period, unmapped: list[dict]) -> None:
    """Write unknown issuer entries to the unmapped registry."""
    registry_dir = Path("claimweb") / "registry" / "unmapped"
    registry_dir.mkdir(parents=True, exist_ok=True)
    path = registry_dir / f"naic_schedule_d_{period}.json"
    existing: list[dict] = []
    with contextlib.suppress(OSError, json.JSONDecodeError):
        existing = json.loads(path.read_text())
    seen = {(r.get("cusip"), r.get("issuer_name")) for r in existing}
    for entry in unmapped:
        key = (entry.get("cusip"), entry.get("issuer_name"))
        if key not in seen:
            existing.append(entry)
            seen.add(key)
    path.write_text(json.dumps(existing, indent=2))
    log.info("Updated unmapped registry at %s (%d entries)", path, len(existing))


# ──────────────────────────────────────────────────────────────────────────────
# Period helper
# ──────────────────────────────────────────────────────────────────────────────


def _period_to_year(period: Period) -> int:
    """Return the calendar year for a period (NAIC annual = year-end Q4)."""
    return period.year


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleDFetcher
# ──────────────────────────────────────────────────────────────────────────────


class NaicScheduleDFetcher(BaseFetcher):
    """Fetcher for NAIC Schedule D Part 1 long-term bond holdings.

    Source: NAIC statutory annual statements, Schedule D Part 1.
    Portal: Iowa Insurance Division (primary for IA-domiciled companies);
            supplemented by TN, NY, NJ, IN state portals and the NAIC CIS.
    Cadence: Annual (year-end December 31; represented as YYYY-Q4).
    Format:  Per-company CSV in NAIC blank schedule format.
    Populates: A7 arcs (CLO mezzanine), A10 arcs (Treasuries/agency MBS),
               A12 arcs (corporate bonds) — issuer → insurer direction.
    Project plan: §10.3.
    """

    source_id: str = "naic_schedule_d"
    cadence: Literal["annual", "quarterly", "monthly"] = "annual"

    def list_available_periods(self) -> list[Period]:
        """Return sorted list of periods for which raw CSV data is cached.

        Only Q4 periods are returned (NAIC annual statements are year-end).
        Scans data/raw/naic_schedule_d/ for YYYY-Q4 subdirectories.
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
        """Download (or use cached) Schedule D Part 1 data for ``period``.

        Only Q4 periods are valid (NAIC annual statements are December 31).
        Raises ValueError for non-Q4 periods.

        Acquisition sequence per company in _INSURER_REGISTRY:
        1. Check cache; if valid CSV exists skip download.
        2. Dispatch to the appropriate state-portal fetch function.
        3. Write CSV to data/raw/naic_schedule_d/{period}/{naic_code}_schedule_d.csv.

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
            for naic_code, company in _INSURER_REGISTRY.items():
                filename = f"{naic_code}_schedule_d.csv"
                dest = cache_dir / filename

                if self._cache_valid(dest):
                    log.debug("Using cached Schedule D for %s (%s)", naic_code, period)
                    csv_paths.append(dest)
                    continue

                rows = self._fetch_company(client, headers, naic_code, company, year)
                if rows:
                    _write_schedule_d_csv(dest, rows)
                    csv_paths.append(dest)
                    log.info(
                        "Downloaded Schedule D: %s %s → %d rows",
                        company["name"], period, len(rows),
                    )
                else:
                    log.warning(
                        "No Schedule D data for %s (%s); file not written",
                        naic_code, period,
                    )
                time.sleep(_REQUEST_INTERVAL_S)

        if not csv_paths:
            log.warning("No Schedule D CSVs acquired for %s", period)
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
            return NaicScheduleDFetcher._fetch_iowa(
                client, headers, naic_code, company["name"], year
            )
        return NaicScheduleDFetcher._fetch_naic_cis(
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

        Iowa IID provides annual statements for Iowa-domiciled insurers.
        The Schedule D structured data is typically in PDF; this method
        returns empty and logs the URL when parsing fails.
        """
        url = f"{_IOWA_IID_BASE}/companies/{naic_code}/financials/{year}/schedule_d"
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
        """Attempt to fetch Schedule D data from the NAIC CIS service."""
        url = f"{_NAIC_CIS_BASE}/financials/{naic_code}/{year}/schedule_d"
        try:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return _parse_iowa_response(resp.content, naic_code, company_name, year)
        except httpx.HTTPError as exc:
            log.warning("NAIC CIS fetch failed for %s: %s", naic_code, exc)
            return []

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse cached Schedule D Part 1 CSV files into A7/A10/A12 ArcFacts.

        For each row in each per-company CSV:
        - Classify the security (CLO→A7, Gov't→A10, other→A12).
        - Emit one ArcFact per holding with:
            source = bond issuer (CUSIP-keyed or name-keyed)
            target = insurer holder (from _INSURER_REGISTRY)
            arc_class = A7 | A10 | A12
            dollar_amount_millions = book_thousands × 0.001
              (falls back to par_thousands if book value absent)
            data_quality_flag = DIRECT_MEASURED
            measurement_basis = stock_eop
        - Write unmapped issuers to the unmapped registry.
        - Skip rows with both book and par value = 0 (no economic content).
        """
        facts: list[ArcFact] = []
        unmapped: list[dict] = []

        for path in handle.paths:
            if not path.exists() or path.suffix != ".csv":
                continue
            sha = handle.sha256_by_path.get(str(path), "0" * 64)
            rows = _read_schedule_d_csv(path)

            for row in rows:
                book_k = row["book_thousands"]
                par_k = row["par_thousands"]
                if book_k == Decimal("0") and par_k == Decimal("0"):
                    continue

                # Use book value (amortized cost) as primary; par as fallback.
                if book_k != Decimal("0"):
                    amount_k = book_k
                    quality_flag = DataQualityFlag.DIRECT_MEASURED
                else:
                    amount_k = par_k
                    quality_flag = DataQualityFlag.PROXY

                arc_class = _classify_security(
                    row["cusip"],
                    row["description"],
                    row["security_type"],
                    row["naic_designation"],
                )
                insurer_node = _insurer_node_id(row["insurer_naic"])
                issuer_node = _issuer_node_id(
                    row["cusip"],
                    row["issuer_name"] or row["description"],
                    row["security_type"],
                    arc_class,
                )

                # Track unmapped issuers (name-based or unknown) for review.
                if ":name:" in issuer_node or issuer_node.endswith(":unknown"):
                    unmapped.append({
                        "cusip": row["cusip"],
                        "issuer_name": row["issuer_name"],
                        "description": row["description"],
                        "security_type": row["security_type"],
                        "suggested_id": issuer_node,
                        "arc_class": arc_class.value,
                        "period": str(handle.period),
                    })

                year_str = row.get("year") or str(handle.period.year)
                provenance_url = (
                    f"{_IOWA_IID_BASE}/companies/{row['insurer_naic']}/"
                    f"financials/{year_str}/schedule_d"
                    if _INSURER_REGISTRY.get(row["insurer_naic"], {}).get("state") == "IA"
                    else f"{_NAIC_CIS_BASE}/financials/{row['insurer_naic']}/"
                    f"{year_str}/schedule_d"
                )

                facts.append(ArcFact(
                    period=handle.period,
                    source_node_id=issuer_node,
                    target_node_id=insurer_node,
                    instrument_class=arc_class,
                    dollar_amount_millions=amount_k * _THOUSANDS_TO_MILLIONS,
                    measurement_basis="stock_eop",
                    data_quality_flag=quality_flag,
                    provenance_source=self.source_id,
                    provenance_url=provenance_url,
                    provenance_filing=(
                        f"NAIC/{row['insurer_naic']}/{year_str}/ScheduleD_Part1"
                    ),
                    provenance_page=None,
                    provenance_field=(
                        f"Schedule_D_Part1.CUSIP={row['cusip'] or 'n/a'}."
                        f"{_COL_BOOK_VALUE}"
                    ),
                    sha256_of_source=sha,
                ))

        if unmapped:
            _write_unmapped_registry(handle.period, unmapped)

        return facts

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Validate parsed Schedule D Part 1 arcs.

        Checks:
        - All arcs are A7, A10, or A12 class.
        - No negative holding amounts.
        - Source nodes have expected issuer: prefix.
        - Target nodes have expected insurer: prefix.
        - At least one A7 (CLO) and one A10 (Treasury) arc present.
        - Total holdings plausible (> _MIN_HOLDINGS_TOTAL_MM).
        - Warns if no arcs emitted at all.
        """
        period = facts[0].period if facts else Period("2000-Q1")
        report = ValidationReport(source_id=self.source_id, period=period)

        if not facts:
            report.warning(
                "NO_ARCS",
                "NaicScheduleDFetcher produced no arcs; check that CSV files "
                "are present and contain non-zero bond holding rows.",
            )
            return report

        _valid_classes = {ArcClass.A7, ArcClass.A10, ArcClass.A12}
        total_holdings = Decimal("0")
        for arc in facts:
            if arc.instrument_class not in _valid_classes:
                report.error(
                    "WRONG_ARC_CLASS",
                    f"Expected A7/A10/A12; got {arc.instrument_class.value} on arc "
                    f"{arc.source_node_id} → {arc.target_node_id}",
                    affected_arcs=(f"{arc.source_node_id}→{arc.target_node_id}",),
                )
            if arc.dollar_amount_millions < Decimal("0"):
                report.error(
                    "NEGATIVE_HOLDING",
                    f"Negative holding amount on arc {arc.source_node_id} → "
                    f"{arc.target_node_id}: {arc.dollar_amount_millions}",
                    affected_arcs=(f"{arc.source_node_id}→{arc.target_node_id}",),
                )
            if not arc.source_node_id.startswith("issuer:"):
                report.warning(
                    "UNEXPECTED_SOURCE_PREFIX",
                    f"Source {arc.source_node_id!r} does not start with 'issuer:'",
                    affected_arcs=(arc.source_node_id,),
                )
            if not arc.target_node_id.startswith("insurer:"):
                report.warning(
                    "UNEXPECTED_TARGET_PREFIX",
                    f"Target {arc.target_node_id!r} does not start with 'insurer:'",
                    affected_arcs=(arc.target_node_id,),
                )
            total_holdings += arc.dollar_amount_millions

        a7_count = sum(1 for a in facts if a.instrument_class is ArcClass.A7)
        a10_count = sum(1 for a in facts if a.instrument_class is ArcClass.A10)
        if a7_count == 0:
            report.info(
                "NO_CLO_ARCS",
                "No A7 (CLO mezzanine) arcs found; expected at least one for "
                "PE-affiliated life insurers with private-credit focus.",
            )
        if a10_count == 0:
            report.info(
                "NO_TREASURY_ARCS",
                "No A10 (Treasury/agency) arcs found; expected at least some "
                "government securities in a diversified life insurer portfolio.",
            )

        if Decimal("0") < total_holdings < _MIN_HOLDINGS_TOTAL_MM:
            report.warning(
                "LOW_HOLDINGS_TOTAL",
                f"Total holdings ${total_holdings:.1f}M seems low; expected "
                f"≥ ${_MIN_HOLDINGS_TOTAL_MM}M for a significant insurer population.",
            )

        return report


# ──────────────────────────────────────────────────────────────────────────────
# Response parsers  (state-portal-specific)
# ──────────────────────────────────────────────────────────────────────────────


def _parse_iowa_response(
    content: bytes,
    insurer_naic: str,
    insurer_name: str,
    year: int,
) -> list[dict]:
    """Parse an Iowa IID (or NAIC CIS) response body into Schedule D row dicts.

    Attempts JSON first (structured API), then CSV fallback.
    Returns empty list if neither format is parseable.
    """
    rows: list[dict] = []
    text = content.decode("utf-8-sig", errors="replace")

    with contextlib.suppress(json.JSONDecodeError):
        data = json.loads(text)
        rows = _rows_from_json(data, insurer_naic, insurer_name, year)
        if rows:
            return rows

    with contextlib.suppress(Exception):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            normalised = _normalise_csv_row(row, insurer_naic, insurer_name, year)
            if normalised:
                rows.append(normalised)

    return rows


def _rows_from_json(
    data: object,
    insurer_naic: str,
    insurer_name: str,
    year: int,
) -> list[dict]:
    """Extract Schedule D Part 1 rows from a JSON API response."""
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
        description = (
            item.get("description") or item.get("security_description")
            or item.get("SECURITY_DESCRIPTION") or item.get("name", "")
        ).strip()
        if not description:
            continue
        rows.append({
            "insurer_naic": insurer_naic,
            "insurer_name": insurer_name,
            "year": str(year),
            "cusip": str(item.get("cusip", item.get("CUSIP", ""))).strip(),
            "description": description,
            "issuer_name": str(
                item.get("issuer_name", item.get("issuerName", ""))
            ).strip(),
            "issuer_naic": str(
                item.get("issuer_naic", item.get("ISSUER_NAIC", ""))
            ).strip(),
            "security_type": str(
                item.get("security_type", item.get("securityType", ""))
            ).strip().upper(),
            "naic_designation": str(
                item.get("naic_designation", item.get("naicDesignation", ""))
            ).strip(),
            "maturity": str(
                item.get("maturity_date", item.get("maturityDate", ""))
            ).strip(),
            "par_thousands": _parse_amount(
                str(item.get("par_value", item.get("parValue", "0")))
            ),
            "book_thousands": _parse_amount(
                str(item.get("book_value", item.get("bookValue", "0")))
            ),
            "fair_thousands": _parse_amount(
                str(item.get("fair_value", item.get("fairValue", "0")))
            ),
        })
    return rows


def _normalise_csv_row(
    row: dict,
    insurer_naic: str,
    insurer_name: str,
    year: int,
) -> dict | None:
    """Attempt to normalise a raw CSV row into the canonical format.

    Handles multiple column-name conventions seen across state portals.
    Returns None if a description (required field) cannot be found.
    """
    description = ""
    for key in (
        _COL_DESCRIPTION, "description", "Description",
        "BOND_NAME", "Name", "SECURITY_NAME",
    ):
        if key in row and row[key].strip():
            description = row[key].strip()
            break
    if not description:
        return None

    cusip = ""
    for key in (_COL_CUSIP, "cusip", "CUSIP", "Cusip"):
        if key in row:
            cusip = row[key].strip()
            break

    security_type = ""
    for key in (_COL_SECURITY_TYPE, "security_type", "SecurityType", "Type"):
        if key in row:
            security_type = row[key].strip().upper()
            break

    issuer_name = ""
    for key in (_COL_ISSUER_NAME, "issuer_name", "IssuerName", "Issuer"):
        if key in row:
            issuer_name = row[key].strip()
            break

    par_str = ""
    for key in (_COL_PAR_VALUE, "par_value", "ParValue", "Par"):
        if key in row:
            par_str = row[key]
            break

    book_str = ""
    for key in (_COL_BOOK_VALUE, "book_value", "BookValue", "Book", "BACV"):
        if key in row:
            book_str = row[key]
            break

    fair_str = ""
    for key in (_COL_FAIR_VALUE, "fair_value", "FairValue", "Fair"):
        if key in row:
            fair_str = row[key]
            break

    return {
        "insurer_naic": insurer_naic,
        "insurer_name": insurer_name,
        "year": str(year),
        "cusip": cusip,
        "description": description,
        "issuer_name": issuer_name,
        "issuer_naic": row.get(_COL_ISSUER_NAIC, "").strip(),
        "security_type": security_type,
        "naic_designation": row.get(_COL_NAIC_DESIG, row.get("naic_designation", "")).strip(),
        "maturity": row.get(_COL_MATURITY, row.get("maturity_date", "")).strip(),
        "par_thousands": _parse_amount(par_str),
        "book_thousands": _parse_amount(book_str),
        "fair_thousands": _parse_amount(fair_str),
    }
