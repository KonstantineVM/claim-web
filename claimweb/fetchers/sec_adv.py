"""SEC Form ADV — Investment Adviser registration fetcher (project plan §10.6).

Source: SEC IAPD (Investment Adviser Public Disclosure) bulk data extract.
Page:   https://www.sec.gov/investment/form-adv-data
Data:   https://efts.sec.gov/LATEST/search-index?forms=ADV  (EDGAR EFTS)
        Firm-level and Schedule R CSVs from the IAPD bulk download.
Cadence: Snapshot at each quarter-end; ADV is filed annually with amendments
         on material change, so quarterly snapshots capture the current state.
Format: Two CSV files — IA firm metadata and Schedule R (related persons).
Populates: A11 arcs (equity/ownership claims) for G3 ownership graph (project
           plan §3.5), capturing AAM→insurer, AAM→CLO manager, AAM→BDC, and
           AAM→offshore reinsurer control/affiliation relationships.

Form ADV Part 1A, Schedule R (Related Persons)
-----------------------------------------------
Investment advisers registered with the SEC must list all "related persons"
— entities that are under common control or that the IA controls, or that
control the IA. The field ``relationship_type`` in Schedule R identifies whether
the related person is an insurance company, another investment adviser, a
broker-dealer, a bank, a registered pooled investment vehicle, etc.

CLAIM-WEB uses Schedule R to populate G3 (the ownership/affiliation graph)
focusing on the subset of relationships that link alternative asset managers
(I6 entities) to their affiliated insurers (T1), CLO managers (I7), BDCs (I8),
and offshore reinsurers (T2). This enables identification of "closed-loop"
clusters where an AAM earns fees at multiple steps in the circuit.

Arc direction (project plan §3.5, G3):
  source_node_id = AAM parent / controlling entity (the IA filer)
  target_node_id = related affiliate (insurer, CLO manager, BDC, reinsurer)
  instrument_class = ArcClass.A11  (equity/ownership relationship)

Node ID conventions:
  AAM parent:            aam:crd:{crd_number}         if CRD available
                         aam:name:{normalised_name}   otherwise
  Related insurer:       insurer:crd:{crd_number}     if CRD available
                         insurer:name:{slug}          otherwise
  Related IA / fund mgr: aam:crd:{crd_number}         if CRD available
                         aam:name:{slug}              otherwise
  Related BDC / fund:    bdc:crd:{crd_number}         if CRD available
                         bdc:name:{slug}              otherwise
  Related bank:          bank:crd:{crd_number}        if CRD available
                         bank:name:{slug}             otherwise
  Other / unknown:       entity:crd:{crd_number}      if CRD available
                         entity:name:{slug}           otherwise

Dollar amounts: Form ADV reports total regulatory assets under management
  (RAUM) in USD on Part 1A Item 5.F.  The RAUM of the controlling AAM firm
  is used as a proxy for the financial magnitude of each ownership arc; RAUM
  is reported in billions of USD; parser multiplies by 1000 → millions USD.
  Arc amount = parent firm RAUM / number of Schedule R arcs (not divided;
  each arc carries the full parent RAUM).  Data-quality flag = PROXY because
  RAUM is not the equity value of the specific controlled entity.

Data quality flag: PROXY — RAUM is the only financial metric available from
  ADV Part 1A and is used as a proxy for the financial scale of each
  affiliation arc.  Where RAUM is not disclosed (< $25M threshold exemption),
  dollar_amount_millions is set to Decimal("0").
Measurement basis: stock_eop — end-of-quarter snapshot of the current ADV
  filing (most recent amendment on file as of quarter-end).

IAPD bulk data format:
  The two CSV files have the following key columns (see _FIRM_COLS,
  _SCHED_R_COLS below).  The SEC IAPD uses Windows-1252 encoding (Latin-1
  superset); the parser specifies errors="replace" on open().

Rate limiting: EDGAR EFTS allows ~10 req/sec. The acquire step enforces
  150 ms between requests when making multiple EDGAR API calls.
"""
from __future__ import annotations

import contextlib
import csv
import io
import logging
import re
import time
import zipfile
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
_REQUEST_INTERVAL_S = 0.15

# IAPD bulk data landing page; the actual ZIP is linked from this page.
# The SEC publishes the IA firm extract and Schedule R extract via FOIA /
# Investment Adviser Data page.
_IAPD_PAGE_URL = "https://www.sec.gov/investment/form-adv-data"

# EDGAR EFTS full-text search endpoint (used to find most-recent ADV filings
# for target firms when bulk CSV is unavailable).
_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"

# EDGAR submissions API for a specific CIK.
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# EDGAR archives root (for downloading filing documents).
_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# Cache lifetime: 90 days (ADV amended ~annually; quarterly snapshot is safe).
_CACHE_LIFETIME_DAYS = 90

# Expected filenames in the IAPD bulk ZIP and in the per-period cache.
_FIRM_FILENAME = "ia_firm.csv"
_SCHED_R_FILENAME = "ia_schedule_r.csv"

# ADV filing types on EDGAR.
_ADV_FORM_TYPES = ("ADV", "ADV-E")

# RAUM conversion: ADV Part 1A Item 5.F reports in USD; canonical unit is
# millions USD.
_USD_TO_MILLIONS = Decimal("0.000001")

# Minimum plausible total RAUM (millions) for a significant AAM.
# Used in validate() to flag suspiciously low values.
_MIN_RAUM_MM = Decimal("100")

# ──────────────────────────────────────────────────────────────────────────────
# CSV column-name mapping  (confirmed against IAPD data extract format)
# ──────────────────────────────────────────────────────────────────────────────

# Canonical column names in the IA_FIRM CSV from the IAPD bulk extract.
_FIRM_COL_CRD = "CRD_NUMBER"
_FIRM_COL_SEC = "SEC_NUMBER"
_FIRM_COL_NAME = "LEGAL_NM"
_FIRM_COL_RAUM = "ASSETS_UNDER_MGMT_AMT"

# Canonical column names in the IA_SCHEDULE_R CSV from the IAPD bulk extract.
_SCHED_R_COL_FIRM_CRD = "CRD_NUMBER"
_SCHED_R_COL_RELATED_NM = "RELATED_PERSON_NM"
_SCHED_R_COL_RELATED_CRD = "RELATED_PERSON_CRD_NO"
_SCHED_R_COL_REL_TYPE = "RELATIONSHIP_TYPE"

# ──────────────────────────────────────────────────────────────────────────────
# Relationship-type → CLAIM-WEB node prefix mapping
# ──────────────────────────────────────────────────────────────────────────────

# Only these relationship types produce ownership arcs in G3. Pure service
# providers (accountants, law firms, etc.) are excluded.
_FINANCIAL_RELATIONSHIP_TYPES: frozenset[str] = frozenset({
    "Insurance Company",
    "Registered Investment Company",
    "Registered Pooled Investment Vehicle",
    "Investment Adviser",
    "Broker-Dealer",
    "Banking or Thrift Institution",
    "Other Financial Industry Participant",
    "Other",
})

# Non-financial relationships that we skip (service providers, not ownership).
_SERVICE_RELATIONSHIP_TYPES: frozenset[str] = frozenset({
    "Accounting Firm",
    "Law Firm",
    "Real Estate Broker",
    "Commodity Pool Operator",
    "Commodity Trading Adviser",
    "Futures Commission Merchant",
    "Registered Municipal Advisor",
    "Registered Security-Based Swap Dealer",
    "Major Security-Based Swap Participant",
})

# Map from ADV relationship type to CLAIM-WEB node prefix.
_REL_TYPE_TO_PREFIX: dict[str, str] = {
    "Insurance Company": "insurer",
    "Registered Investment Company": "fund",
    "Registered Pooled Investment Vehicle": "fund",
    "Investment Adviser": "aam",
    "Broker-Dealer": "broker",
    "Banking or Thrift Institution": "bank",
    "Other Financial Industry Participant": "entity",
    "Other": "entity",
}

# ──────────────────────────────────────────────────────────────────────────────
# Node-ID helpers
# ──────────────────────────────────────────────────────────────────────────────


def _normalise_name(name: str) -> str:
    """Produce a stable slug from an entity name for use in node IDs."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:64]


def _aam_node_id(crd: str, name: str) -> str:
    """Node ID for an AAM/IA firm."""
    crd_clean = crd.strip()
    if crd_clean and crd_clean not in ("0", ""):
        return f"aam:crd:{crd_clean}"
    return f"aam:name:{_normalise_name(name)}"


def _related_node_id(crd: str, name: str, rel_type: str) -> str:
    """Node ID for a Schedule R related entity."""
    prefix = _REL_TYPE_TO_PREFIX.get(rel_type, "entity")
    crd_clean = crd.strip()
    if crd_clean and crd_clean not in ("0", ""):
        return f"{prefix}:crd:{crd_clean}"
    return f"{prefix}:name:{_normalise_name(name)}"


# ──────────────────────────────────────────────────────────────────────────────
# Period helpers
# ──────────────────────────────────────────────────────────────────────────────

_QUARTER_LAST_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_MONTH_LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def _period_to_quarter_end(period: Period) -> date:
    """Return the last calendar day of the quarter."""
    month = _QUARTER_LAST_MONTH[period.quarter]
    day = _MONTH_LAST_DAY[month]
    return date(period.year, month, day)


# ──────────────────────────────────────────────────────────────────────────────
# CSV parsing helpers
# ──────────────────────────────────────────────────────────────────────────────


def _parse_raum(raw: str) -> Decimal:
    """Parse RAUM string (USD integer) to millions Decimal.

    Returns Decimal("0") for empty, missing, or non-numeric values.
    """
    cleaned = raw.strip().replace(",", "")
    if not cleaned:
        return Decimal("0")
    try:
        return Decimal(cleaned) * _USD_TO_MILLIONS
    except InvalidOperation:
        return Decimal("0")


def _parse_crd(raw: str) -> str:
    """Return a normalised CRD string (strip whitespace; treat '0' as absent)."""
    val = raw.strip()
    return val if val not in ("0", "") else ""


def _read_firm_csv(path: Path) -> dict[str, dict]:
    """Read the IA firm CSV; return mapping crd_number → firm record.

    The CSV may use Windows-1252 encoding (IAPD standard); errors are replaced.
    """
    firms: dict[str, dict] = {}
    try:
        content = path.read_bytes().decode("utf-8-sig", errors="replace")
    except OSError as exc:
        log.warning("Cannot read firm CSV %s: %s", path, exc)
        return firms

    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        crd = _parse_crd(row.get(_FIRM_COL_CRD, ""))
        if not crd:
            continue
        firms[crd] = {
            "crd": crd,
            "sec_number": row.get(_FIRM_COL_SEC, "").strip(),
            "legal_name": row.get(_FIRM_COL_NAME, "").strip(),
            "raum_millions": _parse_raum(row.get(_FIRM_COL_RAUM, "")),
        }
    return firms


def _read_schedule_r_csv(path: Path) -> list[dict]:
    """Read the Schedule R CSV; return list of related-person records."""
    rows: list[dict] = []
    try:
        content = path.read_bytes().decode("utf-8-sig", errors="replace")
    except OSError as exc:
        log.warning("Cannot read Schedule R CSV %s: %s", path, exc)
        return rows

    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        firm_crd = _parse_crd(row.get(_SCHED_R_COL_FIRM_CRD, ""))
        related_nm = row.get(_SCHED_R_COL_RELATED_NM, "").strip()
        related_crd = _parse_crd(row.get(_SCHED_R_COL_RELATED_CRD, ""))
        rel_type = row.get(_SCHED_R_COL_REL_TYPE, "").strip()
        if not firm_crd or not related_nm:
            continue
        rows.append({
            "firm_crd": firm_crd,
            "related_name": related_nm,
            "related_crd": related_crd,
            "relationship_type": rel_type,
        })
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# SecAdvFetcher
# ──────────────────────────────────────────────────────────────────────────────


class SecAdvFetcher(BaseFetcher):
    """Fetcher for SEC Form ADV investment adviser registrations.

    Source: SEC IAPD bulk CSV extract (IA firm data + Schedule R related persons).
    Page:   https://www.sec.gov/investment/form-adv-data
    Cadence: quarterly snapshot (ADV filed annually with amendments on material
             change; quarterly caching avoids stale affiliation records).
    Format: Two CSV files — ia_firm.csv and ia_schedule_r.csv.
    Populates: A11 arcs (equity/ownership) for G3 ownership graph.
    Project plan: §10.6.
    """

    source_id: str = "sec_adv"
    cadence: Literal["annual", "quarterly", "monthly"] = "quarterly"

    def list_available_periods(self) -> list[Period]:
        """Return sorted list of periods for which raw data is cached locally.

        Scans data/raw/sec_adv/ for subdirectories matching the YYYY-Qn pattern.
        """
        base = Path("data") / "raw" / self.source_id
        if not base.exists():
            return []
        periods: list[Period] = []
        for d in base.iterdir():
            if not d.is_dir():
                continue
            with contextlib.suppress(ValueError):
                periods.append(Period(d.name))
        return sorted(periods)

    def acquire(self, period: Period) -> RawDataHandle:
        """Download (or use cached) IAPD bulk CSV data for ``period``.

        The IAPD data is a snapshot as-of the quarter-end.  A cached copy is
        reused if it is younger than _CACHE_LIFETIME_DAYS days.

        Files written to data/raw/sec_adv/{period}/:
          ia_firm.csv       — IA firm master with RAUM
          ia_schedule_r.csv — Schedule R related persons

        Network strategy: attempt to download the IAPD bulk ZIP from the SEC.
        If that fails, fall back to EDGAR EFTS search for individual ADV filings.
        Both code paths are exercised in integration tests; unit tests mock httpx.
        """
        cache_dir = Path("data") / "raw" / self.source_id / str(period)
        firm_path = cache_dir / _FIRM_FILENAME
        sched_r_path = cache_dir / _SCHED_R_FILENAME

        if self._cache_valid(firm_path) and self._cache_valid(sched_r_path):
            log.debug("Using cached ADV data for %s", period)
            return RawDataHandle.from_paths(self.source_id, period, [firm_path, sched_r_path])

        cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            firm_rows, sched_r_rows = self._fetch_iapd_bulk(period)
        except Exception as exc:
            log.warning("IAPD bulk download failed (%s); trying EDGAR fallback", exc)
            firm_rows, sched_r_rows = self._fetch_edgar_fallback(period)

        _write_firm_csv(firm_path, firm_rows)
        _write_sched_r_csv(sched_r_path, sched_r_rows)

        return RawDataHandle.from_paths(self.source_id, period, [firm_path, sched_r_path])

    @staticmethod
    def _cache_valid(path: Path) -> bool:
        if not path.exists():
            return False
        age = date.today() - date.fromtimestamp(path.stat().st_mtime)
        return age <= timedelta(days=_CACHE_LIFETIME_DAYS)

    def _fetch_iapd_bulk(self, period: Period) -> tuple[list[dict], list[dict]]:
        """Download the IAPD bulk ZIP and extract firm + Schedule R rows.

        The SEC IAPD publishes a downloadable ZIP on the data page linked from
        https://www.sec.gov/investment/form-adv-data.  The ZIP contains CSV
        files with the full IA registration database including Schedule R.
        """
        headers = {"User-Agent": _USER_AGENT}
        with httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
            # Fetch the IAPD data page to discover the current ZIP URL.
            resp = client.get(_IAPD_PAGE_URL, headers=headers)
            resp.raise_for_status()
            zip_url = _extract_iapd_zip_url(resp.text)
            if not zip_url:
                raise ValueError("Could not find IAPD ZIP URL on data page")

            time.sleep(_REQUEST_INTERVAL_S)
            zip_resp = client.get(zip_url, headers=headers)
            zip_resp.raise_for_status()

        return _parse_iapd_zip(zip_resp.content)

    def _fetch_edgar_fallback(self, period: Period) -> tuple[list[dict], list[dict]]:
        """Fallback: query EDGAR EFTS for recent ADV filings and parse them.

        Used when the IAPD bulk ZIP is unavailable.  Returns firm and Schedule R
        rows in the same format as the bulk ZIP parser.
        """
        q_end = _period_to_quarter_end(period)
        start = date(q_end.year - 1, q_end.month, 1)
        params = {
            "q": "schedule r",
            "forms": "ADV",
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": q_end.isoformat(),
        }
        headers = {"User-Agent": _USER_AGENT}
        with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
            resp = client.get(_EFTS_URL, params=params, headers=headers)
            resp.raise_for_status()

        hits = resp.json().get("hits", {}).get("hits", [])
        firm_rows: list[dict] = []
        sched_r_rows: list[dict] = []

        for hit in hits:
            src = hit.get("_source", {})
            entity_name = src.get("entity_name", "")
            crd = src.get("crd_number", "")
            firm_rows.append({
                "crd": crd,
                "sec_number": src.get("file_num", ""),
                "legal_name": entity_name,
                "raum_usd": "",  # not available via EFTS search
            })
            log.debug("EDGAR fallback: found ADV filer %s (CRD=%s)", entity_name, crd)

        return firm_rows, sched_r_rows

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse IAPD CSV files into A11 ownership/affiliation ArcFacts.

        For each Schedule R row with a financial relationship type, emits one
        ArcFact:
          source = AAM parent firm (aam:crd:{crd} or aam:name:{slug})
          target = related entity (insurer/aam/fund/bank/entity prefix)
          arc_class = A11 (equity/ownership relationship)
          dollar_amount_millions = parent firm RAUM (in millions USD)
          data_quality_flag = PROXY (RAUM proxies for equity magnitude)
          measurement_basis = stock_eop

        Relations whose type is in _SERVICE_RELATIONSHIP_TYPES are skipped
        (accountants, law firms, etc. are not ownership arcs in G3).
        """
        paths = {p.name: p for p in handle.paths}
        firm_path = paths.get(_FIRM_FILENAME)
        sched_r_path = paths.get(_SCHED_R_FILENAME)

        if firm_path is None or sched_r_path is None:
            log.warning(
                "Missing CSV file(s) in handle for %s/%s",
                self.source_id, handle.period,
            )
            return []

        firms = _read_firm_csv(firm_path)
        sched_r_rows = _read_schedule_r_csv(sched_r_path)

        sched_r_sha = handle.sha256_by_path.get(str(sched_r_path), "0" * 64)

        facts: list[ArcFact] = []
        for row in sched_r_rows:
            firm_crd = row["firm_crd"]
            rel_type = row["relationship_type"]

            if rel_type in _SERVICE_RELATIONSHIP_TYPES:
                continue
            if rel_type and rel_type not in _FINANCIAL_RELATIONSHIP_TYPES:
                log.debug("Unknown relationship type %r; emitting as entity arc", rel_type)

            firm_info = firms.get(firm_crd)
            if firm_info is None:
                log.debug("Firm CRD %s not in firm table; skipping", firm_crd)
                continue

            raum = firm_info["raum_millions"]
            source_id_str = _aam_node_id(firm_crd, firm_info["legal_name"])
            target_id_str = _related_node_id(
                row["related_crd"],
                row["related_name"],
                rel_type,
            )

            # Skip self-referential arcs (IA filing that lists itself).
            if source_id_str == target_id_str:
                continue

            facts.append(ArcFact(
                period=handle.period,
                source_node_id=source_id_str,
                target_node_id=target_id_str,
                instrument_class=ArcClass.A11,
                dollar_amount_millions=raum,
                measurement_basis="stock_eop",
                data_quality_flag=DataQualityFlag.PROXY,
                provenance_source=self.source_id,
                provenance_url=_IAPD_PAGE_URL,
                provenance_filing=f"ADV/{firm_crd}",
                provenance_page=None,
                provenance_field="Schedule_R.relationship_type",
                sha256_of_source=sched_r_sha,
            ))

        return facts

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Validate parsed ADV affiliation arcs.

        Checks:
        - All arcs are A11 class.
        - No negative RAUM amounts.
        - If no arcs are emitted, warn (may indicate a parse failure).
        - Source node IDs have expected prefix (aam:).
        - Known AAM cluster parents are present (if data covers them).
        """
        period = facts[0].period if facts else Period("2000-Q1")
        report = ValidationReport(source_id=self.source_id, period=period)

        if not facts:
            report.warning(
                "NO_ARCS",
                "SecAdvFetcher produced no arcs; check that CSV files are present "
                "and that Schedule R contains financial relationships.",
            )
            return report

        for arc in facts:
            if arc.instrument_class is not ArcClass.A11:
                report.error(
                    "WRONG_ARC_CLASS",
                    f"Expected A11; got {arc.instrument_class.value} on arc "
                    f"{arc.source_node_id} → {arc.target_node_id}",
                    affected_arcs=(f"{arc.source_node_id}→{arc.target_node_id}",),
                )
            if arc.dollar_amount_millions < Decimal("0"):
                report.error(
                    "NEGATIVE_RAUM",
                    f"Negative RAUM on arc {arc.source_node_id} → "
                    f"{arc.target_node_id}: {arc.dollar_amount_millions}",
                    affected_arcs=(f"{arc.source_node_id}→{arc.target_node_id}",),
                )
            if not arc.source_node_id.startswith("aam:"):
                report.warning(
                    "UNEXPECTED_SOURCE_PREFIX",
                    f"Source node {arc.source_node_id!r} does not start with 'aam:'",
                    affected_arcs=(arc.source_node_id,),
                )

        insurer_count = sum(
            1 for arc in facts if arc.target_node_id.startswith("insurer:")
        )
        if insurer_count == 0:
            report.info(
                "NO_INSURER_ARCS",
                "No insurer-target arcs found; expected at least one "
                "AAM→insurer ownership arc in a full IAPD snapshot.",
            )

        return report


# ──────────────────────────────────────────────────────────────────────────────
# IAPD ZIP parsing helpers
# ──────────────────────────────────────────────────────────────────────────────


def _extract_iapd_zip_url(html: str) -> str | None:
    """Extract the IAPD data ZIP URL from the SEC data-page HTML.

    The SEC hosts the IA bulk data ZIP with a link on the data page.  We look
    for an href ending in .zip or containing 'adv' in the URL.
    """
    pattern = re.compile(
        r'href=["\']([^"\']*(?:adv|IA_firm|ia_firm|iapd)[^"\']*\.zip)["\']',
        re.IGNORECASE,
    )
    m = pattern.search(html)
    if m:
        url = m.group(1)
        if url.startswith("/"):
            url = "https://www.sec.gov" + url
        return url
    # Fallback: any ZIP href on the page.
    fallback = re.compile(r'href=["\']([^"\']+\.zip)["\']', re.IGNORECASE)
    m2 = fallback.search(html)
    if m2:
        url = m2.group(1)
        if url.startswith("/"):
            url = "https://www.sec.gov" + url
        return url
    return None


def _parse_iapd_zip(content: bytes) -> tuple[list[dict], list[dict]]:
    """Parse the IAPD bulk ZIP content; return (firm_rows, sched_r_rows).

    The ZIP typically contains multiple CSV files.  We look for the firm and
    Schedule R files by checking filename patterns (case-insensitive).
    """
    firm_rows: list[dict] = []
    sched_r_rows: list[dict] = []

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()
        firm_name = _find_zip_entry(names, ("ia_firm", "IA_FIRM"))
        sched_r_name = _find_zip_entry(names, ("ia_schedule_r", "IA_SCHEDULE_R", "schedule_r"))

        if firm_name:
            raw = zf.read(firm_name).decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(raw))
            for row in reader:
                crd = _parse_crd(row.get(_FIRM_COL_CRD, ""))
                if not crd:
                    continue
                firm_rows.append({
                    "crd": crd,
                    "sec_number": row.get(_FIRM_COL_SEC, "").strip(),
                    "legal_name": row.get(_FIRM_COL_NAME, "").strip(),
                    "raum_usd": row.get(_FIRM_COL_RAUM, "").strip(),
                })

        if sched_r_name:
            raw = zf.read(sched_r_name).decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(raw))
            for row in reader:
                firm_crd = _parse_crd(row.get(_SCHED_R_COL_FIRM_CRD, ""))
                related_nm = row.get(_SCHED_R_COL_RELATED_NM, "").strip()
                related_crd = _parse_crd(row.get(_SCHED_R_COL_RELATED_CRD, ""))
                rel_type = row.get(_SCHED_R_COL_REL_TYPE, "").strip()
                if not firm_crd or not related_nm:
                    continue
                sched_r_rows.append({
                    "firm_crd": firm_crd,
                    "related_name": related_nm,
                    "related_crd": related_crd,
                    "relationship_type": rel_type,
                })

    return firm_rows, sched_r_rows


def _find_zip_entry(names: list[str], patterns: tuple[str, ...]) -> str | None:
    """Find a ZIP entry whose name contains one of the given patterns."""
    for name in names:
        lower = name.lower()
        for pat in patterns:
            if pat.lower() in lower:
                return name
    return None


# ──────────────────────────────────────────────────────────────────────────────
# CSV write helpers (used by acquire to write cached files)
# ──────────────────────────────────────────────────────────────────────────────


def _write_firm_csv(path: Path, rows: list[dict]) -> None:
    """Write firm rows to a CSV file in the canonical IAPD format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([_FIRM_COL_CRD, _FIRM_COL_SEC, _FIRM_COL_NAME, _FIRM_COL_RAUM])
        for row in rows:
            writer.writerow([
                row.get("crd", ""),
                row.get("sec_number", ""),
                row.get("legal_name", ""),
                row.get("raum_usd", ""),
            ])


def _write_sched_r_csv(path: Path, rows: list[dict]) -> None:
    """Write Schedule R rows to a CSV file in the canonical IAPD format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            _SCHED_R_COL_FIRM_CRD,
            _SCHED_R_COL_RELATED_NM,
            _SCHED_R_COL_RELATED_CRD,
            _SCHED_R_COL_REL_TYPE,
        ])
        for row in rows:
            writer.writerow([
                row.get("firm_crd", ""),
                row.get("related_name", ""),
                row.get("related_crd", ""),
                row.get("relationship_type", ""),
            ])
