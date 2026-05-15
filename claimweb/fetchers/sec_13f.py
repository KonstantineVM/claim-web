"""SEC Form 13F — Institutional Investment Manager holdings fetcher (project plan §10.7).

Source: SEC EDGAR Form 13F-HR filings.
Cadence: Quarterly (filed within 45 days after each quarter-end).
Format: XML (informationTable), one file per filer.
Populates: A11 arcs (equity holdings) and A12 arcs (bond/PRN holdings) for the
           intra-AAM-cluster public security cross-holdings sub-graph.

Form 13F is required of any institutional investment manager with >$100M in 13F
securities on the last trading day of any month during the calendar year.  The
13F-HR (Holdings Report) lists all 13F securities held as of the quarter-end.

CLAIM-WEB uses 13F to populate G1 arcs representing public-security holdings by
alternative asset manager (AAM) groups affiliated with U.S. life insurers.  The
registry of target filers (``_MANAGER_REGISTRY``) covers the seven largest
PE-affiliated AAMs per project plan §3.5, node class I6.

Arc direction (project plan §1, source = liability side, target = asset holder):
  source_node_id = security issuer (``corp:cusip:{cusip6}`` for equities,
                   ``corp:name:{slug}`` when CUSIP is absent)
  target_node_id = institutional manager/holder (``aam:cik:{cik10}``)
  instrument_class = ArcClass.A11 for equity (sshPrnamtType == "SH")
                   = ArcClass.A12 for debt principal (sshPrnamtType == "PRN")

Holdings classified as options (putCall ∈ {"Put", "Call"}) are skipped;
they are derivative positions, not direct financial claims.

Node ID conventions:
  Security issuer (source): corp:cusip:{first-6-chars-of-CUSIP}
                             corp:name:{normalised-name}  (unmapped registry)
  AAM manager (target):     aam:cik:{zero-padded-cik-10-digits}

Dollar amounts: 13F value field is reported in thousands of USD.  The parser
multiplies by Decimal("0.001") to produce millions of USD.

Data quality flag: DIRECT_MEASURED — SEC EDGAR regulatory filings.
Measurement basis: stock_eop — quarter-end portfolio snapshot.

EDGAR acquisition strategy:
  For each target manager CIK in ``_MANAGER_REGISTRY``:
    1. Fetch the EDGAR submissions JSON (data.sec.gov/submissions/CIK{cik10}.json).
    2. Locate the 13F-HR filing whose filingDate falls in the 50-day window
       after the quarter-end (quarters end on Mar 31, Jun 30, Sep 30, Dec 31).
    3. Resolve the primary document (informationTable XML) URL from the accession
       number: https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/…
    4. Download and cache the XML under data/raw/sec_13f/{period}/{cik10}.xml.
       Cache lifetime: 90 days.

Rate limiting: SEC EDGAR policy allows ~10 req/sec with a descriptive User-Agent.
The fetcher enforces 150 ms between requests (≈ 6.7 req/sec).
"""
from __future__ import annotations

import contextlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
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
_REQUEST_INTERVAL_S = 0.15

# EDGAR API endpoints.
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# 13F XML namespace (modern filings post-2013).
_13F_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"
_NS = {"t": _13F_NS}

# Cache lifetime: 90 days (13F is quarterly and does not change after filing).
_CACHE_LIFETIME_DAYS = 90

# 13F value field is in thousands of USD.
_THOUSANDS_TO_MILLIONS = Decimal("0.001")

# 45 calendar-day statutory deadline plus 5-day buffer for late filers.
_FILING_WINDOW_DAYS = 50

# Minimum plausible total holdings (millions) across all target managers in
# any period.  Below this threshold the validate step raises a warning.
_MIN_TOTAL_HOLDINGS_MM = Decimal("1000")

# putCall values that identify options (not direct holdings).
_OPTION_LABELS: frozenset[str] = frozenset({"Put", "Call", "put", "call"})

# sshPrnamtType: "SH" = shares (equity → A11), "PRN" = principal (debt → A12).
_SH_TYPE = "SH"
_PRN_TYPE = "PRN"

# ──────────────────────────────────────────────────────────────────────────────
# Target manager registry  (project plan §3.5, I6 — PE-affiliated AAMs)
# ──────────────────────────────────────────────────────────────────────────────
# Keys are EDGAR CIK strings (no leading zeros); values are canonical names.
# CIKs are for the publicly-listed parent or principal filing entity.
# Subsidiaries may file separate 13Fs; those are not fetched here and should
# be added as the project registry expands.

_MANAGER_REGISTRY: dict[str, str] = {
    "1357615": "Apollo Global Management Inc",
    "1393818": "Blackstone Inc",
    "1404912": "KKR & Co Inc",
    "1001085": "Brookfield Asset Management Inc",
    "1527590": "The Carlyle Group Inc",
    "1364742": "BlackRock Inc",
    "1555280": "Ares Management Corp",
}

# ──────────────────────────────────────────────────────────────────────────────
# Calendar helpers
# ──────────────────────────────────────────────────────────────────────────────

_QUARTER_LAST_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_MONTH_LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def _period_to_quarter_end(period: Period) -> date:
    """Return the last calendar day of the quarter."""
    month = _QUARTER_LAST_MONTH[period.quarter]
    day = _MONTH_LAST_DAY[month]
    return date(period.year, month, day)


def _period_to_filing_window(period: Period) -> tuple[date, date]:
    """Return (start, end) date window for 13F-HR discovery.

    13F is due 45 calendar days after quarter-end.  A 50-day window captures
    the deadline plus 5 days of grace for late filers.
    """
    qend = _period_to_quarter_end(period)
    start = qend + timedelta(days=1)
    end = qend + timedelta(days=_FILING_WINDOW_DAYS)
    return start, end


def _filing_date_in_window(filing_date_str: str, start: date, end: date) -> bool:
    """Return True if the filing date falls within [start, end]."""
    try:
        fd = date.fromisoformat(filing_date_str.strip())
        return start <= fd <= end
    except (ValueError, AttributeError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Node-ID helpers
# ──────────────────────────────────────────────────────────────────────────────

_SAFE_RE = re.compile(r"[^a-z0-9_]")


def _normalise_name(name: str) -> str:
    """Return a URL-safe lower-case slug from an issuer name (max 60 chars)."""
    slug = _SAFE_RE.sub("_", name.lower().strip())
    return slug[:60].rstrip("_")


def _issuer_node_id(cusip: str | None, name: str) -> str:
    """Return canonical CLAIM-WEB source node ID for a 13F security issuer.

    Uses first 6 CUSIP chars (issuer code) when CUSIP is present and long
    enough.  Otherwise falls back to name-based ID (goes to unmapped registry).
    """
    if cusip and len(cusip) >= 6 and cusip[:6].isalnum():
        return f"corp:cusip:{cusip[:6].upper()}"
    return f"corp:name:{_normalise_name(name)}"


def _manager_node_id(cik: str) -> str:
    """Return canonical CLAIM-WEB target node ID for an AAM manager.

    CIK is zero-padded to 10 digits for stability.
    """
    return f"aam:cik:{cik.zfill(10)}"


# ──────────────────────────────────────────────────────────────────────────────
# XML element accessor
# ──────────────────────────────────────────────────────────────────────────────


def _text(elem: ET.Element, tag: str) -> str | None:
    """Return stripped text of a direct child element, or None if absent/empty.

    Handles both namespaced (``t:{tag}``) and bare element names so the same
    code works for the modern and legacy 13F schemas.
    """
    child = elem.find(f"t:{tag}", _NS)
    if child is None:
        child = elem.find(tag)
    if child is None or not child.text:
        return None
    return child.text.strip() or None


# ──────────────────────────────────────────────────────────────────────────────
# XML parser
# ──────────────────────────────────────────────────────────────────────────────


def _parse_13f_xml(
    xml_bytes: bytes,
    manager_cik: str,
    period: Period,
    source_url: str,
    sha256: str,
    unmapped_issuers: list[dict] | None = None,
) -> list[ArcFact]:
    """Parse a single 13F informationTable XML and return ArcFacts.

    Each <infoTable> row becomes one ArcFact (equity or debt holding) unless:
    - putCall is "Put" or "Call" (options, skipped)
    - value is zero or negative
    - CUSIP is absent and name is blank (no identifier, skipped)

    Parameters
    ----------
    xml_bytes: Raw bytes of the informationTable XML document.
    manager_cik: CIK of the filing manager (for target node ID).
    period: Reporting quarter.
    source_url: URL or file path from which the XML was obtained.
    sha256: SHA-256 hex digest of xml_bytes.
    unmapped_issuers: Mutable list; name-based issuers are appended for registry.

    Returns
    -------
    list[ArcFact] — one per qualifying holding in the filing.
    """
    if unmapped_issuers is None:
        unmapped_issuers = []

    facts: list[ArcFact] = []
    target_node_id = _manager_node_id(manager_cik)

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        log.warning("13F XML parse error at %s: %s", source_url, exc)
        return facts

    # informationTable may be the root element itself or wrapped in an outer
    # element for some older filings.  Normalise to a list of <infoTable> elems.
    if root.tag in (
        f"{{{_13F_NS}}}informationTable",
        "informationTable",
    ):
        info_tables = (
            root.findall("t:infoTable", _NS)
            or root.findall("infoTable")
        )
    else:
        info_tables = (
            root.findall(".//t:infoTable", _NS)
            or root.findall(".//infoTable")
        )

    for row in info_tables:
        # ── Option filter ─────────────────────────────────────────────────────
        put_call = _text(row, "putCall") or ""
        if put_call.strip() in _OPTION_LABELS:
            continue

        # ── Amount ────────────────────────────────────────────────────────────
        value_str = _text(row, "value") or ""
        if not value_str:
            log.debug("13F: missing <value> in %s", source_url)
            continue
        try:
            amount_mm = Decimal(value_str) * _THOUSANDS_TO_MILLIONS
        except InvalidOperation:
            log.debug("13F: unparseable <value> %r in %s", value_str, source_url)
            continue
        if amount_mm <= Decimal("0"):
            continue

        # ── Arc class ─────────────────────────────────────────────────────────
        shrs_elem = _get_shrs_elem(row)
        shr_type = _text(shrs_elem, "sshPrnamtType") if shrs_elem is not None else None
        arc_class = ArcClass.A12 if shr_type == _PRN_TYPE else ArcClass.A11

        # ── Source node ID (issuer) ───────────────────────────────────────────
        issuer_name = _text(row, "nameOfIssuer") or ""
        cusip = _text(row, "cusip") or ""

        source_node_id = _issuer_node_id(cusip or None, issuer_name)

        if not issuer_name and not cusip:
            log.debug("13F: row with no issuer name or CUSIP in %s; skipping", source_url)
            continue

        if source_node_id.startswith("corp:name:"):
            unmapped_issuers.append({
                "name": issuer_name,
                "title_of_class": _text(row, "titleOfClass") or "",
                "value_thousands": value_str,
            })

        # ── Provenance ────────────────────────────────────────────────────────
        title = _text(row, "titleOfClass") or ""
        provenance_field = f"13F-HR/informationTable/infoTable[cusip={cusip or 'none'},titleOfClass={title}]"

        facts.append(
            ArcFact(
                period=period,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                instrument_class=arc_class,
                dollar_amount_millions=amount_mm,
                measurement_basis="stock_eop",
                data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
                provenance_source="sec_13f",
                provenance_url=source_url,
                provenance_filing=None,
                provenance_page=None,
                provenance_field=provenance_field,
                sha256_of_source=sha256,
            )
        )

    log.debug(
        "13F: CIK %s period %s → %d holdings parsed from %s",
        manager_cik,
        period,
        len(facts),
        source_url,
    )
    return facts


def _get_shrs_elem(row: ET.Element) -> ET.Element | None:
    """Return the <shrsOrPrnAmt> child of a row, namespace-tolerant."""
    return row.find("t:shrsOrPrnAmt", _NS) or row.find("shrsOrPrnAmt")


# ──────────────────────────────────────────────────────────────────────────────
# EDGAR submissions helper
# ──────────────────────────────────────────────────────────────────────────────


def _find_13f_hr_for_period(
    sub_data: dict,
    start: date,
    end: date,
) -> dict | None:
    """Return the first 13F-HR filing entry in [start, end] from submissions JSON.

    The submissions JSON has parallel arrays under filings.recent.  We look for
    form == "13F-HR" (not amendments "13F-HR/A") with filingDate in window.

    Returns a dict with keys: accessionNumber, primaryDocument, filingDate.
    Returns None if no matching filing is found.
    """
    recent = sub_data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    filing_dates = recent.get("filingDate", [])

    for form, acc, doc, fdate in zip(
        forms, accessions, primary_docs, filing_dates, strict=False
    ):
        if form != "13F-HR":
            continue
        if _filing_date_in_window(fdate, start, end):
            return {
                "accessionNumber": acc,
                "primaryDocument": doc,
                "filingDate": fdate,
            }

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Sec13fFetcher
# ──────────────────────────────────────────────────────────────────────────────


class Sec13fFetcher(BaseFetcher):
    """Fetcher for SEC Form 13F institutional investment manager holdings.

    Source: https://www.sec.gov/form/13f (EDGAR filings)
    Cadence: quarterly, ≤ 45 calendar days after quarter-end.
    Format: XML informationTable document per 13F-HR filing.
    Populates: A11 arcs (equity) and A12 arcs (debt) from _MANAGER_REGISTRY
               managers into the intra-AAM-cluster cross-holdings sub-graph.
    Project plan: §10.7.
    """

    source_id: str = "sec_13f"
    cadence: Literal["quarterly"] = "quarterly"

    def __init__(self, data_root: Path | str | None = None) -> None:
        if data_root is None:
            data_root = Path("data/raw") / self.source_id
        self._data_root = Path(data_root)

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def list_available_periods(self) -> list[Period]:
        """Return sorted list of quarters for which 13F XMLs are cached on disk."""
        periods: set[Period] = set()
        if not self._data_root.exists():
            return []
        for entry in self._data_root.iterdir():
            if not entry.is_dir():
                continue
            with contextlib.suppress(ValueError):
                periods.add(Period(entry.name))
        return sorted(periods)

    def acquire(self, period: Period) -> RawDataHandle:
        """Download 13F-HR informationTable XMLs for all managers in the period.

        For each CIK in ``_MANAGER_REGISTRY``:
        1. Fetch EDGAR submissions JSON.
        2. Find the 13F-HR filing within the 50-day post-quarter-end window.
        3. Download the informationTable XML.
        4. Cache under data/raw/sec_13f/{period}/{cik10}.xml.

        Returns a RawDataHandle referencing all cached XMLs for this period.
        A per-period manifest tracks fetched_at, so the cache is valid for
        ``_CACHE_LIFETIME_DAYS`` days before re-downloading.
        """
        period_dir = self._data_root / str(period)
        manifest_path = period_dir / "_manifest.json"

        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                fetched_at = datetime.fromisoformat(manifest.get("fetched_at", ""))
                if datetime.utcnow() - fetched_at <= timedelta(days=_CACHE_LIFETIME_DAYS):
                    xml_paths = [
                        period_dir / fn
                        for fn in manifest.get("files", [])
                        if (period_dir / fn).exists()
                    ]
                    log.info(
                        "Sec13fFetcher: using %d cached XMLs for %s",
                        len(xml_paths),
                        period,
                    )
                    return RawDataHandle.from_paths(self.source_id, period, xml_paths)
            except (ValueError, json.JSONDecodeError, KeyError):
                pass

        period_dir.mkdir(parents=True, exist_ok=True)
        start_dt, end_dt = _period_to_filing_window(period)

        xml_paths: list[Path] = []
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            for cik, name in _MANAGER_REGISTRY.items():
                try:
                    path = self._fetch_one_manager(
                        client, cik, name, period, period_dir, start_dt, end_dt
                    )
                    if path is not None:
                        xml_paths.append(path)
                except Exception as exc:
                    log.warning(
                        "Sec13fFetcher: failed to fetch CIK %s (%s): %s",
                        cik,
                        name,
                        exc,
                    )

        manifest = {
            "fetched_at": datetime.utcnow().isoformat(),
            "period": str(period),
            "files": [p.name for p in xml_paths],
            "manager_count": len(xml_paths),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        log.info(
            "Sec13fFetcher: cached %d 13F XMLs for %s",
            len(xml_paths),
            period,
        )
        return RawDataHandle.from_paths(self.source_id, period, xml_paths)

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse all cached 13F informationTable XMLs and return ArcFacts.

        Each XML file name encodes the manager CIK (``{cik10}.xml``).  The CIK
        is used to build the target node ID.

        Unknown issuers (no CUSIP) are written to the unmapped registry at
        ``claimweb/registry/unmapped/sec_13f_{period}.json``.
        """
        facts: list[ArcFact] = []
        unmapped: list[dict] = []

        for path in handle.paths:
            sha256 = handle.sha256_by_path.get(str(path), "0" * 64)
            cik = _cik_from_filename(path.name)
            if cik is None:
                log.warning("Sec13fFetcher: cannot derive CIK from filename %s", path.name)
                continue
            try:
                xml_bytes = path.read_bytes()
            except OSError as exc:
                log.warning("Sec13fFetcher: cannot read %s: %s", path, exc)
                continue
            file_facts = _parse_13f_xml(
                xml_bytes,
                manager_cik=cik,
                period=handle.period,
                source_url=str(path),
                sha256=sha256,
                unmapped_issuers=unmapped,
            )
            facts.extend(file_facts)

        if unmapped:
            _write_unmapped(handle.period, unmapped)

        return facts

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Sanity checks on parsed 13F ArcFacts.

        Checks:
        1. All arc classes are A11 or A12.
        2. All amounts are non-negative.
        3. Source nodes follow the corp:… convention.
        4. Target nodes follow the aam:cik:… convention.
        5. Total holdings plausibility (≥ _MIN_TOTAL_HOLDINGS_MM).
        """
        period = facts[0].period if facts else Period("2000-Q1")
        report = ValidationReport(source_id=self.source_id, period=period)

        if not facts:
            report.info(
                "NO_13F_HOLDINGS",
                "No 13F holdings parsed for any target manager in "
                f"{period}.  Verify that filings exist for this period.",
            )
            return report

        total_mm = Decimal("0")
        for f in facts:
            if f.instrument_class not in (ArcClass.A11, ArcClass.A12):
                report.error(
                    "WRONG_ARC_CLASS",
                    f"Expected A11 or A12 arc, got {f.instrument_class.value} "
                    f"for {f.source_node_id} → {f.target_node_id}",
                )
            if f.dollar_amount_millions < Decimal("0"):
                report.warning(
                    "NEGATIVE_AMOUNT",
                    f"Negative holding value {f.dollar_amount_millions} MM "
                    f"for {f.source_node_id} → {f.target_node_id} in {f.period}",
                )
            if not f.source_node_id.startswith("corp:"):
                report.warning(
                    "UNEXPECTED_SOURCE_PREFIX",
                    f"Source node {f.source_node_id!r} does not start with 'corp:'",
                )
            if not f.target_node_id.startswith("aam:cik:"):
                report.warning(
                    "UNEXPECTED_TARGET_PREFIX",
                    f"Target node {f.target_node_id!r} does not start with 'aam:cik:'",
                )
            total_mm += f.dollar_amount_millions

        if total_mm < _MIN_TOTAL_HOLDINGS_MM:
            report.warning(
                "LOW_TOTAL_HOLDINGS",
                f"Total holdings {total_mm:.1f} MM is below the plausibility "
                f"threshold {_MIN_TOTAL_HOLDINGS_MM} MM.  Check that all target "
                f"managers filed 13Fs for {period}.",
            )

        name_based = [
            f.source_node_id
            for f in facts
            if f.source_node_id.startswith("corp:name:")
        ]
        if name_based:
            report.info(
                "NAME_BASED_ISSUER_IDS",
                f"{len(name_based)} holdings lack CUSIPs and use name-based "
                f"source IDs; review via claimweb/registry/unmapped/sec_13f_*.  "
                f"Examples: {name_based[:3]}",
            )

        return report

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _fetch_one_manager(
        self,
        client: httpx.Client,
        cik: str,
        name: str,
        period: Period,
        dest_dir: Path,
        start_dt: date,
        end_dt: date,
    ) -> Path | None:
        """Fetch one manager's 13F-HR XML for the target period.

        Returns the local Path of the cached XML, or None if not found/failed.
        """
        cik_padded = cik.zfill(10)
        dest_path = dest_dir / f"{cik_padded}.xml"
        if dest_path.exists():
            return dest_path

        # Step 1: fetch submissions JSON for this CIK.
        time.sleep(_REQUEST_INTERVAL_S)
        sub_url = _SUBMISSIONS_URL.format(cik=cik_padded)
        try:
            sub_resp = client.get(sub_url)
            sub_resp.raise_for_status()
            sub_data = sub_resp.json()
        except httpx.HTTPError as exc:
            log.warning(
                "Sec13fFetcher: submissions JSON failed for %s (%s): %s",
                cik,
                name,
                exc,
            )
            return None

        # Step 2: find the 13F-HR filing for this period.
        filing = _find_13f_hr_for_period(sub_data, start_dt, end_dt)
        if filing is None:
            log.info(
                "Sec13fFetcher: no 13F-HR found for CIK %s (%s) in %s",
                cik,
                name,
                period,
            )
            return None

        accession_no = filing["accessionNumber"]
        primary_doc = filing.get("primaryDocument") or ""
        accession_dir = accession_no.replace("-", "")

        # Step 3: download the informationTable XML.
        time.sleep(_REQUEST_INTERVAL_S)
        if primary_doc:
            xml_url = f"{_EDGAR_ARCHIVES}/{cik}/{accession_dir}/{primary_doc}"
        else:
            # Fallback: common naming pattern for 13F informationTable.
            xml_url = (
                f"{_EDGAR_ARCHIVES}/{cik}/{accession_dir}/"
                f"form13fInfoTable.xml"
            )

        try:
            xml_resp = client.get(xml_url)
            xml_resp.raise_for_status()
        except httpx.HTTPError:
            # Second fallback: try the accession number as filename.
            alt_url = f"{_EDGAR_ARCHIVES}/{cik}/{accession_dir}/{accession_no}.xml"
            try:
                time.sleep(_REQUEST_INTERVAL_S)
                xml_resp = client.get(alt_url)
                xml_resp.raise_for_status()
                xml_url = alt_url
            except httpx.HTTPError as exc2:
                log.warning(
                    "Sec13fFetcher: XML download failed for CIK %s accession %s: %s",
                    cik,
                    accession_no,
                    exc2,
                )
                return None

        dest_path.write_bytes(xml_resp.content)
        log.debug(
            "Sec13fFetcher: cached CIK %s (%s) 13F XML → %s",
            cik,
            name,
            dest_path,
        )
        return dest_path


# ──────────────────────────────────────────────────────────────────────────────
# Filesystem helpers
# ──────────────────────────────────────────────────────────────────────────────


def _cik_from_filename(filename: str) -> str | None:
    """Extract CIK string from cached XML filename ({cik10}.xml).

    Returns the CIK without leading zeros, or None if the filename does not
    match the expected pattern.
    """
    m = re.match(r"^(\d{10})\.xml$", filename)
    if not m:
        return None
    return m.group(1).lstrip("0") or "0"


def _write_unmapped(period: Period, issuers: list[dict]) -> None:
    """Write name-based issuer IDs to the unmapped registry for human review."""
    registry_dir = Path("claimweb/registry/unmapped")
    registry_dir.mkdir(parents=True, exist_ok=True)
    out_path = registry_dir / f"sec_13f_{period}.json"
    out_path.write_text(
        json.dumps(
            {"period": str(period), "unmapped_issuers": issuers},
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info(
        "Sec13fFetcher: wrote %d unmapped issuers to %s", len(issuers), out_path
    )
