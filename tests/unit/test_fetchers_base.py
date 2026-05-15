"""Unit and property-based tests for claimweb.fetchers.base.

Covers:
- Period: construction, validation, ordering, equality, hashing
- ArcClass: all 12 members present
- DataQualityFlag: all 7 members present; priority ordering
- ArcFact: construction, validation, round-trip serialisation
- ValidationReport: issue accumulation, is_clean semantics
- BaseFetcher: subclass contract enforcement
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from claimweb.fetchers.base import (
    ArcClass,
    ArcFact,
    BaseFetcher,
    DataQualityFlag,
    Period,
    RawDataHandle,
    ValidationIssue,
    ValidationReport,
)

# ---------------------------------------------------------------------------
# Helpers / strategies
# ---------------------------------------------------------------------------

_VALID_SHA256 = "a" * 64

_periods = st.builds(
    Period,
    st.from_regex(r"(19|20|21)\d{2}-Q[1-4]", fullmatch=True),
)

_arc_classes = st.sampled_from(list(ArcClass))
_dq_flags = st.sampled_from(list(DataQualityFlag))
_measurement_bases = st.sampled_from(["stock_eop", "flow_period", "average"])

_dollar_amounts = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_sha256s = st.from_regex(r"[0-9a-f]{64}", fullmatch=True)

_nonempty_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=120,
)

_arc_facts = st.builds(
    ArcFact,
    period=_periods,
    source_node_id=_nonempty_text,
    target_node_id=_nonempty_text,
    instrument_class=_arc_classes,
    dollar_amount_millions=_dollar_amounts,
    measurement_basis=_measurement_bases,
    data_quality_flag=_dq_flags,
    provenance_source=_nonempty_text,
    provenance_url=_nonempty_text,
    provenance_filing=st.one_of(st.none(), _nonempty_text),
    provenance_page=st.one_of(st.none(), st.integers(min_value=1, max_value=9999)),
    provenance_field=_nonempty_text,
    sha256_of_source=_sha256s,
)


# ---------------------------------------------------------------------------
# Period
# ---------------------------------------------------------------------------


class TestPeriod:
    def test_valid_construction(self):
        p = Period("2024-Q4")
        assert p.year == 2024
        assert p.quarter == 4

    def test_str(self):
        assert str(Period("2000-Q1")) == "2000-Q1"

    def test_repr(self):
        assert repr(Period("2000-Q1")) == "Period('2000-Q1')"

    @pytest.mark.parametrize(
        "bad",
        ["2024-Q5", "2024-Q0", "24-Q1", "2024Q4", "2024-q1", "", "foo", "2024-Q"],
    )
    def test_invalid_construction(self, bad):
        with pytest.raises(ValueError, match="Period must match"):
            Period(bad)

    def test_equality(self):
        assert Period("2024-Q4") == Period("2024-Q4")
        assert Period("2024-Q4") != Period("2024-Q3")

    def test_hash_consistent_with_equality(self):
        a, b = Period("2024-Q4"), Period("2024-Q4")
        assert hash(a) == hash(b)
        assert {a: 1}[b] == 1

    def test_ordering(self):
        quarters = [Period("2025-Q1"), Period("2024-Q4"), Period("2024-Q1")]
        assert sorted(quarters) == [Period("2024-Q1"), Period("2024-Q4"), Period("2025-Q1")]

    def test_le_ge(self):
        p1, p2 = Period("2024-Q1"), Period("2024-Q4")
        assert p1 <= p2
        assert p2 >= p1
        assert p1 <= p1


# ---------------------------------------------------------------------------
# ArcClass
# ---------------------------------------------------------------------------


class TestArcClass:
    def test_all_twelve_present(self):
        members = {m.value for m in ArcClass}
        assert members == {f"A{i}" for i in range(1, 13)}

    def test_round_trip_value(self):
        for member in ArcClass:
            assert ArcClass(member.value) is member


# ---------------------------------------------------------------------------
# DataQualityFlag
# ---------------------------------------------------------------------------


class TestDataQualityFlag:
    def test_all_seven_present(self):
        names = {m.name for m in DataQualityFlag}
        assert names == {
            "DIRECT_MEASURED",
            "DOUBLE_ENTRY_INFERRED",
            "MARGINAL_INFERRED",
            "SECTORAL_DISAGGREGATED",
            "PROXY",
            "MODEL_ESTIMATE",
            "UNOBSERVED",
        }

    def test_priority_ordering(self):
        flags_best_to_worst = [
            DataQualityFlag.DIRECT_MEASURED,
            DataQualityFlag.DOUBLE_ENTRY_INFERRED,
            DataQualityFlag.MARGINAL_INFERRED,
            DataQualityFlag.SECTORAL_DISAGGREGATED,
            DataQualityFlag.PROXY,
            DataQualityFlag.MODEL_ESTIMATE,
            DataQualityFlag.UNOBSERVED,
        ]
        for i in range(len(flags_best_to_worst) - 1):
            assert flags_best_to_worst[i].priority < flags_best_to_worst[i + 1].priority


# ---------------------------------------------------------------------------
# ArcFact construction and validation
# ---------------------------------------------------------------------------


class TestArcFactConstruction:
    def _minimal(self, **overrides) -> dict:
        base = dict(
            period=Period("2024-Q4"),
            source_node_id="insurer:MET",
            target_node_id="fhlb:FHLBNY",
            instrument_class=ArcClass.A3,
            dollar_amount_millions=Decimal("1234.56"),
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
            provenance_source="fhlb_combined",
            provenance_url="https://example.com/report.pdf",
            provenance_filing=None,
            provenance_page=12,
            provenance_field="Table 3, Row 7",
            sha256_of_source=_VALID_SHA256,
        )
        base.update(overrides)
        return base

    def test_happy_path(self):
        fact = ArcFact(**self._minimal())
        assert fact.dollar_amount_millions == Decimal("1234.56")
        assert fact.instrument_class is ArcClass.A3

    def test_rejects_float_dollar(self):
        with pytest.raises(TypeError, match="must be a Decimal"):
            ArcFact(**self._minimal(dollar_amount_millions=1234.56))

    def test_rejects_int_dollar(self):
        with pytest.raises(TypeError, match="must be a Decimal"):
            ArcFact(**self._minimal(dollar_amount_millions=1234))

    def test_rejects_bad_measurement_basis(self):
        with pytest.raises(ValueError, match="measurement_basis"):
            ArcFact(**self._minimal(measurement_basis="end_of_year"))

    def test_rejects_empty_source_node(self):
        with pytest.raises(ValueError, match="source_node_id"):
            ArcFact(**self._minimal(source_node_id=""))

    def test_rejects_empty_target_node(self):
        with pytest.raises(ValueError, match="target_node_id"):
            ArcFact(**self._minimal(target_node_id=""))

    def test_rejects_empty_provenance_url(self):
        with pytest.raises(ValueError, match="provenance_url"):
            ArcFact(**self._minimal(provenance_url=""))

    def test_rejects_empty_provenance_field(self):
        with pytest.raises(ValueError, match="provenance_field"):
            ArcFact(**self._minimal(provenance_field=""))

    def test_rejects_bad_sha256_length(self):
        with pytest.raises(ValueError, match="sha256_of_source"):
            ArcFact(**self._minimal(sha256_of_source="abc"))

    def test_frozen(self):
        fact = ArcFact(**self._minimal())
        with pytest.raises(Exception):
            fact.dollar_amount_millions = Decimal("0")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ArcFact serialisation round-trip
# ---------------------------------------------------------------------------


class TestArcFactSerialisation:
    @given(_arc_facts)
    @settings(max_examples=200)
    def test_dict_round_trip(self, fact: ArcFact) -> None:
        d = fact.to_dict()
        back = ArcFact.from_dict(d)
        assert back == fact

    @given(_arc_facts)
    @settings(max_examples=200)
    def test_dict_is_json_serialisable(self, fact: ArcFact) -> None:
        """to_dict() output must survive json.dumps / json.loads."""
        d = fact.to_dict()
        j = json.dumps(d)
        parsed = json.loads(j)
        back = ArcFact.from_dict(parsed)
        assert back == fact

    @given(_arc_facts)
    @settings(max_examples=200)
    def test_dollar_amount_preserved_exactly(self, fact: ArcFact) -> None:
        """Decimal precision must survive the to_dict/from_dict round-trip."""
        back = ArcFact.from_dict(fact.to_dict())
        assert back.dollar_amount_millions == fact.dollar_amount_millions


# ---------------------------------------------------------------------------
# ArcFact property tests
# ---------------------------------------------------------------------------


class TestArcFactProperties:
    @given(_arc_facts)
    def test_all_provenance_fields_present(self, fact: ArcFact) -> None:
        assert fact.provenance_source
        assert fact.provenance_url
        assert fact.provenance_field
        assert len(fact.sha256_of_source) == 64

    @given(_arc_facts)
    def test_measurement_basis_is_valid(self, fact: ArcFact) -> None:
        assert fact.measurement_basis in {"stock_eop", "flow_period", "average"}

    @given(_arc_facts)
    def test_dollar_amount_is_decimal(self, fact: ArcFact) -> None:
        assert isinstance(fact.dollar_amount_millions, Decimal)

    @given(_arc_facts)
    def test_period_is_period(self, fact: ArcFact) -> None:
        assert isinstance(fact.period, Period)

    @given(_arc_facts)
    def test_data_quality_flag_is_enum(self, fact: ArcFact) -> None:
        assert isinstance(fact.data_quality_flag, DataQualityFlag)

    @given(_arc_facts)
    def test_instrument_class_is_enum(self, fact: ArcFact) -> None:
        assert isinstance(fact.instrument_class, ArcClass)


# ---------------------------------------------------------------------------
# ValidationReport
# ---------------------------------------------------------------------------


class TestValidationReport:
    def _report(self, **kw) -> ValidationReport:
        return ValidationReport(
            source_id=kw.get("source_id", "test_source"),
            period=kw.get("period", Period("2024-Q4")),
        )

    def test_empty_report_is_clean(self):
        assert self._report().is_clean

    def test_warning_does_not_dirty_report(self):
        r = self._report()
        r.warning("W001", "some warning")
        assert r.is_clean

    def test_info_does_not_dirty_report(self):
        r = self._report()
        r.info("I001", "some info")
        assert r.is_clean

    def test_error_dirties_report(self):
        r = self._report()
        r.error("E001", "some error")
        assert not r.is_clean

    def test_issues_accumulate(self):
        r = self._report()
        r.error("E001", "first")
        r.warning("W001", "second")
        r.info("I001", "third")
        assert len(r.issues) == 3

    def test_add_issue_directly(self):
        r = self._report()
        issue = ValidationIssue("error", "X001", "direct add", ("arc:1",))
        r.add_issue(issue)
        assert r.issues[0] is issue
        assert not r.is_clean


# ---------------------------------------------------------------------------
# BaseFetcher: subclass contract enforcement
# ---------------------------------------------------------------------------


class TestBaseFetcherContract:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseFetcher()  # type: ignore[abstract]

    def test_concrete_subclass_without_source_id_raises(self):
        with pytest.raises(TypeError, match="source_id"):

            class BadFetcher(BaseFetcher):
                cadence = "quarterly"

                def list_available_periods(self):
                    return []

                def acquire(self, period):
                    ...

                def parse(self, handle):
                    return []

                def validate(self, facts):
                    return ValidationReport("bad", period=facts[0].period if facts else Period("2024-Q4"))

    def test_concrete_subclass_without_cadence_raises(self):
        with pytest.raises(TypeError, match="cadence"):

            class BadFetcher2(BaseFetcher):
                source_id = "bad"

                def list_available_periods(self):
                    return []

                def acquire(self, period):
                    ...

                def parse(self, handle):
                    return []

                def validate(self, facts):
                    return ValidationReport("bad", period=Period("2024-Q4"))

    def test_well_formed_subclass(self):
        class GoodFetcher(BaseFetcher):
            source_id = "good"
            cadence = "quarterly"

            def list_available_periods(self):
                return [Period("2024-Q4")]

            def acquire(self, period):
                return RawDataHandle(
                    source_id=self.source_id,
                    period=period,
                    paths=(),
                    sha256_by_path={},
                )

            def parse(self, handle):
                return []

            def validate(self, facts):
                return ValidationReport(self.source_id, handle.period)  # type: ignore[name-defined]

        # Should not raise
        fetcher = GoodFetcher()
        assert fetcher.source_id == "good"
        assert fetcher.list_available_periods() == [Period("2024-Q4")]
