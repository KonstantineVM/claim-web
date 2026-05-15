"""BaseFetcher abstraction and ArcFact schema (project plan §11, §12).

Every data-source fetcher in claimweb/fetchers/ subclasses BaseFetcher and
emits ArcFact records.  The contract here is the single integration point that
the normalizer, constraint compiler, and downstream solvers depend on.

Types defined here
------------------
Period              Quarter string wrapper ("2024-Q4"); validated on construction.
ArcClass            Arc-instrument taxonomy A1..A12 (project plan §4).
DataQualityFlag     Seven-value epistemic taxonomy (project plan §12).
RawDataHandle       Content-addressed reference to acquired raw files.
ArcFact             Immutable normalized arc record; Decimal dollar amounts.
ValidationIssue     Single discrepancy surfaced by a fetcher's validate step.
ValidationReport    Collection of ValidationIssues for one (fetcher, period) run.
BaseFetcher         Abstract base class every fetcher must subclass.
"""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Period
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^(\d{4})-Q([1-4])$")


class Period:
    """Immutable, validated quarter identifier, e.g. '2024-Q4'.

    The canonical form is YYYY-Q[1-4].  Periods are orderable; "2024-Q1" <
    "2024-Q4" < "2025-Q1".
    """

    __slots__ = ("_value", "_year", "_quarter")

    def __init__(self, value: str) -> None:
        m = _PERIOD_RE.match(value)
        if not m:
            raise ValueError(
                f"Period must match YYYY-Q[1-4]; got {value!r}"
            )
        self._value: str = value
        self._year: int = int(m.group(1))
        self._quarter: int = int(m.group(2))

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def year(self) -> int:
        return self._year

    @property
    def quarter(self) -> int:
        return self._quarter

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Period({self._value!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Period):
            return self._value == other._value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)

    def __lt__(self, other: Period) -> bool:
        if not isinstance(other, Period):
            return NotImplemented  # type: ignore[return-value]
        return (self._year, self._quarter) < (other._year, other._quarter)

    def __le__(self, other: Period) -> bool:
        return self == other or self < other

    def __gt__(self, other: Period) -> bool:
        return not self <= other

    def __ge__(self, other: Period) -> bool:
        return not self < other


# ---------------------------------------------------------------------------
# ArcClass  (project plan §4)
# ---------------------------------------------------------------------------


class ArcClass(Enum):
    """Arc-instrument taxonomy from project plan §4."""

    A1 = "A1"   # Funding agreements (cash-funded, on-shore)
    A2 = "A2"   # FABNs (Funding Agreement-Backed Notes)
    A3 = "A3"   # FHLB advances
    A4 = "A4"   # Repo (securities sold under agreements to repurchase)
    A5 = "A5"   # Securities-lending cash collateral
    A6 = "A6"   # Reinsurance treaties (offshore-cession)
    A7 = "A7"   # CLO mezzanine tranches
    A8 = "A8"   # Money market fund shares
    A9 = "A9"   # Bank deposits
    A10 = "A10" # Government securities (Treasuries, agency MBS)
    A11 = "A11" # Equity claims (common and preferred stock)
    A12 = "A12" # Other liabilities (residual)


# ---------------------------------------------------------------------------
# DataQualityFlag  (project plan §12)
# ---------------------------------------------------------------------------


class DataQualityFlag(Enum):
    """Epistemic quality flags carried by every ArcFact (project plan §12).

    Assignment priority (best to worst):
      DIRECT_MEASURED > DOUBLE_ENTRY_INFERRED > MARGINAL_INFERRED
      > SECTORAL_DISAGGREGATED > PROXY > MODEL_ESTIMATE > UNOBSERVED
    """

    DIRECT_MEASURED = "DIRECT_MEASURED"
    DOUBLE_ENTRY_INFERRED = "DOUBLE_ENTRY_INFERRED"
    MARGINAL_INFERRED = "MARGINAL_INFERRED"
    SECTORAL_DISAGGREGATED = "SECTORAL_DISAGGREGATED"
    PROXY = "PROXY"
    MODEL_ESTIMATE = "MODEL_ESTIMATE"
    UNOBSERVED = "UNOBSERVED"

    @property
    def priority(self) -> int:
        """Lower number = higher quality."""
        return _FLAG_PRIORITY[self]


_FLAG_PRIORITY: dict[DataQualityFlag, int] = {
    DataQualityFlag.DIRECT_MEASURED: 0,
    DataQualityFlag.DOUBLE_ENTRY_INFERRED: 1,
    DataQualityFlag.MARGINAL_INFERRED: 2,
    DataQualityFlag.SECTORAL_DISAGGREGATED: 3,
    DataQualityFlag.PROXY: 4,
    DataQualityFlag.MODEL_ESTIMATE: 5,
    DataQualityFlag.UNOBSERVED: 6,
}


# ---------------------------------------------------------------------------
# RawDataHandle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawDataHandle:
    """Content-addressed reference to one or more acquired raw files.

    The acquire step writes files to data/raw/{source_id}/{period}/ and
    records their SHA-256.  Subsequent runs compare the stored hash to detect
    upstream changes.
    """

    source_id: str
    period: Period
    paths: tuple[Path, ...]
    sha256_by_path: dict[str, str]  # str(path) -> hex SHA-256

    @classmethod
    def from_paths(cls, source_id: str, period: Period, paths: list[Path]) -> RawDataHandle:
        """Build a handle by computing SHA-256 of each file on disk."""
        sha_map: dict[str, str] = {}
        for p in paths:
            sha_map[str(p)] = _sha256_file(p)
        return cls(
            source_id=source_id,
            period=period,
            paths=tuple(paths),
            sha256_by_path=sha_map,
        )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# ArcFact
# ---------------------------------------------------------------------------

_VALID_MEASUREMENT_BASES = frozenset({"stock_eop", "flow_period", "average"})


@dataclass(frozen=True)
class ArcFact:
    """Immutable normalized arc record emitted by every fetcher.

    Represents a single financial claim from source_node_id to target_node_id
    for a given period.  Dollar amounts are always in millions of USD using
    Decimal arithmetic (project plan §19; decimal-arithmetic rule in CLAUDE.md).

    Provenance fields are mandatory — every arc must be traceable back to the
    exact source file, page/section, and field it was read from.
    """

    period: Period
    source_node_id: str
    target_node_id: str
    instrument_class: ArcClass
    dollar_amount_millions: Decimal
    measurement_basis: str  # "stock_eop" | "flow_period" | "average"
    data_quality_flag: DataQualityFlag
    provenance_source: str   # source_id of the emitting fetcher
    provenance_url: str      # specific URL the value was retrieved from
    provenance_filing: str | None  # specific filing identifier (e.g. CIK+period)
    provenance_page: int | None    # page number for PDF sources
    provenance_field: str          # table/cell/XBRL tag the value came from
    sha256_of_source: str          # SHA-256 of the underlying acquired file

    def __post_init__(self) -> None:
        if self.measurement_basis not in _VALID_MEASUREMENT_BASES:
            raise ValueError(
                f"measurement_basis must be one of {sorted(_VALID_MEASUREMENT_BASES)!r}; "
                f"got {self.measurement_basis!r}"
            )
        if not isinstance(self.dollar_amount_millions, Decimal):
            raise TypeError(
                "dollar_amount_millions must be a Decimal; "
                f"got {type(self.dollar_amount_millions).__name__}"
            )
        if not self.source_node_id:
            raise ValueError("source_node_id must be non-empty")
        if not self.target_node_id:
            raise ValueError("target_node_id must be non-empty")
        if not self.provenance_url:
            raise ValueError("provenance_url must be non-empty")
        if not self.provenance_field:
            raise ValueError("provenance_field must be non-empty")
        if len(self.sha256_of_source) != 64:
            raise ValueError(
                f"sha256_of_source must be a 64-char hex string; "
                f"got length {len(self.sha256_of_source)}"
            )

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict; Decimal rendered as string."""
        return {
            "period": str(self.period),
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "instrument_class": self.instrument_class.value,
            "dollar_amount_millions": str(self.dollar_amount_millions),
            "measurement_basis": self.measurement_basis,
            "data_quality_flag": self.data_quality_flag.value,
            "provenance_source": self.provenance_source,
            "provenance_url": self.provenance_url,
            "provenance_filing": self.provenance_filing,
            "provenance_page": self.provenance_page,
            "provenance_field": self.provenance_field,
            "sha256_of_source": self.sha256_of_source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ArcFact:
        """Deserialize from a dict produced by to_dict()."""
        return cls(
            period=Period(d["period"]),
            source_node_id=d["source_node_id"],
            target_node_id=d["target_node_id"],
            instrument_class=ArcClass(d["instrument_class"]),
            dollar_amount_millions=Decimal(d["dollar_amount_millions"]),
            measurement_basis=d["measurement_basis"],
            data_quality_flag=DataQualityFlag(d["data_quality_flag"]),
            provenance_source=d["provenance_source"],
            provenance_url=d["provenance_url"],
            provenance_filing=d.get("provenance_filing"),
            provenance_page=d.get("provenance_page"),
            provenance_field=d["provenance_field"],
            sha256_of_source=d["sha256_of_source"],
        )


# ---------------------------------------------------------------------------
# ValidationIssue / ValidationReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationIssue:
    """A single discrepancy surfaced during fetcher-specific validation."""

    severity: Literal["error", "warning", "info"]
    code: str        # short machine-readable identifier, e.g. "TOTAL_MISMATCH"
    message: str     # human-readable description
    affected_arcs: tuple[str, ...] = field(default_factory=tuple)  # optional arc IDs


@dataclass
class ValidationReport:
    """Collection of ValidationIssues for one (source_id, period) run.

    Discrepancies are reported here; they are never silently corrected.
    The pipeline decides whether to proceed based on is_clean.
    """

    source_id: str
    period: Period
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def add_issue(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    def error(self, code: str, message: str, affected_arcs: tuple[str, ...] = ()) -> None:
        self.add_issue(ValidationIssue("error", code, message, affected_arcs))

    def warning(self, code: str, message: str, affected_arcs: tuple[str, ...] = ()) -> None:
        self.add_issue(ValidationIssue("warning", code, message, affected_arcs))

    def info(self, code: str, message: str, affected_arcs: tuple[str, ...] = ()) -> None:
        self.add_issue(ValidationIssue("info", code, message, affected_arcs))


# ---------------------------------------------------------------------------
# BaseFetcher
# ---------------------------------------------------------------------------


class BaseFetcher(ABC):
    """Abstract base class for all CLAIM-WEB data-source fetchers.

    Subclasses must declare class-level ``source_id`` and ``cadence``, and
    implement the four abstract methods.  The fetcher-author skill documents
    all conventions that subclasses must follow.
    """

    source_id: str
    cadence: Literal["annual", "quarterly", "monthly"]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if ABC not in cls.__bases__:
            for attr in ("source_id", "cadence"):
                if not hasattr(cls, attr):
                    raise TypeError(
                        f"{cls.__name__} must define the class attribute {attr!r}"
                    )

    @abstractmethod
    def list_available_periods(self) -> list[Period]:
        """Enumerate periods for which raw data can be acquired."""

    @abstractmethod
    def acquire(self, period: Period) -> RawDataHandle:
        """Download (or read from cache) the raw data for *period*.

        Writes to data/raw/{source_id}/{period}/ with content-addressed naming.
        Returns a handle referencing the file(s) and their SHA-256.
        Re-acquisition is skipped if the cached file's SHA-256 matches; it is
        forced only by an explicit ``--refresh`` flag passed at the CLI level.
        """

    @abstractmethod
    def parse(self, handle: RawDataHandle) -> list[ArcFact]:
        """Parse the raw data into the normalized arc-fact form.

        Every emitted ArcFact must have all provenance fields set and a valid
        data_quality_flag.  Unknown entity identifiers go to
        claimweb/registry/unmapped/{source_id}_{period}.json rather than being
        silently dropped.
        """

    @abstractmethod
    def validate(self, facts: list[ArcFact]) -> ValidationReport:
        """Run fetcher-specific sanity checks on the parsed facts.

        Checks source-disclosed totals against sum of parsed arcs, etc.
        Discrepancies surface as ValidationIssues; they are never silently
        corrected.
        """

    def run(self, period: Period) -> tuple[list[ArcFact], ValidationReport]:
        """Convenience method: acquire → parse → validate in one call."""
        handle = self.acquire(period)
        facts = self.parse(handle)
        report = self.validate(facts)
        return facts, report
