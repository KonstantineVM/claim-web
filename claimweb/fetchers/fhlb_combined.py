"""FHLB Office of Finance Combined Financial Report fetcher (project plan §10.4).

Source: https://www.fhlb-of.com/ofweb_userWeb/pageBuilder/fhlbank-financial-data-36
Cadence: quarterly, ~60-90 days after end-of-quarter.
Format: PDF with structured tables (text-based, pdfplumber-extractable).
Populates: A3 arcs (FHLB advances → member institutions), I3 nodes.

Arc direction convention (per project plan §1 and §4):
  source_node_id = issuer of the obligation = the member/borrower (liability on member's books)
  target_node_id = holder of the claim    = FHLB system (asset on FHLB's books)

The Combined Financial Report provides two types of A3 data:
  1. System-wide insurance-member advances aggregate (direct measurement).
  2. Named top-N advance users from the insurance category, where disclosed.

Dollar amounts: advances-by-member-type table is in billions USD; top-member table
is in millions USD. Both are converted to millions in the emitted ArcFacts.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import httpx
import pdfplumber
from bs4 import BeautifulSoup

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_URL = "https://www.fhlb-of.com/ofweb_userWeb/pageBuilder/fhlbank-financial-data-36"
_USER_AGENT = (
    "CLAIM-WEB academic research; "
    "contact: researchers studying systemic risk in life insurance sector"
)
_REQUEST_TIMEOUT = 60.0  # seconds

# FHLB system-wide node ID (lender/holder side for A3 arcs)
_FHLB_SYSTEM_NODE = "fhlb:system"

# Aggregate insurance-member node used when individual insurers are not identified
_INSURER_AGGREGATE_NODE = "insurer:aggregate_fhlb_members"

# Minimum plausible insurance-member advance total (billions).
# FHLB insurance-member advances have never been below $20B in the modern era.
_MIN_INSURANCE_ADVANCES_BILLIONS = Decimal("10")

# ---------------------------------------------------------------------------
# Quarter-label patterns for scraping the FHLB index page
# ---------------------------------------------------------------------------

_QUARTER_LABEL_RE = re.compile(
    r"(?:"
    r"(First|Second|Third|Fourth)\s+Quarter[\s,]+(\d{4})"
    r"|"
    r"Q([1-4])\s+(\d{4})"
    r"|"
    r"(\d{4})[\s-]+Q([1-4])"
    r"|"
    r"(?:March|June|September|December)\s+\d{1,2},?\s+(\d{4})"
    r")",
    re.IGNORECASE,
)

_ORDINAL_TO_Q: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4,
}
_MONTH_TO_Q: dict[str, int] = {
    "march": 1, "june": 2, "september": 3, "december": 4,
}

# ---------------------------------------------------------------------------
# Text-extraction patterns for the CFR tables
# ---------------------------------------------------------------------------

# "Insurance Companies  89.7  87.4"  (amounts in billions; first number = current period)
_INSURANCE_ROW_RE = re.compile(
    r"Insurance\s+Companies?\s+([\d,]+\.?\d*)",
    re.IGNORECASE,
)

# "Total Advances  595.7  585.2"
_TOTAL_ADVANCES_RE = re.compile(
    r"Total\s+Advances?\s+([\d,]+\.?\d*)",
    re.IGNORECASE,
)

# Top-N table entry: "MetLife Insurance Company of Connecticut CT 8234"
# Captures: full name, two-letter state code, integer amount in millions.
# Uses \s+ (not \s{2,}) because pdfplumber may collapse multiple PDF spaces to one.
_MEMBER_ROW_RE = re.compile(
    r"^(.+?)\s+([A-Z]{2})\s+([\d,]+)\s*$",
    re.MULTILINE,
)

# Period from report header: "For the Quarter Ended December 31, 2024"
_HEADER_PERIOD_RE = re.compile(
    r"(?:Quarter\s+Ended|Three\s+Months\s+Ended)\s+"
    r"(March|June|September|December)\s+\d{1,2},?\s+(\d{4})",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Entity-name → canonical node-ID mapping
# ---------------------------------------------------------------------------

_MEMBER_NAME_TO_NODE: dict[str, str] = {
    # MetLife / Brighthouse
    "Metropolitan Life Insurance Company": "insurer:MET",
    "MetLife Insurance Company of Connecticut": "insurer:MET_CTIC",
    "Brighthouse Life Insurance Company": "insurer:BHF",
    # Lincoln National
    "Lincoln National Life Insurance Company": "insurer:LNC",
    "Lincoln Benefit Life Company": "insurer:LNC_BENEFIT",
    # Athene (Apollo)
    "Athene Annuity and Life Insurance Company": "insurer:ATH_ALIC",
    "Athene Annuity and Life Assurance Company": "insurer:ATH_ALAC",
    "Athene Life Insurance Company of New York": "insurer:ATH_NY",
    # Corebridge / AIG
    "American General Life Insurance Company": "insurer:CRBG_AGLI",
    "United States Life Insurance Company in the City of New York": "insurer:CRBG_USLIC",
    "The Variable Annuity Life Insurance Company": "insurer:CRBG_VALIC",
    # Transamerica (Aegon)
    "Transamerica Life Insurance Company": "insurer:TRMK_LIFE",
    "Transamerica Financial Life Insurance Company": "insurer:TRMK_FLIC",
    # Principal
    "Principal Life Insurance Company": "insurer:PFG_LIFE",
    "Principal National Life Insurance Company": "insurer:PFG_NAT",
    # Prudential
    "Prudential Insurance Company of America": "insurer:PRU",
    "Primerica Life Insurance Company": "insurer:PRI",
    # Voya / ReliaStar
    "ReliaStar Life Insurance Company": "insurer:VOYA_RLIC",
    "Security-Connecticut Life Insurance Company": "insurer:VOYA_SCLIC",
    "Voya Insurance and Annuity Company": "insurer:VOYA_IAC",
    # Global Atlantic (Goldman Sachs)
    "Commonwealth Annuity and Life Insurance Company": "insurer:GAF_CALIC",
    "First Allmerica Financial Life Insurance and Annuity Company": "insurer:GAF_FAF",
    "Accordia Life and Annuity Company": "insurer:GAF_ALAC",
    # Nationwide
    "Nationwide Life Insurance Company": "insurer:NWM_NLIC",
    "Nationwide Life and Annuity Insurance Company": "insurer:NWM_NLAIC",
    # New York Life
    "New York Life Insurance Company": "insurer:NYL",
    "New York Life Insurance and Annuity Corporation": "insurer:NYL_ANNU",
    # TIAA
    "Teachers Insurance and Annuity Association of America": "insurer:TIAA",
    # F&G (Fidelity National Financial)
    "Fidelity and Guaranty Life Insurance Company": "insurer:FG",
    "Fidelity and Guaranty Life Insurance Company of New York": "insurer:FG_NY",
    # American Equity (Brookfield)
    "American Equity Investment Life Insurance Company": "insurer:AEL",
    "American Equity Investment Life Insurance Company of New York": "insurer:AEL_NY",
    # Protective Life (Dai-ichi)
    "Protective Life Insurance Company": "insurer:PL",
    # Pacific Life
    "Pacific Life Insurance Company": "insurer:PAC",
    # Unum
    "Unum Life Insurance Company of America": "insurer:UNM",
    # Sun Life
    "Sun Life Insurance and Annuity Company of New York": "insurer:SLF_NY",
    # Equitable / AXA
    "Equitable Financial Life Insurance Company": "insurer:EQH",
    "Equitable Financial Life Insurance Company of New York": "insurer:EQH_NY",
}


def _canonicalize_member_name(raw_name: str) -> str | None:
    """Return the canonical node ID for a member name, or None if unmapped."""
    name = raw_name.strip()
    if name in _MEMBER_NAME_TO_NODE:
        return _MEMBER_NAME_TO_NODE[name]
    # Try case-insensitive match
    lower = name.lower()
    for key, node_id in _MEMBER_NAME_TO_NODE.items():
        if key.lower() == lower:
            return node_id
    return None


def _slug(name: str) -> str:
    """Create a filesystem-safe slug from an entity name (for unmapped IDs)."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")
    return slug[:60]


# ---------------------------------------------------------------------------
# Period-from-quarter-label helper
# ---------------------------------------------------------------------------


def _label_to_period(label: str) -> Period | None:
    """Parse a human-readable quarter label into a Period, or return None."""
    m = _QUARTER_LABEL_RE.search(label)
    if not m:
        return None
    ordinal, year1, q2, year2, year3, q3, year4 = m.groups()
    if ordinal and year1:
        q = _ORDINAL_TO_Q.get(ordinal.lower())
        year = int(year1)
    elif q2 and year2:
        q, year = int(q2), int(year2)
    elif year3 and q3:
        q, year = int(q3), int(year3)
    elif year4:
        # Month-based: "For the Quarter Ended December 31, 2024" → Q4
        # Extract month from original label
        month_m = re.search(r"(March|June|September|December)", label, re.IGNORECASE)
        if not month_m:
            return None
        q = _MONTH_TO_Q[month_m.group(1).lower()]
        year = int(year4)
    else:
        return None
    try:
        return Period(f"{year}-Q{q}")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# FhlbCombinedFetcher
# ---------------------------------------------------------------------------


class FhlbCombinedFetcher(BaseFetcher):
    """Fetcher for the FHLB Office of Finance Combined Financial Report.

    Source: https://www.fhlb-of.com/ofweb_userWeb/pageBuilder/fhlbank-financial-data-36
    Cadence: quarterly, ~60-90 days after end-of-quarter.
    Format: PDF with structured tables (text-based; parsed with pdfplumber).
    Populates: A3 arcs (FHLB advances), I3 nodes (FHLB system).
    Project plan: §10.4.
    """

    source_id: str = "fhlb_combined"
    cadence: Literal["quarterly"] = "quarterly"

    def __init__(self, data_root: Path | str | None = None) -> None:
        if data_root is None:
            data_root = Path("data/raw") / self.source_id
        self._data_root = Path(data_root)

    # ------------------------------------------------------------------
    # list_available_periods
    # ------------------------------------------------------------------

    def list_available_periods(self) -> list[Period]:
        """Scrape the FHLB-OF index page and return available quarters.

        Makes a single HTTP GET to the index URL, parses the HTML for PDF
        links whose anchor text or surrounding text identifies a quarter,
        and returns the sorted list of parseable periods.
        """
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            resp = client.get(INDEX_URL)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        periods: list[Period] = []
        seen: set[str] = set()

        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            if not (href.endswith(".pdf") or "combined" in href.lower()):
                continue
            text = a_tag.get_text(" ", strip=True)
            period = _label_to_period(text)
            if period is None:
                # Try the surrounding paragraph text
                parent_text = (
                    a_tag.parent.get_text(" ", strip=True) if a_tag.parent else ""
                )
                period = _label_to_period(parent_text)
            if period is not None and str(period) not in seen:
                seen.add(str(period))
                periods.append(period)

        periods.sort()
        return periods

    # ------------------------------------------------------------------
    # acquire
    # ------------------------------------------------------------------

    def acquire(self, period: Period) -> RawDataHandle:
        """Download the Combined Financial Report PDF for *period*.

        Caches the file under data/raw/fhlb_combined/{period}/. Re-uses the
        cached file if it already exists (content-addressing via SHA-256).
        The period-to-URL mapping is obtained by scraping the index page.
        """
        dest_dir = self._data_root / str(period)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / "combined-financial-report.pdf"

        if dest_file.exists():
            log.info("Cache hit: %s", dest_file)
            return RawDataHandle.from_paths(self.source_id, period, [dest_file])

        pdf_url = self._resolve_pdf_url(period)
        log.info("Downloading %s → %s", pdf_url, dest_file)

        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            resp = client.get(pdf_url)
            resp.raise_for_status()

        dest_file.write_bytes(resp.content)
        return RawDataHandle.from_paths(self.source_id, period, [dest_file])

    def _resolve_pdf_url(self, period: Period) -> str:
        """Return the direct PDF download URL for *period* by scraping the index."""
        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            resp = client.get(INDEX_URL)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        base = str(resp.url)

        for a_tag in soup.find_all("a", href=True):
            href: str = a_tag["href"]
            if not (href.endswith(".pdf") or "combined" in href.lower()):
                continue
            text = a_tag.get_text(" ", strip=True)
            p = _label_to_period(text) or _label_to_period(
                (a_tag.parent or a_tag).get_text(" ", strip=True)
            )
            if p == period:
                if href.startswith("http"):
                    return href
                # Make absolute
                from urllib.parse import urljoin
                return urljoin(base, href)

        raise FileNotFoundError(
            f"Could not locate a PDF link for {period} on {INDEX_URL}"
        )

    # ------------------------------------------------------------------
    # parse
    # ------------------------------------------------------------------

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse the Combined Financial Report PDF into ArcFact records.

        Extracts two categories of A3 arcs:
          1. System-wide insurance-member advances aggregate (billions table).
          2. Named top-N insurance advance users (millions table), where present.

        Unknown member names are written to the unmapped registry.
        """
        if not handle.paths:
            raise ValueError("RawDataHandle has no file paths")

        pdf_path = handle.paths[0]
        sha256 = handle.sha256_by_path[str(pdf_path)]
        provenance_url = INDEX_URL

        full_text = self._extract_text(pdf_path)
        period = self._detect_period(full_text, handle.period)
        facts: list[ArcFact] = []
        unmapped: list[dict] = []

        # -- Aggregate insurance-member arc --
        insurance_arc = self._parse_insurance_aggregate(
            full_text, period, sha256, provenance_url
        )
        if insurance_arc is not None:
            facts.append(insurance_arc)

        # -- Named top-N member arcs (if present) --
        named_arcs, new_unmapped = self._parse_top_members(
            full_text, period, sha256, provenance_url
        )
        facts.extend(named_arcs)
        unmapped.extend(new_unmapped)

        if unmapped:
            self._write_unmapped_registry(period, unmapped)

        return facts

    def _extract_text(self, pdf_path: Path) -> str:
        """Return full text of the PDF using pdfplumber, page-joined with newlines."""
        pages: list[str] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if text:
                    pages.append(text)
        return "\n".join(pages)

    def _detect_period(self, text: str, fallback: Period) -> Period:
        """Extract the report period from the header text, falling back to handle.period."""
        m = _HEADER_PERIOD_RE.search(text)
        if m:
            month_name, year_str = m.group(1), m.group(2)
            q = _MONTH_TO_Q[month_name.lower()]
            try:
                return Period(f"{year_str}-Q{q}")
            except ValueError:
                pass
        return fallback

    def _parse_insurance_aggregate(
        self,
        text: str,
        period: Period,
        sha256: str,
        url: str,
    ) -> ArcFact | None:
        """Extract the system-wide insurance-member advances total."""
        m = _INSURANCE_ROW_RE.search(text)
        if not m:
            log.warning("Could not find 'Insurance Companies' row in %s", period)
            return None
        raw_amount = m.group(1).replace(",", "")
        try:
            amount_billions = Decimal(raw_amount)
        except InvalidOperation:
            log.warning("Could not parse insurance amount %r for %s", raw_amount, period)
            return None

        amount_millions = amount_billions * Decimal("1000")
        return ArcFact(
            period=period,
            source_node_id=_INSURER_AGGREGATE_NODE,
            target_node_id=_FHLB_SYSTEM_NODE,
            instrument_class=ArcClass.A3,
            dollar_amount_millions=amount_millions,
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
            provenance_source=self.source_id,
            provenance_url=url,
            provenance_filing=f"fhlb_combined_{period}",
            provenance_page=None,
            provenance_field="ADVANCES OUTSTANDING BY MEMBER TYPE / Insurance Companies",
            sha256_of_source=sha256,
        )

    def _parse_top_members(
        self,
        text: str,
        period: Period,
        sha256: str,
        url: str,
    ) -> tuple[list[ArcFact], list[dict]]:
        """Extract individual named insurance-member arcs from the top-N table."""
        # Find the top-member section; only parse lines after the header.
        section_match = re.search(
            r"TOP\s+(?:TEN|TEN|10|N)\s+ADVANCE\s+USERS?.*?INSURANCE",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if not section_match:
            return [], []

        section_text = text[section_match.start():]
        facts: list[ArcFact] = []
        unmapped: list[dict] = []

        for row_match in _MEMBER_ROW_RE.finditer(section_text):
            raw_name = row_match.group(1).strip()
            # Skip the header row
            if raw_name.lower() in ("member name", "member", "name"):
                continue
            raw_amount = row_match.group(3).replace(",", "")

            try:
                amount_millions = Decimal(raw_amount)
            except InvalidOperation:
                log.warning("Cannot parse member amount %r, skipping", raw_amount)
                continue

            node_id = _canonicalize_member_name(raw_name)
            if node_id is None:
                slug = _slug(raw_name)
                node_id = f"insurer:unresolved_{slug}"
                unmapped.append(
                    {
                        "raw_name": raw_name,
                        "assigned_node_id": node_id,
                        "period": str(period),
                        "source": self.source_id,
                    }
                )
                log.warning(
                    "Unmapped FHLB member %r → %s (logged to unmapped registry)",
                    raw_name,
                    node_id,
                )

            facts.append(
                ArcFact(
                    period=period,
                    source_node_id=node_id,
                    target_node_id=_FHLB_SYSTEM_NODE,
                    instrument_class=ArcClass.A3,
                    dollar_amount_millions=amount_millions,
                    measurement_basis="stock_eop",
                    data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
                    provenance_source=self.source_id,
                    provenance_url=url,
                    provenance_filing=f"fhlb_combined_{period}",
                    provenance_page=None,
                    provenance_field="TOP TEN ADVANCE USERS / member row",
                    sha256_of_source=sha256,
                )
            )

        return facts, unmapped

    def _write_unmapped_registry(self, period: Period, unmapped: list[dict]) -> None:
        """Append unmapped entity names to the project registry for human review."""
        registry_dir = Path("claimweb/registry/unmapped")
        registry_dir.mkdir(parents=True, exist_ok=True)
        registry_file = registry_dir / f"{self.source_id}_{period}.json"
        existing: list[dict] = []
        if registry_file.exists():
            try:
                existing = json.loads(registry_file.read_text())
            except (json.JSONDecodeError, OSError):
                existing = []
        seen_names = {e["raw_name"] for e in existing}
        new_entries = [e for e in unmapped if e["raw_name"] not in seen_names]
        if new_entries:
            registry_file.write_text(
                json.dumps(existing + new_entries, indent=2)
            )

    # ------------------------------------------------------------------
    # validate
    # ------------------------------------------------------------------

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Check internal consistency of the parsed arcs.

        Rules:
          1. At least one arc must be present.
          2. The insurance-aggregate arc must be present.
          3. Insurance-aggregate amount must exceed the minimum plausible value.
          4. Sum of named-member arcs must not exceed the insurance aggregate.
          5. All arcs must have the expected instrument class and measurement basis.
        """
        report = ValidationReport(source_id=self.source_id, period=facts[0].period if facts else Period("2000-Q1"))

        if not facts:
            report.error("NO_FACTS", "parse() returned zero ArcFacts — check PDF structure")
            return report

        report = ValidationReport(source_id=self.source_id, period=facts[0].period)

        aggregate_arcs = [
            f for f in facts if f.source_node_id == _INSURER_AGGREGATE_NODE
        ]
        named_arcs = [
            f for f in facts if f.source_node_id != _INSURER_AGGREGATE_NODE
        ]

        if not aggregate_arcs:
            report.error(
                "MISSING_AGGREGATE",
                "Insurance-member aggregate arc not found; "
                "'Insurance Companies' row may be missing or reformatted",
            )
        else:
            agg_amount = aggregate_arcs[0].dollar_amount_millions
            min_millions = _MIN_INSURANCE_ADVANCES_BILLIONS * Decimal("1000")
            if agg_amount < min_millions:
                report.warning(
                    "LOW_INSURANCE_TOTAL",
                    f"Insurance-member advances = {agg_amount} M USD is below "
                    f"the expected minimum of {min_millions} M USD; "
                    "check unit conversion (billions→millions)",
                )

            # Named-member sum ≤ aggregate
            if named_arcs:
                named_sum = sum(
                    (f.dollar_amount_millions for f in named_arcs), Decimal("0")
                )
                if named_sum > agg_amount:
                    report.error(
                        "NAMED_EXCEEDS_AGGREGATE",
                        f"Sum of named-member arcs ({named_sum} M) exceeds the "
                        f"insurance-aggregate arc ({agg_amount} M); "
                        "possible unit mismatch between the two tables",
                    )

        # Instrument class and measurement basis checks
        for fact in facts:
            if fact.instrument_class is not ArcClass.A3:
                report.error(
                    "WRONG_ARC_CLASS",
                    f"Expected A3, got {fact.instrument_class} for "
                    f"{fact.source_node_id} → {fact.target_node_id}",
                )
            if fact.measurement_basis != "stock_eop":
                report.warning(
                    "UNEXPECTED_BASIS",
                    f"Expected stock_eop, got {fact.measurement_basis!r} for "
                    f"{fact.source_node_id} → {fact.target_node_id}",
                )

        return report
