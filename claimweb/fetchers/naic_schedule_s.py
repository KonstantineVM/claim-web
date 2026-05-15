"""NAIC Schedule S — Reinsurance cessions fetcher (project plan §10.3).

Source: NAIC annual statutory filings (per-state insurance department portals).
        No stable central free API exists; data must be obtained from state
        portals and placed at data/raw/naic_schedule_s/{period}/.
        See DATA_ACQUISITION_NOTES below for per-state guidance.
Cadence: Annual (NAIC annual statement filed by March 1 for prior December 31
         year-end; each year-end maps to a YYYY-Q4 period).
Format: CSV with one row per (cedent, reinsurer) pair; amounts in $000.
Populates: A6 arcs (reinsurance treaties, offshore-cession, project plan §4).
           T2 node identifiers for offshore reinsurers.

DATA_ACQUISITION_NOTES
----------------------
NAIC statutory annual statements are filed with individual state insurance
departments; there is no single free central repository.  The best free
acquisition paths for Schedule S Part 3 (ceded reinsurance by counterparty):

1. **NAIC Insurance Data Portal (IDP)**
   https://insurancedatalink.naic.org/
   Requires NAIC membership login.  Provides per-company Schedule S in
   machine-readable format.  Not freely accessible without membership.

2. **Iowa Insurance Division** (Athene, AUSA Life, other Iowa-domiciled)
   https://iid.iowa.gov/company-financial-data
   Iowa hosts the NAIC Annual Statement data for Iowa-domiciled companies.
   Some data is accessible without login via their public search interface.

3. **New York DFS** (Global Atlantic, Lincoln, Brighthouse)
   https://www.dfs.ny.gov/industry_guidance/financial_condition_examinations
   New York provides statutory filings via their company search portal.
   Machine-readable extraction requires the DFS portal search workflow.

4. **Wisconsin OCI** (many mid-tier insurers)
   https://oci.wi.gov/Pages/Companies/CompanySearch.aspx
   Wisconsin provides statutory filing data via their portal.

Manual extraction workflow:
  1. Navigate to the state portal for the domicile state of target cedents.
  2. Download the Annual Statement (or Schedule S extract) for the target year.
  3. Export Schedule S Part 3 to CSV matching the column schema below.
  4. Place the file at: data/raw/naic_schedule_s/{period}/schedule_s.csv
     where {period} is the YYYY-Q4 period for December 31 of the filing year.

Required CSV schema (header row required):
  period            — YYYY-Q4 (e.g., 2023-Q4)
  cedent_name       — Full legal name of the ceding U.S. insurer
  cedent_naic_code  — NAIC company code for the cedent (5 digits; may be blank)
  reinsurer_name    — Full legal name of the assuming reinsurer
  reinsurer_naic_code — NAIC code for reinsurer (blank for non-admitted foreign)
  reinsurer_domicile  — 2-char US state code or ISO country code (BM, KY, IE…)
  authorized_flag   — Authorized | Unauthorized | Certified (NAIC certified flag)
  amount_life_000   — Life insurance ceded ($000)
  amount_anh_000    — Accident & Health ceded ($000)
  amount_annuity_000 — Annuity ceded ($000)
  amount_other_000  — Other ceded ($000)

Arc direction (A6 reinsurance treaty claim):
  source_node_id = reinsurer (issuer of the reinsurance liability)
  target_node_id = cedent   (holder of the reinsurance recoverable asset)
  This follows the project-wide convention: source = obligor, target = creditor.

Node ID conventions:
  Cedent (U.S. insurer, T1):  insurer:naic:{cedent_naic_code}  if code present
                               insurer:name:{slug}               otherwise
  Reinsurer (T2 or domestic): reinsurer:naic:{reinsurer_naic_code}  if present
                               reinsurer:name:{slug}                 otherwise

Dollar amounts: source CSV amounts are in $000 (NAIC standard).  Parser
  multiplies by 0.001 → millions USD.  Each (cedent, reinsurer) row emits one
  A6 arc whose dollar_amount_millions = total ceded (life + A&H + annuity + other).

Data quality flag: DIRECT_MEASURED — Schedule S Part 3 is a direct statutory
  disclosure by the ceding insurer under regulatory requirement.  The amount
  ceded is the insurer's own statement of its reinsurance obligation.

Measurement basis: stock_eop — year-end snapshot of outstanding ceded reserves
  as of December 31 of the filing year.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

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

# Source amounts are in $000; project canonical unit is millions USD.
_THOUSANDS_TO_MILLIONS = Decimal("0.001")

# Minimum plausible total ceded reserves for a significant cedent (millions).
_MIN_CEDENT_TOTAL_MM = Decimal("1")

# Known offshore jurisdictions (ISO 3166-1 alpha-2 that are NOT U.S. states).
# Used in validate() to identify A6 offshore-cession arcs.
_OFFSHORE_DOMICILES: frozenset[str] = frozenset({
    "BM",  # Bermuda
    "KY",  # Cayman Islands
    "IE",  # Ireland
    "LU",  # Luxembourg
    "VG",  # British Virgin Islands
    "BS",  # Bahamas
    "BB",  # Barbados
    "TC",  # Turks and Caicos
    "GG",  # Guernsey
    "JE",  # Jersey
    "IM",  # Isle of Man
    "MT",  # Malta
    "JP",  # Japan (for Japan-domiciled affiliates)
    "CH",  # Switzerland
    "FR",  # France
    "GB",  # United Kingdom
    # Intentionally excluded ambiguous ISO-2 codes that collide with U.S. state
    # abbreviations used in NAIC domicile fields:
    #   "CA" → Canada ISO-2 but also California state abbreviation
    #   "DE" → Germany ISO-2 but also Delaware state abbreviation
    # German and Canadian reinsurers appear in Schedule S but the offshore-cession
    # circuit primarily targets Bermuda/Cayman captives.  Add explicit parsing of
    # the 3-char ISO-3 codes if full coverage is needed in a future revision.
})

# Known PE-affiliated insurer NAIC codes (used in validate() to warn if absent).
_PE_AFFILIATED_CEDENT_CODES: frozenset[str] = frozenset({
    "68039",  # Athene Annuity and Life Insurance Company
    "97071",  # Global Atlantic Life Insurance Company
    "63177",  # Fidelity and Guaranty Life Insurance Company
    "92487",  # American Equity Investment Life Insurance Company
    "88072",  # Talcott Life and Annuity Insurance Company (Talcott Resolution)
})

# CSV column names in the canonical CLAIM-WEB Schedule S format.
_COL_PERIOD = "period"
_COL_CEDENT_NAME = "cedent_name"
_COL_CEDENT_NAIC = "cedent_naic_code"
_COL_REINSURER_NAME = "reinsurer_name"
_COL_REINSURER_NAIC = "reinsurer_naic_code"
_COL_REINSURER_DOM = "reinsurer_domicile"
_COL_AUTH_FLAG = "authorized_flag"
_COL_AMT_LIFE = "amount_life_000"
_COL_AMT_ANH = "amount_anh_000"
_COL_AMT_ANNUITY = "amount_annuity_000"
_COL_AMT_OTHER = "amount_other_000"

_REQUIRED_COLUMNS: frozenset[str] = frozenset({
    _COL_PERIOD,
    _COL_CEDENT_NAME,
    _COL_REINSURER_NAME,
    _COL_AMT_LIFE,
    _COL_AMT_ANH,
    _COL_AMT_ANNUITY,
    _COL_AMT_OTHER,
})

# Filename used for the canonical per-period CSV inside the cache directory.
_SCHEDULE_S_FILENAME = "schedule_s.csv"

# ──────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ──────────────────────────────────────────────────────────────────────────────


def _normalise_name(name: str) -> str:
    """Produce a stable slug from an entity name for use in node IDs."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:64]


def _cedent_node_id(naic_code: str, name: str) -> str:
    """Return a canonical node ID for a cedent (U.S. life insurer, T1 node)."""
    code = naic_code.strip()
    if code and code not in ("0", "00000", ""):
        return f"insurer:naic:{code}"
    return f"insurer:name:{_normalise_name(name)}"


def _reinsurer_node_id(naic_code: str, name: str) -> str:
    """Return a canonical node ID for a reinsurer (T2 node or domestic)."""
    code = naic_code.strip()
    if code and code not in ("0", "00000", ""):
        return f"reinsurer:naic:{code}"
    return f"reinsurer:name:{_normalise_name(name)}"


def _parse_amount_thousands(raw: str) -> Decimal:
    """Parse a $000 amount string to a Decimal in thousands.

    Returns Decimal("0") for empty, blank, or non-numeric values.
    """
    cleaned = raw.strip().replace(",", "").replace("$", "")
    if not cleaned or cleaned in ("-", "N/A", "NA", ""):
        return Decimal("0")
    try:
        val = Decimal(cleaned)
        return val if val >= Decimal("0") else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def _parse_schedule_s_csv(content: str) -> list[dict]:
    """Parse the canonical CLAIM-WEB Schedule S CSV.

    Returns a list of row dicts; skips rows with missing required columns.
    """
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        return []

    fieldnames_lower = {f.strip().lower() for f in reader.fieldnames}
    missing = _REQUIRED_COLUMNS - fieldnames_lower
    if missing:
        log.warning(
            "NaicScheduleSFetcher: CSV missing required columns: %s",
            sorted(missing),
        )

    rows: list[dict] = []
    for raw_row in reader:
        row = {k.strip().lower(): v for k, v in raw_row.items()}
        cedent_name = row.get(_COL_CEDENT_NAME, "").strip()
        reinsurer_name = row.get(_COL_REINSURER_NAME, "").strip()
        if not cedent_name or not reinsurer_name:
            continue
        rows.append(row)
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# NaicScheduleSFetcher
# ──────────────────────────────────────────────────────────────────────────────


class NaicScheduleSFetcher(BaseFetcher):
    """Fetcher for NAIC Schedule S reinsurance cessions.

    Source: NAIC annual statutory filings (per-state insurance department portals).
            Data must be manually obtained and placed in
            data/raw/naic_schedule_s/{period}/schedule_s.csv.
            See module docstring for acquisition guidance.
    Cadence: Annual (each period must be a Q4 period, e.g. '2023-Q4').
    Format: CSV with one row per (cedent, reinsurer) pair.
    Populates: A6 arcs (reinsurance treaties, offshore-cession).
    Project plan: §10.3.
    """

    source_id: str = "naic_schedule_s"
    cadence: Literal["annual", "quarterly", "monthly"] = "annual"

    def list_available_periods(self) -> list[Period]:
        """Return sorted list of annual periods for which cached data exists.

        Scans data/raw/naic_schedule_s/ for subdirectories containing
        schedule_s.csv.  Only Q4 periods are valid (NAIC annual statement
        cadence is December 31 year-end).
        """
        base = Path("data") / "raw" / self.source_id
        if not base.exists():
            return []

        periods: list[Period] = []
        for subdir in sorted(base.iterdir()):
            if not subdir.is_dir():
                continue
            try:
                period = Period(subdir.name)
            except ValueError:
                continue
            if period.quarter != 4:
                log.debug(
                    "NaicScheduleSFetcher: skipping non-Q4 directory %s",
                    subdir.name,
                )
                continue
            csv_path = subdir / _SCHEDULE_S_FILENAME
            if csv_path.exists():
                periods.append(period)
        return sorted(periods)

    def acquire(self, period: Period) -> RawDataHandle:
        """Return a handle to the cached Schedule S CSV for *period*.

        NAIC Schedule S data is not available via a free central API.
        This method reads from the local cache only.  If no cached file
        exists, raises RuntimeError with data-acquisition instructions.

        Period must be a Q4 period (NAIC annual statement cadence).

        Cache path: data/raw/naic_schedule_s/{period}/schedule_s.csv
        """
        if period.quarter != 4:
            raise ValueError(
                f"NAIC Schedule S is annual (Q4 only); got period {period!r}. "
                "Use the December 31 year-end period, e.g. '2023-Q4'."
            )

        cache_dir = Path("data") / "raw" / self.source_id / str(period)
        csv_path = cache_dir / _SCHEDULE_S_FILENAME

        if csv_path.exists():
            log.info(
                "NaicScheduleSFetcher: reading cached %s", csv_path
            )
            return RawDataHandle.from_paths(
                source_id=self.source_id,
                period=period,
                paths=[csv_path],
            )

        raise RuntimeError(
            f"No cached NAIC Schedule S data found for {period}.\n"
            f"Expected file: {csv_path}\n\n"
            "NAIC Schedule S reinsurance data must be manually obtained from "
            "state insurance department portals.  See the module docstring in "
            "claimweb/fetchers/naic_schedule_s.py for per-state acquisition "
            "guidance.\n\n"
            "Quick-start for key PE-affiliated cedents:\n"
            "  Iowa-domiciled (Athene, AUSA):  https://iid.iowa.gov/\n"
            "  New York-domiciled (Global Atlantic):  https://www.dfs.ny.gov/\n"
            "  Iowa-domiciled (F&G):  https://iid.iowa.gov/\n\n"
            f"Place the exported CSV at {csv_path} then re-run acquire()."
        )

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse the Schedule S CSV into A6 reinsurance-cession ArcFacts.

        Each row in the CSV represents a (cedent, reinsurer) pair with ceded
        amounts by instrument type.  Emits one A6 ArcFact per row where the
        total ceded amount is greater than zero.

        Arc direction:
          source_node_id = reinsurer (issuer of the reinsurance liability)
          target_node_id = cedent   (holder of the reinsurance recoverable)

        Dollar amounts: source CSV amounts are in $000; multiplied by 0.001
          to convert to millions USD.
        """
        if not handle.paths:
            log.warning("NaicScheduleSFetcher.parse: empty handle paths")
            return []

        csv_path = handle.paths[0]
        sha256 = handle.sha256_by_path.get(str(csv_path), "0" * 64)
        provenance_url = f"file://{csv_path.resolve()}"

        try:
            content = csv_path.read_bytes().decode("utf-8-sig", errors="replace")
        except OSError as exc:
            log.error(
                "NaicScheduleSFetcher.parse: cannot read %s: %s", csv_path, exc
            )
            return []

        rows = _parse_schedule_s_csv(content)
        if not rows:
            log.warning(
                "NaicScheduleSFetcher.parse: no data rows parsed from %s", csv_path
            )
            return []

        facts: list[ArcFact] = []
        skipped_zero = 0
        skipped_selfref = 0

        for row in rows:
            period_str = row.get(_COL_PERIOD, "").strip()
            try:
                period = Period(period_str)
            except ValueError:
                log.debug(
                    "NaicScheduleSFetcher.parse: unparseable period %r; skipping",
                    period_str,
                )
                continue

            cedent_name = row.get(_COL_CEDENT_NAME, "").strip()
            cedent_naic = row.get(_COL_CEDENT_NAIC, "").strip()
            reinsurer_name = row.get(_COL_REINSURER_NAME, "").strip()
            reinsurer_naic = row.get(_COL_REINSURER_NAIC, "").strip()
            reinsurer_dom = row.get(_COL_REINSURER_DOM, "").strip().upper()
            auth_flag = row.get(_COL_AUTH_FLAG, "").strip()

            amt_life = _parse_amount_thousands(row.get(_COL_AMT_LIFE, "0"))
            amt_anh = _parse_amount_thousands(row.get(_COL_AMT_ANH, "0"))
            amt_annuity = _parse_amount_thousands(row.get(_COL_AMT_ANNUITY, "0"))
            amt_other = _parse_amount_thousands(row.get(_COL_AMT_OTHER, "0"))
            total_thousands = amt_life + amt_anh + amt_annuity + amt_other

            if total_thousands <= Decimal("0"):
                skipped_zero += 1
                continue

            source_id = _reinsurer_node_id(reinsurer_naic, reinsurer_name)
            target_id = _cedent_node_id(cedent_naic, cedent_name)

            if source_id == target_id:
                skipped_selfref += 1
                log.debug(
                    "NaicScheduleSFetcher.parse: self-referential arc for %r; skipping",
                    reinsurer_name,
                )
                continue

            dollar_millions = total_thousands * _THOUSANDS_TO_MILLIONS

            # Provenance field encodes the treaty classification
            provenance_field = (
                f"Schedule_S_Part3|cedent={cedent_naic or cedent_name!r}"
                f"|reinsurer={reinsurer_naic or reinsurer_name!r}"
                f"|domicile={reinsurer_dom}"
                f"|auth={auth_flag}"
            )

            filing_id = (
                f"naic_schedule_s_{period}_{cedent_naic or _normalise_name(cedent_name)}"
            )

            facts.append(
                ArcFact(
                    period=period,
                    source_node_id=source_id,
                    target_node_id=target_id,
                    instrument_class=ArcClass.A6,
                    dollar_amount_millions=dollar_millions,
                    measurement_basis="stock_eop",
                    data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
                    provenance_source=self.source_id,
                    provenance_url=provenance_url,
                    provenance_filing=filing_id,
                    provenance_page=None,
                    provenance_field=provenance_field,
                    sha256_of_source=sha256,
                )
            )

        if skipped_zero:
            log.debug(
                "NaicScheduleSFetcher.parse: skipped %d rows with zero total ceded",
                skipped_zero,
            )
        if skipped_selfref:
            log.debug(
                "NaicScheduleSFetcher.parse: skipped %d self-referential arcs",
                skipped_selfref,
            )

        log.info(
            "NaicScheduleSFetcher.parse: emitted %d A6 arcs from %s",
            len(facts),
            csv_path,
        )
        return facts

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Run sanity checks on the parsed A6 reinsurance arcs.

        Checks:
        - All emitted arcs have instrument_class A6.
        - All dollar amounts are non-negative.
        - All amounts use stock_eop measurement basis.
        - At least one offshore-domicile arc exists if facts are non-empty.
        - Warns if any known PE-affiliated cedents are absent.
        """
        period = facts[0].period if facts else Period("2000-Q4")
        report = ValidationReport(source_id=self.source_id, period=period)

        if not facts:
            report.info(
                "NO_FACTS",
                "No A6 arcs parsed; Schedule S CSV may be empty or not yet acquired.",
            )
            return report

        bad_class = [f for f in facts if f.instrument_class != ArcClass.A6]
        if bad_class:
            report.error(
                "WRONG_ARC_CLASS",
                f"{len(bad_class)} arcs have instrument_class != A6; "
                f"first offender: {bad_class[0].instrument_class!r}",
                tuple(f.provenance_field for f in bad_class[:3]),
            )

        negative = [f for f in facts if f.dollar_amount_millions < Decimal("0")]
        if negative:
            report.error(
                "NEGATIVE_AMOUNT",
                f"{len(negative)} arcs have negative dollar_amount_millions",
                tuple(f.provenance_field for f in negative[:3]),
            )

        wrong_basis = [f for f in facts if f.measurement_basis != "stock_eop"]
        if wrong_basis:
            report.error(
                "WRONG_MEASUREMENT_BASIS",
                f"{len(wrong_basis)} arcs have measurement_basis != 'stock_eop'",
                tuple(f.provenance_field for f in wrong_basis[:3]),
            )

        # Check that at least some offshore arcs exist in the dataset.
        # Offshore arcs have target containing a known offshore-domicile code
        # in their provenance_field.
        offshore_count = sum(
            1 for f in facts
            if any(
                f"|domicile={dom}" in f.provenance_field
                for dom in _OFFSHORE_DOMICILES
            )
        )
        if offshore_count == 0:
            report.warning(
                "NO_OFFSHORE_ARCS",
                "No offshore-domicile reinsurance arcs found.  "
                "The dataset may be missing cessions to Bermuda/Cayman affiliates.",
            )

        # Warn if no known PE-affiliated cedents appear in the source targets.
        observed_targets = {f.target_node_id for f in facts}
        missing_pe = {
            code
            for code in _PE_AFFILIATED_CEDENT_CODES
            if f"insurer:naic:{code}" not in observed_targets
        }
        if missing_pe:
            report.info(
                "PE_AFFILIATED_CEDENTS_ABSENT",
                f"No arcs found for known PE-affiliated cedents "
                f"(NAIC codes: {sorted(missing_pe)}). "
                "Coverage may be incomplete for the offshore-cession circuit.",
            )

        total_mm = sum(f.dollar_amount_millions for f in facts)
        if total_mm < _MIN_CEDENT_TOTAL_MM:
            report.warning(
                "IMPLAUSIBLY_LOW_TOTAL",
                f"Total ceded reserves across all arcs is {total_mm:.2f}M, "
                "which is below the plausibility floor of "
                f"{_MIN_CEDENT_TOTAL_MM}M.",
            )

        log.info(
            "NaicScheduleSFetcher.validate: %d facts, total=%.1fM, "
            "offshore=%d; %d errors %d warnings %d info",
            len(facts),
            float(total_mm),
            offshore_count,
            sum(1 for i in report.issues if i.severity == "error"),
            sum(1 for i in report.issues if i.severity == "warning"),
            sum(1 for i in report.issues if i.severity == "info"),
        )
        return report
