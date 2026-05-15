"""SEC Form N-MFP — Money Market Fund portfolio holdings fetcher (project plan §10.5).

Source: SEC EDGAR Form N-MFP filings.
Cadence: monthly (filed 5 days after month-end); the fetcher acquires the last-month
         filing of each calendar quarter and treats it as the quarter-end snapshot.
Format: XML with namespace http://www.sec.gov/edgar/nmfp.
Populates: A2 arcs (prime MMF holdings of FABNs / "Other Note" instruments).

SEC Form N-MFP requires every registered money market fund to report its complete
portfolio security-by-security on a monthly basis.  Holdings include CUSIPs,
issuer names, security categories, maturity dates, and amortized costs.

The "Other Note" category in N-MFP covers funding agreement-backed notes (FABNs)
and similar fixed-income instruments issued by insurance SPVs.  Aggregating prime
MMF holdings of "Other Note" instruments by CUSIP gives the A2 arc structure on
the MMF side of the network (project plan §4, arc class A2).

Arc direction (project plan §1):
  source_node_id = FABN issuer/SPV (the obligor)
  target_node_id = MMF fund series (the holder)
  instrument_class = ArcClass.A2

Node ID conventions:
  SPV (source): spv:cusip:{9-char-cusip}       if CUSIP available
                spv:name:{normalised-name}      otherwise (goes to unmapped registry)
  MMF (target): mmf:{series_id}                SEC series ID, e.g. "S000004059"
                mmf:cik:{zero-padded-cik}       if series ID absent

Dollar amounts: N-MFP reports amortizedCostAmt in raw USD integers.  The parser
multiplies by Decimal("0.000001") to produce millions of USD.

Data quality flag: DIRECT_MEASURED — SEC EDGAR regulatory filings with CUSIP-level
security disclosure.
Measurement basis: stock_eop — end-of-month portfolio snapshot (last month of quarter).

Schema versions handled (project plan §10.5 risk note):
  N-MFP  (2010–2015): original schema; fundCategory element may differ.
  N-MFP2 (2016+):     reformed schema; adds fundCategory, isNMFP1.
  The parser reads both by detecting the presence of fundCategory elements.

EDGAR acquisition strategy:
  1. Query EDGAR EFTS full-text search for N-MFP filings in a 3-week window
     after the quarter's last month-end (e.g. Jan 1–21 for Q4).
  2. For each filing found, derive the primary XML URL from the EDGAR submissions
     JSON (data.sec.gov/submissions/CIK{cik}.json → primaryDocument).
  3. Download and cache each XML under data/raw/sec_nmfp/{period}/.
  4. A manifest tracks all cached files; the 30-day cache lifetime avoids
     re-downloading monthly-final filings.

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

# EDGAR API endpoints
_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# N-MFP XML namespace (used in both pre- and post-2016 reform filings).
_NMFP_NS = "http://www.sec.gov/edgar/nmfp"
_NS = {"n": _NMFP_NS}

# Security category codes in N-MFP XML that correspond to funding agreement-backed
# notes (FABNs).  "Other Note" is the primary classification per SEC instructions;
# "Other Instrument" is used by a minority of filers for the same instruments.
_FABN_CATEGORIES: frozenset[str] = frozenset({
    "Other Note",
    "Other Instrument",
})

# Fund category codes that identify prime money market funds.  Government, treasury,
# and tax-exempt funds do not hold FABNs, so they are skipped.
_PRIME_FUND_CATEGORIES: frozenset[str] = frozenset({
    "Prime",
    "Institutional Prime",
    "Retail Prime",
    "Prime Retail",
    "Prime Institutional",
})

# Raw USD → millions of USD
_USD_TO_MM = Decimal("0.000001")

# Cache lifetime for per-filing XMLs.  N-MFP monthly filings are final once
# filed; 30 days is conservative and avoids re-downloading.
_CACHE_LIFETIME_DAYS = 30

# Minimum plausible total FABN holdings across all prime MMFs in a period.
# Zero is allowed; prime MMFs can and do hold zero FABNs in some periods.
_MIN_TOTAL_FABN_MM = Decimal("0")

# Inter-request delay enforcing ~6.7 req/sec (SEC EDGAR rate limit: 10 req/sec).
_REQUEST_INTERVAL_S = 0.15

# EDGAR EFTS returns up to 10 results per page.
_EFTS_PAGE_SIZE = 10

# ──────────────────────────────────────────────────────────────────────────────
# Calendar helpers
# ──────────────────────────────────────────────────────────────────────────────

_QUARTER_LAST_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_MONTH_LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}
_MONTH_TO_QUARTER = {
    1: 1, 2: 1, 3: 1,
    4: 2, 5: 2, 6: 2,
    7: 3, 8: 3, 9: 3,
    10: 4, 11: 4, 12: 4,
}


def _period_to_month_end(period: Period) -> date:
    """Return the last calendar day of the quarter (the N-MFP reporting date)."""
    month = _QUARTER_LAST_MONTH[period.quarter]
    day = _MONTH_LAST_DAY[month]
    return date(period.year, month, day)


def _period_to_filing_window(period: Period) -> tuple[date, date]:
    """Return the (start, end) date window for EDGAR EFTS discovery.

    N-MFP is due 5 days after month-end.  A 25-day window captures late filers.
    """
    month_end = _period_to_month_end(period)
    start = month_end + timedelta(days=1)
    end = month_end + timedelta(days=25)
    return start, end


def _parse_rep_period_date(date_str: str) -> date | None:
    """Parse repPeriodDate from N-MFP XML; returns None on failure."""
    try:
        return date.fromisoformat(date_str.strip())
    except (ValueError, AttributeError):
        return None


def _date_to_period(d: date) -> Period:
    """Return the calendar quarter containing the given date."""
    return Period(f"{d.year}-Q{_MONTH_TO_QUARTER[d.month]}")


# ──────────────────────────────────────────────────────────────────────────────
# Node-ID helpers
# ──────────────────────────────────────────────────────────────────────────────

_SAFE_NAME_RE = re.compile(r"[^a-z0-9_]")


def _normalise_name(name: str) -> str:
    """Return a URL-safe lower-case slug from an issuer name (max 60 chars)."""
    slug = _SAFE_NAME_RE.sub("_", name.lower().strip())
    return slug[:60].rstrip("_")


def _spv_node_id(cusip: str | None, issuer_name: str) -> str:
    """Return canonical CLAIM-WEB source node ID for a FABN issuer.

    Priority: CUSIP-based (traceable) > name-based (requires unmapped review).
    """
    if cusip and len(cusip) == 9 and cusip.isalnum():
        return f"spv:cusip:{cusip}"
    return f"spv:name:{_normalise_name(issuer_name)}"


def _mmf_node_id(series_id: str | None, cik: str) -> str:
    """Return canonical CLAIM-WEB target node ID for a MMF fund series."""
    if series_id and series_id.startswith("S"):
        return f"mmf:{series_id}"
    if cik:
        return f"mmf:cik:{cik.zfill(10)}"
    return "mmf:unknown"


# ──────────────────────────────────────────────────────────────────────────────
# XML element accessor
# ──────────────────────────────────────────────────────────────────────────────


def _text(elem: ET.Element, tag: str) -> str | None:
    """Return stripped text of a direct child element, or None if absent/empty."""
    child = elem.find(f"n:{tag}", _NS)
    if child is None:
        child = elem.find(tag)
    if child is None or not child.text:
        return None
    return child.text.strip() or None


# ──────────────────────────────────────────────────────────────────────────────
# XML parser
# ──────────────────────────────────────────────────────────────────────────────


def _parse_nmfp_xml(
    xml_bytes: bytes,
    source_url: str,
    sha256: str,
    target_period: Period | None = None,
) -> list[ArcFact]:
    """Parse a single N-MFP XML filing and return ArcFacts for FABN holdings.

    Only prime money market funds are processed; government/treasury/tax-exempt
    funds do not hold FABNs and are skipped.  Holdings with category not in
    ``_FABN_CATEGORIES`` are skipped.

    Parameters
    ----------
    xml_bytes:
        Raw bytes of the N-MFP XML document.
    source_url:
        The URL (or local path string) from which the XML was obtained.
        Stored in ArcFact.provenance_url.
    sha256:
        SHA-256 of xml_bytes.  Stored in ArcFact.sha256_of_source.
    target_period:
        If provided, only emit ArcFacts for this quarter.  Holdings whose
        repPeriodDate falls in a different quarter are skipped.

    Returns
    -------
    list of ArcFact — one per FABN-category holding in the filing.
    """
    facts: list[ArcFact] = []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        log.warning("N-MFP XML parse error at %s: %s", source_url, exc)
        return facts

    # Locate formData — handles both namespaced and non-namespaced XML.
    form_data = (
        root.find("n:formData", _NS)
        or root.find("formData")
    )
    if form_data is None:
        log.debug("N-MFP XML missing <formData> at %s", source_url)
        return facts

    gen_info = (
        form_data.find("n:genInfo", _NS)
        or form_data.find("genInfo")
    )
    if gen_info is None:
        log.debug("N-MFP XML missing <genInfo> at %s", source_url)
        return facts

    # ── Fund-level filters ────────────────────────────────────────────────────

    fund_category = _text(gen_info, "fundCategory") or ""
    if fund_category not in _PRIME_FUND_CATEGORIES:
        # Government, treasury, and tax-exempt funds do not hold FABNs; skip.
        log.debug(
            "N-MFP: skipping non-prime fund category %r at %s",
            fund_category,
            source_url,
        )
        return facts

    rep_date_str = _text(gen_info, "repPeriodDate") or ""
    rep_date = _parse_rep_period_date(rep_date_str)
    if rep_date is None:
        log.warning(
            "N-MFP: invalid repPeriodDate %r at %s", rep_date_str, source_url
        )
        return facts

    period = _date_to_period(rep_date)
    if target_period is not None and period != target_period:
        log.debug(
            "N-MFP: filing period %s ≠ target period %s; skipping %s",
            period,
            target_period,
            source_url,
        )
        return facts

    # ── Build fund (target) node ID ───────────────────────────────────────────

    series_id = _text(gen_info, "seriesId")
    fund_cik = _text(gen_info, "cik") or ""
    series_name = _text(gen_info, "seriesName") or "Unknown"
    target_node_id = _mmf_node_id(series_id, fund_cik)
    filing_id = f"N-MFP_{fund_cik}_{rep_date_str}"

    # ── Security-level holdings ───────────────────────────────────────────────

    # findall retrieves direct invstOrSec children; handles both namespaces.
    securities = form_data.findall("n:invstOrSec", _NS)
    if not securities:
        securities = form_data.findall("invstOrSec")

    for sec in securities:
        category = _text(sec, "category") or ""
        if category not in _FABN_CATEGORIES:
            continue  # Not a FABN-type holding; skip.

        # ── Amount ───────────────────────────────────────────────────────────
        amt_str = _text(sec, "amortizedCostAmt") or ""
        if not amt_str:
            log.debug(
                "N-MFP: missing amortizedCostAmt for %s in %s",
                _text(sec, "name"),
                source_url,
            )
            continue
        try:
            amount_mm = Decimal(amt_str) * _USD_TO_MM
        except InvalidOperation:
            log.debug(
                "N-MFP: unparseable amortizedCostAmt %r in %s", amt_str, source_url
            )
            continue

        if amount_mm <= Decimal("0"):
            continue

        # ── Source node ID (issuer) ───────────────────────────────────────────
        issuer_name = _text(sec, "name") or "Unknown Issuer"
        identifiers_elem = (
            sec.find("n:identifiers", _NS)
            or sec.find("identifiers")
        )
        cusip: str | None = None
        if identifiers_elem is not None:
            cusip = _text(identifiers_elem, "cusip")

        source_node_id = _spv_node_id(cusip, issuer_name)

        # ── Provenance field ──────────────────────────────────────────────────
        is_demand = _text(sec, "isDemandFeature") or "N"
        provenance_field = (
            f"invstOrSec/amortizedCostAmt"
            f"[category={category},isDemandFeature={is_demand}]"
        )

        facts.append(
            ArcFact(
                period=period,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                instrument_class=ArcClass.A2,
                dollar_amount_millions=amount_mm,
                measurement_basis="stock_eop",
                data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
                provenance_source="sec_nmfp",
                provenance_url=source_url,
                provenance_filing=filing_id,
                provenance_page=None,
                provenance_field=provenance_field,
                sha256_of_source=sha256,
            )
        )

    if facts:
        log.debug(
            "N-MFP: %s (%s) → %d FABN holdings for %s",
            series_name,
            series_id or fund_cik,
            len(facts),
            period,
        )

    return facts


# ──────────────────────────────────────────────────────────────────────────────
# SecNmfpFetcher
# ──────────────────────────────────────────────────────────────────────────────


class SecNmfpFetcher(BaseFetcher):
    """Fetcher for SEC Form N-MFP money market fund portfolio holdings.

    Source: https://www.sec.gov/form/n-mfp (EDGAR filings)
    Cadence: monthly filings; fetcher acquires the last month of each quarter.
    Format: XML, namespace http://www.sec.gov/edgar/nmfp.
    Populates: A2 arcs (prime MMF holdings of FABNs), project plan §10.5.
    """

    source_id: str = "sec_nmfp"
    cadence: Literal["monthly"] = "monthly"

    def __init__(self, data_root: Path | str | None = None) -> None:
        if data_root is None:
            data_root = Path("data/raw") / self.source_id
        self._data_root = Path(data_root)

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def list_available_periods(self) -> list[Period]:
        """Return sorted list of quarters for which XMLs are cached on disk."""
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
        """Download N-MFP XML filings for the last month of ``period``.

        Queries EDGAR EFTS for all N-MFP filings filed in the 25-day window
        after the quarter's month-end.  For each filer, downloads the primary
        XML document.  Results are cached in data/raw/sec_nmfp/{period}/ with
        a 30-day freshness window.

        The handle returned references every cached XML for this period.
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
                        "SecNmfpFetcher: using %d cached XMLs for %s",
                        len(xml_paths),
                        period,
                    )
                    return RawDataHandle.from_paths(self.source_id, period, xml_paths)
            except (ValueError, json.JSONDecodeError, KeyError):
                pass

        period_dir.mkdir(parents=True, exist_ok=True)

        start_dt, end_dt = _period_to_filing_window(period)
        accessions = self._discover_filings(start_dt, end_dt)
        log.info(
            "SecNmfpFetcher: discovered %d N-MFP filings for %s",
            len(accessions),
            period,
        )

        xml_paths: list[Path] = []
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            for info in accessions:
                try:
                    path = self._download_one(client, info, period_dir)
                    if path is not None:
                        xml_paths.append(path)
                except Exception as exc:
                    log.warning(
                        "SecNmfpFetcher: failed to download %s: %s",
                        info.get("accession_no"),
                        exc,
                    )

        manifest = {
            "fetched_at": datetime.utcnow().isoformat(),
            "period": str(period),
            "files": [p.name for p in xml_paths],
            "filing_count": len(xml_paths),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        log.info(
            "SecNmfpFetcher: cached %d XMLs for %s", len(xml_paths), period
        )
        return RawDataHandle.from_paths(self.source_id, period, xml_paths)

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse all cached N-MFP XML files and return FABN-related ArcFacts.

        Only prime money market funds are processed.  All ``_FABN_CATEGORIES``
        holdings are emitted as A2 arcs.
        """
        facts: list[ArcFact] = []
        for path in handle.paths:
            sha256 = handle.sha256_by_path.get(str(path), "0" * 64)
            try:
                xml_bytes = path.read_bytes()
            except OSError as exc:
                log.warning("SecNmfpFetcher: cannot read %s: %s", path, exc)
                continue
            file_facts = _parse_nmfp_xml(
                xml_bytes,
                source_url=str(path),
                sha256=sha256,
                target_period=handle.period,
            )
            facts.extend(file_facts)
        return facts

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Sanity checks on parsed N-MFP ArcFacts.

        Checks:
        1. All arc classes are A2 (FABN).
        2. All amounts are non-negative.
        3. Source nodes follow the spv:… convention.
        4. Target nodes follow the mmf:… convention.
        """
        period = facts[0].period if facts else Period("2000-Q1")
        report = ValidationReport(source_id=self.source_id, period=period)

        if not facts:
            report.info(
                "NO_FABN_HOLDINGS",
                "No FABN holdings found in prime MMF N-MFP filings "
                f"for {period}. This is permissible if prime MMFs hold no FABNs.",
            )
            return report

        for f in facts:
            if f.instrument_class != ArcClass.A2:
                report.error(
                    "WRONG_ARC_CLASS",
                    f"Expected A2 (FABN) arc, got {f.instrument_class.value} "
                    f"for {f.source_node_id} → {f.target_node_id}",
                )
            if f.dollar_amount_millions < Decimal("0"):
                report.warning(
                    "NEGATIVE_AMOUNT",
                    f"Negative amortized cost {f.dollar_amount_millions} MM "
                    f"for {f.source_node_id} → {f.target_node_id} in {f.period}",
                )
            if not f.source_node_id.startswith("spv:"):
                report.warning(
                    "UNEXPECTED_SOURCE_PREFIX",
                    f"Source node {f.source_node_id!r} does not start with 'spv:'",
                )
            if not f.target_node_id.startswith("mmf:"):
                report.warning(
                    "UNEXPECTED_TARGET_PREFIX",
                    f"Target node {f.target_node_id!r} does not start with 'mmf:'",
                )

        # Name-based SPV IDs require human review to resolve to canonical nodes.
        name_based = [
            f.source_node_id
            for f in facts
            if f.source_node_id.startswith("spv:name:")
        ]
        if name_based:
            report.info(
                "NAME_BASED_SPV_IDS",
                f"{len(name_based)} holdings lack CUSIPs and use name-based "
                f"source IDs; review via claimweb/registry/unmapped/. "
                f"Examples: {name_based[:3]}",
            )

        return report

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _discover_filings(self, start_dt: date, end_dt: date) -> list[dict]:
        """Query EDGAR EFTS for all N-MFP filings filed in [start_dt, end_dt].

        Returns list of {cik, accession_no, entity_name, file_date} dicts.
        Paginates until all results are retrieved.
        """
        results: list[dict] = []
        from_offset = 0

        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            while True:
                time.sleep(_REQUEST_INTERVAL_S)
                params = {
                    "forms": "N-MFP",
                    "dateRange": "custom",
                    "startdt": start_dt.isoformat(),
                    "enddt": end_dt.isoformat(),
                    "from": from_offset,
                }
                try:
                    resp = client.get(_EFTS_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError as exc:
                    log.error("EDGAR EFTS request failed: %s", exc)
                    break

                hits_obj = data.get("hits", {})
                hits = hits_obj.get("hits", [])
                if not hits:
                    break

                for hit in hits:
                    src = hit.get("_source", {})
                    ciks = src.get("ciks", [])
                    results.append({
                        "cik": ciks[0].lstrip("0") if ciks else "",
                        "cik_padded": ciks[0] if ciks else "",
                        "accession_no": src.get("accession_no", ""),
                        "entity_name": src.get("entity_name", ""),
                        "file_date": src.get("file_date", ""),
                    })

                from_offset += len(hits)
                total = hits_obj.get("total", {}).get("value", 0)
                if from_offset >= total:
                    break

        return results

    def _download_one(
        self,
        client: httpx.Client,
        info: dict,
        dest_dir: Path,
    ) -> Path | None:
        """Download the primary XML for a single N-MFP filing.

        Uses the EDGAR submissions JSON to resolve the exact primary document
        filename, then downloads the XML.  Returns the local path, or None
        on failure.
        """
        accession_no = info.get("accession_no", "")
        cik = info.get("cik", "").lstrip("0") or "0"
        cik_padded = info.get("cik_padded", cik.zfill(10))

        if not accession_no:
            return None

        safe_fn = f"{accession_no.replace('-', '')}.xml"
        dest_path = dest_dir / safe_fn
        if dest_path.exists():
            return dest_path

        # ── Step 1: resolve primary document via submissions JSON ─────────────
        time.sleep(_REQUEST_INTERVAL_S)
        sub_url = _SUBMISSIONS_URL.format(cik=cik_padded)
        try:
            sub_resp = client.get(sub_url)
            sub_resp.raise_for_status()
            sub_data = sub_resp.json()
        except httpx.HTTPError as exc:
            log.debug("Submissions JSON failed for CIK %s: %s", cik_padded, exc)
            sub_data = {}

        primary_doc = self._find_primary_doc(sub_data, accession_no)

        # ── Step 2: download the primary XML ─────────────────────────────────
        accession_dir = accession_no.replace("-", "")
        if primary_doc:
            xml_url = f"{_EDGAR_ARCHIVES}/{cik}/{accession_dir}/{primary_doc}"
        else:
            # Fallback: accession_no.xml is the most common N-MFP naming pattern.
            xml_url = f"{_EDGAR_ARCHIVES}/{cik}/{accession_dir}/{accession_no}.xml"

        time.sleep(_REQUEST_INTERVAL_S)
        try:
            xml_resp = client.get(xml_url)
            xml_resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("XML download failed for %s: %s", accession_no, exc)
            return None

        dest_path.write_bytes(xml_resp.content)
        log.debug("Cached N-MFP XML → %s", dest_path)
        return dest_path

    @staticmethod
    def _find_primary_doc(sub_data: dict, accession_no: str) -> str | None:
        """Extract the primary document filename from an EDGAR submissions JSON.

        The submissions JSON has parallel arrays filings.recent.accessionNumber[]
        and filings.recent.primaryDocument[].  Returns the primaryDocument value
        for the matching accession number, or None if not found.
        """
        recent = sub_data.get("filings", {}).get("recent", {})
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        for acc, doc in zip(accessions, primary_docs, strict=False):
            if acc == accession_no:
                return doc
        return None
