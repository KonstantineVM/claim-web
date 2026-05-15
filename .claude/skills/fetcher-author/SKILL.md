---
name: fetcher-author
description: Author a new fetcher under claimweb/fetchers/. Use whenever implementing a fetcher for a new data source (FRB Z.1, SEC XBRL, SEC NMFP, SEC ADV, SEC 13F, SEC FOCUS, NAIC Schedule S/D/BA/DB, FHLB Combined Financial Report, FHLB district 10-Q, FRB EFA FABS, FIO Annual Report, OFR publications, BMA registers, Treasury TIC, FFIEC Y-9C). Triggers on phrases like "implement the [X] fetcher", "fetch [data source]", "add [X] to claimweb/fetchers". Encodes the project's fetcher conventions so each fetcher conforms.
---

# Authoring a fetcher

This skill standardizes how every CLAIM-WEB fetcher is structured. Read it before writing any fetcher. Following the convention is mandatory — downstream code (the normalizer, the constraint compiler) depends on the contract.

## Fetcher contract

Every fetcher is a Python module under `claimweb/fetchers/{name}.py` exposing a class `{Name}Fetcher(BaseFetcher)` with the following interface:

```python
class FhlbCombinedFetcher(BaseFetcher):
    """Fetcher for the FHLB Office of Finance Combined Financial Report.

    Source: https://www.fhlb-of.com/ofweb_userWeb/pageBuilder/fhlbank-financial-data-36
    Cadence: quarterly, ~60-90 days after end-of-quarter.
    Format: PDF with structured tables.
    Populates: A3 arcs (FHLB advances), I3 nodes (FHLB districts).
    Project plan: §10.4.
    """

    source_id: str = "fhlb_combined"
    cadence: Literal["annual", "quarterly", "monthly"] = "quarterly"

    def list_available_periods(self) -> list[Period]:
        """Enumerate periods for which raw data can be acquired."""

    def acquire(self, period: Period) -> RawDataHandle:
        """Download (or read from cache) the raw data for `period`.
        Writes to data/raw/{source_id}/{period}/ with content-addressed naming.
        Returns a handle referencing the file(s) and their SHA-256."""

    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse the raw data into the normalized arc-fact form.
        Every emitted ArcFact has the data_quality_flag set."""

    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Run fetcher-specific sanity checks on the parsed facts.
        E.g., total advances disclosed in the executive summary must equal
        the sum of per-district advances. Discrepancies are reported, not
        silently corrected."""
```

`BaseFetcher` lives in `claimweb/fetchers/base.py`. If it doesn't exist yet, create it first.

## The arc-fact normalized form

Every fetcher emits zero or more `ArcFact` records. The schema:

```python
@dataclass(frozen=True)
class ArcFact:
    period: Period                       # e.g., "2024-Q4"
    source_node_id: str                  # issuer of the claim
    target_node_id: str                  # holder of the claim
    instrument_class: ArcClass           # A1..A12 from project plan §4
    dollar_amount_millions: Decimal      # always in millions USD
    measurement_basis: str               # "stock_eop" | "flow_period" | "average"
    data_quality_flag: DataQualityFlag   # DIRECT_MEASURED | MARGINAL_INFERRED | ...
    provenance_source: str               # source_id of this fetcher
    provenance_url: str                  # specific URL the value came from
    provenance_filing: str | None        # specific filing identifier
    provenance_page: int | None          # for PDF sources, page number
    provenance_field: str                # specific table/cell/tag the value was read from
    sha256_of_source: str                # of the underlying acquired file
```

Two of these merit emphasis:

- **`dollar_amount_millions`** is always in millions of USD. Always. If the source publishes in thousands or billions, convert in the parser. Document the conversion in the docstring.
- **`provenance_*` fields** are mandatory. Without them, the arc cannot be audited or replicated.

## Acquisition discipline

- **Content-address every raw file.** The acquire step writes to `data/raw/{source_id}/{period}/{filename}` and records the SHA-256. Subsequent runs check the SHA-256 to detect changes upstream.
- **Cache.** Once acquired, do not re-download for the same period. Re-acquisition only on explicit request (e.g., a `--refresh` flag) or if the source content has changed (detected by HEAD request or freshness check).
- **Rate-limit.** Respect the source's rate limits. SEC EDGAR allows ~10 requests/sec but expects a descriptive User-Agent. Other sources may have stricter limits.
- **Resilience.** Fetchers must handle network failures, partial downloads, and malformed files gracefully. A fetcher that crashes on a transient network error blocks the whole pipeline.

## Parsing discipline

- **Schema versioning.** If the source has changed schema across history (most sources have), the parser dispatches on a schema version derived from the period and/or the file structure. New schema versions are added at the bottom of the parser, never replacing old ones.
- **Strict type conversion.** Use `Decimal`, not `float`, for dollar amounts. Conservation laws are sensitive to floating-point error.
- **Identifier resolution.** Entity names in the source must be resolved to canonical CLAIM-WEB node IDs (`insurer:MET`, `bank:JPM`, etc.). Maintain a per-fetcher mapping table; never embed magic strings.
- **Unknown identifiers go to a registry** under `claimweb/registry/unmapped/{source_id}_{period}.json` for human review. Don't silently drop unknown entities — they're either new entities to register or data-quality issues.

## Testing requirements

Every fetcher has:
- A unit test using a captured sample of the source (a small fixture under `tests/fixtures/{source_id}/`). The test verifies parse() on the fixture.
- A property-based test (hypothesis) verifying that emitted ArcFacts pass schema validation.
- An integration test that runs `acquire(period)` then `parse(handle)` on a single recent period. May be marked `@pytest.mark.integration` so it isn't part of the default fast test run.

## What not to do

- Do not implement the fetcher without first spawning the `data-source-investigator` subagent for any source not already characterized in `docs/data_dictionary/sources/`.
- Do not parse without recording provenance. Every emitted arc must be traceable to the source file, page/section, and specific field.
- Do not silently "fix" data anomalies. Surface them; let the user decide.
- Do not embed paid-aggregator URLs even as fallbacks. The hooks will block writes containing forbidden patterns, but the rule predates the hook.
