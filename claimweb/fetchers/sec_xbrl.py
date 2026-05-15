"""SEC XBRL companyfacts fetcher for the LIFE_INSURERS panel (project plan §10.2).

Source: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
Cadence: as-filed (quarterly 10-Q; annual 10-K; ~40-75 days after period-end).
Format: JSON with us-gaap and custom taxonomy namespaces.
Populates: per-entity balance-sheet marginals (Law 1 constraints) and
           specific instrument exposures: A1 (funding agreements / GICs),
           A3 (FHLB advances), A4 (repurchase agreements), A5 (securities
           lending payables).

The LIFE_INSURERS panel covers major U.S. life insurance holding companies
that file 10-K/10-Q with the SEC.  Mutual companies (New York Life,
Northwestern Mutual, MassMutual, etc.) do not file with the SEC and are
therefore excluded from this fetcher.

Arc direction convention (project plan §1):
  source_node_id = issuer of the obligation
  target_node_id = holder of the claim

  Liability-side (insurer *issues* the obligation):
    source = insurer:{ticker}  →  target = sector:... or z1:all_holders
  Asset-side (insurer *holds* the instrument):
    source = sector:...        →  target = insurer:{ticker}

Dollar amounts: SEC companyfacts values are in raw USD.  The parser divides
all values by 1,000,000 (i.e., multiplies by Decimal("0.000001")) to produce
millions of USD.  Conversion is documented in provenance_field per ArcFact.

Data quality flag: DIRECT_MEASURED — SEC EDGAR regulatory filings.
Measurement basis: "stock_eop" — balance-sheet items are end-of-period stocks.
"""
from __future__ import annotations

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

# SEC EDGAR XBRL companyfacts endpoint (project plan §10.2).
# Rate limit: ~10 requests/second; must include descriptive User-Agent per
# EDGAR guidelines (https://www.sec.gov/os/accessing-edgar-data).
_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Cache lifetime: bundle is re-downloaded when older than this many days.
# Life-insurer 10-Qs are filed ~40 days after quarter-end; a 14-day window
# gives a fresh snapshot without hammering EDGAR.
_CACHE_LIFETIME_DAYS = 14

# Plausibility floor for any major life-insurer total assets (millions).
# All panel members hold >> $10 billion.
_MIN_TOTAL_ASSETS_MM = Decimal("10_000")

# Raw USD → millions of USD
_USD_TO_MM = Decimal("0.000001")

# ──────────────────────────────────────────────────────────────────────────────
# LIFE_INSURERS panel
# ──────────────────────────────────────────────────────────────────────────────

# Canonical CLAIM-WEB node ID → zero-padded 10-digit SEC CIK.
# Panel covers SEC-registered public life insurance holding companies only.
# CIKs verified against SEC EDGAR full-text search, 2024-12 (project plan
# §10.2, data-dictionary Part VI).
LIFE_INSURERS: dict[str, str] = {
    "insurer:MET":  "0001099219",   # MetLife, Inc.
    "insurer:PRU":  "0001137774",   # Prudential Financial, Inc.
    "insurer:LNC":  "0000059479",   # Lincoln National Corporation
    "insurer:PFG":  "0001126328",   # Principal Financial Group, Inc.
    "insurer:AFL":  "0000004977",   # Aflac Incorporated
    "insurer:UNM":  "0000005513",   # Unum Group
    "insurer:RGA":  "0001096664",   # Reinsurance Group of America, Inc.
    "insurer:BHF":  "0001673358",   # Brighthouse Financial, Inc.
    "insurer:EQH":  "0001778523",   # Equitable Holdings, Inc.
    "insurer:VOYA": "0001535778",   # Voya Financial, Inc.
    "insurer:CNO":  "0000723511",   # CNO Financial Group, Inc.
    "insurer:JXN":  "0001822479",   # Jackson Financial Inc.
    "insurer:GL":   "0000098752",   # Globe Life Inc. (formerly Torchmark)
    "insurer:AEL":  "0001171825",   # American Equity Investment Life Holding
    "insurer:FG":   "0001819189",   # F&G Annuities & Life, Inc.
}

# Reverse map: zero-padded 10-digit CIK → canonical entity node ID.
_CIK_TO_ENTITY: dict[str, str] = {cik: eid for eid, cik in LIFE_INSURERS.items()}

# ──────────────────────────────────────────────────────────────────────────────
# XBRL tag → arc mapping
# ──────────────────────────────────────────────────────────────────────────────

# Maps us-gaap XBRL tag → (ArcClass, source_template, target_template).
# "{entity_id}" is substituted with the canonical entity node ID at parse time.
#
# Arc directions:
#   Liability-side: source = "{entity_id}", target = sector/aggregate node
#   Asset-side:     source = sector/aggregate node, target = "{entity_id}"
_TAG_MAP: dict[str, tuple[ArcClass, str, str]] = {
    # ── Law 1 balance-sheet marginals ────────────────────────────────────────
    # Total assets: insurer holds claims against all counterparties
    "Assets": (
        ArcClass.A12, "z1:aggregate", "{entity_id}"
    ),
    # Total liabilities: insurer has issued claims to all holders
    "Liabilities": (
        ArcClass.A12, "{entity_id}", "z1:aggregate"
    ),
    # Stockholders' equity (two tag vintages across filing history)
    "StockholdersEquity": (
        ArcClass.A12, "{entity_id}", "z1:equity_holders"
    ),
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": (
        ArcClass.A12, "{entity_id}", "z1:equity_holders"
    ),
    # ── A3: FHLB advances ────────────────────────────────────────────────────
    # Insurer borrows from its FHLB district (recorded as liability)
    "AdvancesFromFederalHomeLoanBanks": (
        ArcClass.A3, "{entity_id}", "sector:fhlb"
    ),
    # ── A4: Repurchase agreements ────────────────────────────────────────────
    # Insurer sells securities under agreement to repurchase (borrower side)
    "SecuritiesSoldUnderAgreementsToRepurchase": (
        ArcClass.A4, "{entity_id}", "sector:repo_dealers"
    ),
    # ── A5: Securities-lending cash collateral payable ───────────────────────
    # Insurer lends securities; owes cash collateral back to the borrower
    "PayablesForCollateralUnderSecuritiesLoanedAndOtherTransactions": (
        ArcClass.A5, "{entity_id}", "sector:sec_lending_counterparty"
    ),
    # ── A1: Funding agreements / policyholder account balances ───────────────
    # Insurer issues GICs and funding agreements to institutional holders.
    # Tag vintages differ across filing years:
    "PolicyholderAccountBalance": (
        ArcClass.A1, "{entity_id}", "z1:all_holders"
    ),
    "PolicyholderContractDeposits": (
        ArcClass.A1, "{entity_id}", "z1:all_holders"
    ),
}

# XBRL tag used as the plausibility anchor in validate()
_ASSETS_TAG = "Assets"

# ──────────────────────────────────────────────────────────────────────────────
# Period ↔ balance-sheet date helpers
# ──────────────────────────────────────────────────────────────────────────────

# Calendar quarter-end month → quarter number
_MONTH_TO_QUARTER: dict[int, int] = {3: 1, 6: 2, 9: 3, 12: 4}

# Quarter number → (month, last day) for calendar-year filers
_QUARTER_END: dict[int, tuple[int, int]] = {
    1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)
}


def _end_date_to_period(end_date_str: str) -> Period | None:
    """Convert an SEC end-date string ("YYYY-MM-DD") to a Period.

    Supports calendar-year quarter-ends only (March 31, June 30, September 30,
    December 31).  Non-standard fiscal-year-end dates return None.
    """
    try:
        d = date.fromisoformat(end_date_str)
    except ValueError:
        return None
    q = _MONTH_TO_QUARTER.get(d.month)
    if q is None:
        return None
    _, expected_day = _QUARTER_END[q]
    if d.day != expected_day:
        return None
    try:
        return Period(f"{d.year}-Q{q}")
    except ValueError:
        return None


def _period_to_end_date(period: Period) -> date:
    """Return the calendar quarter-end date for a given Period."""
    month, day = _QUARTER_END[period.quarter]
    return date(period.year, month, day)


# ──────────────────────────────────────────────────────────────────────────────
# XBRL fact extractor
# ──────────────────────────────────────────────────────────────────────────────


def _extract_best_fact(
    entries: list[dict],
    period: Period,
) -> tuple[Decimal, str, str] | None:
    """Return (amount_millions, accession_number, filing_form) for the period.

    Selection strategy:
    1. Filter to entries whose ``end`` date matches the period's quarter-end.
    2. Prefer primary forms (10-K, 10-Q) over amendments (10-K/A, 10-Q/A).
    3. Prefer entries with a ``frame`` field (undimensioned entity totals;
       segment / dimension facts lack frames).
    4. Among ties, pick the most recently filed entry.

    Returns None if no matching entry exists or the value cannot be parsed.
    """
    target_end = _period_to_end_date(period).isoformat()
    candidates = [e for e in entries if e.get("end") == target_end]
    if not candidates:
        return None

    primary = [e for e in candidates if e.get("form", "") in {"10-K", "10-Q"}]
    pool = primary if primary else candidates

    framed = [e for e in pool if e.get("frame")]
    pool = framed if framed else pool

    best = max(pool, key=lambda e: e.get("filed", ""))

    raw_val = best.get("val")
    if raw_val is None:
        return None
    try:
        amount_mm = Decimal(str(raw_val)) * _USD_TO_MM
    except InvalidOperation:
        log.debug(
            "Unparseable val %r for accn=%s", raw_val, best.get("accn", "?")
        )
        return None
    return amount_mm, best.get("accn", ""), best.get("form", "")


# ──────────────────────────────────────────────────────────────────────────────
# SecXbrlFetcher
# ──────────────────────────────────────────────────────────────────────────────


class SecXbrlFetcher(BaseFetcher):
    """Fetcher for SEC XBRL companyfacts for the LIFE_INSURERS panel.

    Source: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json
    Cadence: as-filed (quarterly 10-Q; annual 10-K).
    Format: JSON with us-gaap taxonomy.
    Populates: A1, A3, A4, A5 arcs; Law 1 balance-sheet marginals (§10.2).
    """

    source_id: str = "sec_xbrl"
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
        """Return sorted list of periods present in the cached bundle.

        Downloads the bundle on first call if not already cached.
        Enumerates periods from the ``Assets`` tag of the first panel entity.
        """
        self._ensure_bundle()
        first_cik = next(iter(LIFE_INSURERS.values()))
        json_path = self._bundle_dir / f"CIK{first_cik}.json"
        if not json_path.exists():
            return []
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        entries = (
            payload.get("facts", {})
            .get("us-gaap", {})
            .get(_ASSETS_TAG, {})
            .get("units", {})
            .get("USD", [])
        )
        periods: set[Period] = set()
        for e in entries:
            if e.get("form", "") in {"10-K", "10-Q"}:
                p = _end_date_to_period(e.get("end", ""))
                if p is not None:
                    periods.add(p)
        return sorted(periods)

    def acquire(self, period: Period) -> RawDataHandle:
        """Download (or read from cache) the companyfacts JSON bundle.

        SEC companyfacts contains complete filing history per entity in a
        single JSON.  All panel entity JSONs are downloaded once (subject to
        the cache window); ``period`` is carried in the handle so ``parse``
        knows which quarter to extract.

        Cached files live under ``data/raw/sec_xbrl/bundle/``.
        """
        self._ensure_bundle()
        paths = [
            self._bundle_dir / f"CIK{cik}.json"
            for cik in LIFE_INSURERS.values()
        ]
        paths = [p for p in paths if p.exists()]
        return RawDataHandle.from_paths(self.source_id, period, paths)

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse companyfacts JSONs and return ArcFacts for ``handle.period``.

        For each entity JSON in the handle, iterates the mapped XBRL tags and
        emits one ArcFact per (entity, tag) pair where data is present for the
        target period.  Tags absent from a filing are silently skipped.
        """
        target_period = handle.period
        facts: list[ArcFact] = []

        for path in handle.paths:
            sha256 = handle.sha256_by_path.get(str(path), "0" * 64)

            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Cannot read %s: %s", path, exc)
                continue

            # CIK can be string or integer in the SEC JSON
            raw_cik = payload.get("cik", "")
            cik_padded = str(raw_cik).zfill(10)
            entity_id = _CIK_TO_ENTITY.get(cik_padded)
            if entity_id is None:
                log.warning(
                    "CIK %s not in LIFE_INSURERS panel — skipping %s",
                    cik_padded,
                    path.name,
                )
                continue

            url = _COMPANYFACTS_URL.format(cik=cik_padded)
            us_gaap = payload.get("facts", {}).get("us-gaap", {})

            entity_fact_count = 0
            for tag, (arc_class, src_template, tgt_template) in _TAG_MAP.items():
                tag_data = us_gaap.get(tag)
                if tag_data is None:
                    continue
                entries = tag_data.get("units", {}).get("USD", [])
                result = _extract_best_fact(entries, target_period)
                if result is None:
                    continue

                amount_mm, accn, _form = result
                source_node = src_template.replace("{entity_id}", entity_id)
                target_node = tgt_template.replace("{entity_id}", entity_id)

                facts.append(
                    ArcFact(
                        period=target_period,
                        source_node_id=source_node,
                        target_node_id=target_node,
                        instrument_class=arc_class,
                        dollar_amount_millions=amount_mm,
                        measurement_basis="stock_eop",
                        data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
                        provenance_source=self.source_id,
                        provenance_url=url,
                        provenance_filing=f"{entity_id}_{target_period}_{accn}",
                        provenance_page=None,
                        provenance_field=tag,
                        sha256_of_source=sha256,
                    )
                )
                entity_fact_count += 1

            log.debug(
                "Parsed %s for %s: %d facts",
                entity_id,
                target_period,
                entity_fact_count,
            )

        return facts

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Sanity-check parsed ArcFacts.

        Checks:
        1. At least one ArcFact was emitted.
        2. All dollar amounts are non-negative.
        3. At least one entity's total assets exceed the plausibility floor.
        """
        period = facts[0].period if facts else Period("2000-Q1")
        report = ValidationReport(source_id=self.source_id, period=period)

        if not facts:
            report.error("NO_FACTS", "SEC XBRL parse produced zero ArcFacts")
            return report

        for f in facts:
            if f.dollar_amount_millions < Decimal("0"):
                report.warning(
                    "NEGATIVE_AMOUNT",
                    f"Negative amount {f.dollar_amount_millions} MM for "
                    f"{f.provenance_field} "
                    f"({f.source_node_id} → {f.target_node_id})",
                )

        asset_facts = [f for f in facts if f.provenance_field == _ASSETS_TAG]
        if asset_facts:
            max_assets = max(f.dollar_amount_millions for f in asset_facts)
            if max_assets < _MIN_TOTAL_ASSETS_MM:
                report.error(
                    "ASSETS_IMPLAUSIBLE",
                    f"Largest total-assets fact is {max_assets} MM, below "
                    f"plausibility floor {_MIN_TOTAL_ASSETS_MM} MM",
                )

        return report

    # ──────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────

    def _ensure_bundle(self) -> None:
        """Download all panel entity JSONs if absent or stale."""
        if self._is_bundle_fresh():
            return
        self._download_bundle()

    def _is_bundle_fresh(self) -> bool:
        """Return True if all entity JSONs exist and the manifest is recent."""
        if not self._manifest_path.exists():
            return False
        try:
            manifest = json.loads(self._manifest_path.read_text())
            fetched_at = datetime.fromisoformat(manifest["fetched_at"])
        except (KeyError, ValueError, json.JSONDecodeError):
            return False
        if datetime.utcnow() - fetched_at > timedelta(days=_CACHE_LIFETIME_DAYS):
            return False
        return all(
            (self._bundle_dir / f"CIK{cik}.json").exists()
            for cik in LIFE_INSURERS.values()
        )

    def _download_bundle(self) -> None:
        """Download companyfacts JSON for every panel entity from EDGAR."""
        self._bundle_dir.mkdir(parents=True, exist_ok=True)

        with httpx.Client(
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            for entity_id, cik in LIFE_INSURERS.items():
                url = _COMPANYFACTS_URL.format(cik=cik)
                log.info(
                    "Downloading companyfacts %s (%s) from %s",
                    entity_id,
                    cik,
                    url,
                )
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    log.warning(
                        "HTTP %d for %s (%s) — skipping",
                        exc.response.status_code,
                        entity_id,
                        url,
                    )
                    continue
                dest = self._bundle_dir / f"CIK{cik}.json"
                dest.write_bytes(resp.content)
                log.info(
                    "Cached %s → %s (%d bytes)", entity_id, dest, len(resp.content)
                )

        manifest = {
            "fetched_at": datetime.utcnow().isoformat(),
            "ciks": list(LIFE_INSURERS.values()),
        }
        self._manifest_path.write_text(json.dumps(manifest, indent=2))
