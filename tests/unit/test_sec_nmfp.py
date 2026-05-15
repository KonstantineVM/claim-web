"""Unit tests for claimweb.fetchers.sec_nmfp.

Covers:
- _period_to_month_end: last calendar day of each quarter
- _period_to_filing_window: EDGAR search window calculation
- _parse_rep_period_date: date parsing including edge cases
- _date_to_period: date → quarter mapping
- _normalise_name: issuer name slug generation
- _spv_node_id: CUSIP-based and name-based source node IDs
- _mmf_node_id: series-ID-based and CIK-based target node IDs
- _text: element text extraction with namespace handling
- _parse_nmfp_xml: fixture-based parse for prime and government funds
- SecNmfpFetcher.parse: end-to-end fixture parse via RawDataHandle
- SecNmfpFetcher.validate: clean path, empty facts, negative, wrong arc class
- SecNmfpFetcher.list_available_periods: directory scanning
- SecNmfpFetcher._find_primary_doc: submissions JSON parsing
- Property-based (hypothesis): ArcFact schema compliance
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from claimweb.fetchers.base import (
    ArcClass,
    ArcFact,
    DataQualityFlag,
    Period,
    RawDataHandle,
    ValidationReport,
)
from claimweb.fetchers.sec_nmfp import (
    _FABN_CATEGORIES,
    _NMFP_NS,
    _NS,
    _PRIME_FUND_CATEGORIES,
    _REQUEST_INTERVAL_S,
    _USD_TO_MM,
    SecNmfpFetcher,
    _date_to_period,
    _mmf_node_id,
    _normalise_name,
    _parse_nmfp_xml,
    _parse_rep_period_date,
    _period_to_filing_window,
    _period_to_month_end,
    _spv_node_id,
    _text,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "sec_nmfp"
PRIME_FUND_XML = FIXTURE_DIR / "prime_fund_q4_2024.xml"
GOVT_FUND_XML = FIXTURE_DIR / "govt_fund_q4_2024.xml"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_handle(paths: list[Path], period: Period) -> RawDataHandle:
    return RawDataHandle.from_paths("sec_nmfp", period, paths)


def _make_prime_handle(tmp_path: Path, period: Period = Period("2024-Q4")) -> RawDataHandle:
    """Build a handle pointing at the prime fund fixture."""
    dest = tmp_path / "prime_fund.xml"
    dest.write_bytes(PRIME_FUND_XML.read_bytes())
    return _make_handle([dest], period)


def _make_minimal_xml(
    fund_category: str = "Prime",
    rep_period_date: str = "2024-12-31",
    series_id: str = "S000099999",
    cik: str = "0000999999",
    holdings: list[dict] | None = None,
) -> bytes:
    """Build a minimal valid N-MFP2 XML document."""
    holding_xml = ""
    if holdings:
        for h in holdings:
            cusip_block = (
                f"<cusip xmlns='http://www.sec.gov/edgar/nmfp'>{h.get('cusip', '')}</cusip>"
                if h.get("cusip")
                else ""
            )
            identifiers = (
                f"<identifiers xmlns='http://www.sec.gov/edgar/nmfp'>{cusip_block}</identifiers>"
            )
            holding_xml += f"""
    <invstOrSec xmlns="http://www.sec.gov/edgar/nmfp">
      <name>{h.get('name', 'Test Issuer')}</name>
      {identifiers}
      <category>{h.get('category', 'Other Note')}</category>
      <amortizedCostAmt>{h.get('amount', '100000000')}</amortizedCostAmt>
      <maturityDate>{h.get('maturity', '2025-06-30')}</maturityDate>
      <isDemandFeature>{h.get('isDemandFeature', 'N')}</isDemandFeature>
    </invstOrSec>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp">
  <formData>
    <genInfo>
      <seriesName>Test Fund</seriesName>
      <seriesId>{series_id}</seriesId>
      <cik>{cik}</cik>
      <repPeriodDate>{rep_period_date}</repPeriodDate>
      <isNMFP1>N</isNMFP1>
      <fundCategory>{fund_category}</fundCategory>
      <totalNetAssets>1000000000</totalNetAssets>
    </genInfo>
    {holding_xml}
  </formData>
</edgarSubmission>""".encode()


# ──────────────────────────────────────────────────────────────────────────────
# _period_to_month_end
# ──────────────────────────────────────────────────────────────────────────────


class TestPeriodToMonthEnd:
    @pytest.mark.parametrize(
        "period_str, expected",
        [
            ("2024-Q1", date(2024, 3, 31)),
            ("2024-Q2", date(2024, 6, 30)),
            ("2024-Q3", date(2024, 9, 30)),
            ("2024-Q4", date(2024, 12, 31)),
            ("2000-Q1", date(2000, 3, 31)),
            ("2020-Q2", date(2020, 6, 30)),
        ],
    )
    def test_quarter_end_dates(self, period_str: str, expected: date) -> None:
        assert _period_to_month_end(Period(period_str)) == expected

    def test_returns_date_object(self) -> None:
        result = _period_to_month_end(Period("2024-Q4"))
        assert isinstance(result, date)

    def test_q4_is_december_31(self) -> None:
        d = _period_to_month_end(Period("2023-Q4"))
        assert d.month == 12
        assert d.day == 31

    def test_q2_is_june_30(self) -> None:
        d = _period_to_month_end(Period("2023-Q2"))
        assert d.month == 6
        assert d.day == 30


# ──────────────────────────────────────────────────────────────────────────────
# _period_to_filing_window
# ──────────────────────────────────────────────────────────────────────────────


class TestPeriodToFilingWindow:
    def test_start_is_day_after_month_end(self) -> None:
        start, _ = _period_to_filing_window(Period("2024-Q4"))
        assert start == date(2025, 1, 1)

    def test_end_is_25_days_after_month_end(self) -> None:
        _, end = _period_to_filing_window(Period("2024-Q4"))
        assert end == date(2025, 1, 25)

    def test_q3_window(self) -> None:
        start, end = _period_to_filing_window(Period("2024-Q3"))
        assert start == date(2024, 10, 1)
        assert end == date(2024, 10, 25)

    def test_start_before_end(self) -> None:
        start, end = _period_to_filing_window(Period("2024-Q1"))
        assert start < end

    def test_window_spans_25_days(self) -> None:
        start, end = _period_to_filing_window(Period("2024-Q2"))
        assert (end - start).days == 24  # 25-day exclusive window


# ──────────────────────────────────────────────────────────────────────────────
# _parse_rep_period_date
# ──────────────────────────────────────────────────────────────────────────────


class TestParseRepPeriodDate:
    @pytest.mark.parametrize(
        "date_str, expected",
        [
            ("2024-12-31", date(2024, 12, 31)),
            ("2024-09-30", date(2024, 9, 30)),
            ("2024-03-31", date(2024, 3, 31)),
            ("2000-01-01", date(2000, 1, 1)),
            ("  2024-12-31  ", date(2024, 12, 31)),  # whitespace
        ],
    )
    def test_valid_dates(self, date_str: str, expected: date) -> None:
        assert _parse_rep_period_date(date_str) == expected

    @pytest.mark.parametrize(
        "date_str",
        ["", "not-a-date", "2024/12/31", "12-31-2024", "  "],
    )
    def test_invalid_dates_return_none(self, date_str: str) -> None:
        assert _parse_rep_period_date(date_str) is None

    def test_none_input_returns_none(self) -> None:
        assert _parse_rep_period_date(None) is None  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────────
# _date_to_period
# ──────────────────────────────────────────────────────────────────────────────


class TestDateToPeriod:
    @pytest.mark.parametrize(
        "d, expected",
        [
            (date(2024, 1, 15), "2024-Q1"),
            (date(2024, 3, 31), "2024-Q1"),
            (date(2024, 4, 1), "2024-Q2"),
            (date(2024, 6, 30), "2024-Q2"),
            (date(2024, 7, 1), "2024-Q3"),
            (date(2024, 9, 30), "2024-Q3"),
            (date(2024, 10, 1), "2024-Q4"),
            (date(2024, 12, 31), "2024-Q4"),
        ],
    )
    def test_month_to_quarter_mapping(self, d: date, expected: str) -> None:
        assert _date_to_period(d) == Period(expected)

    def test_returns_period_object(self) -> None:
        assert isinstance(_date_to_period(date(2024, 12, 31)), Period)


# ──────────────────────────────────────────────────────────────────────────────
# _normalise_name
# ──────────────────────────────────────────────────────────────────────────────


class TestNormaliseName:
    def test_lowercase(self) -> None:
        assert _normalise_name("MetLife Funding LLC") == "metlife_funding_llc"

    def test_special_chars_replaced(self) -> None:
        result = _normalise_name("Test & Co., Ltd.")
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in result)

    def test_max_60_chars(self) -> None:
        long_name = "A" * 80
        assert len(_normalise_name(long_name)) <= 60

    def test_empty_string(self) -> None:
        result = _normalise_name("")
        assert isinstance(result, str)

    def test_strips_trailing_underscores(self) -> None:
        result = _normalise_name("Test   ")
        assert not result.endswith("_")


# ──────────────────────────────────────────────────────────────────────────────
# _spv_node_id
# ──────────────────────────────────────────────────────────────────────────────


class TestSpvNodeId:
    def test_valid_cusip_produces_cusip_based_id(self) -> None:
        assert _spv_node_id("59156RAB5", "MetLife") == "spv:cusip:59156RAB5"

    def test_none_cusip_produces_name_based_id(self) -> None:
        result = _spv_node_id(None, "MetLife Funding LLC")
        assert result.startswith("spv:name:")

    def test_empty_cusip_produces_name_based_id(self) -> None:
        result = _spv_node_id("", "MetLife Funding LLC")
        assert result.startswith("spv:name:")

    def test_short_cusip_produces_name_based_id(self) -> None:
        # CUSIP must be 9 chars
        result = _spv_node_id("12345", "MetLife")
        assert result.startswith("spv:name:")

    def test_non_alphanum_cusip_produces_name_based_id(self) -> None:
        result = _spv_node_id("123-4567-8", "MetLife")
        assert result.startswith("spv:name:")

    def test_nine_char_alnum_cusip_used(self) -> None:
        result = _spv_node_id("123456789", "SomeName")
        assert result == "spv:cusip:123456789"

    def test_cusip_preserved_as_given(self) -> None:
        # CUSIPs are case-sensitive; preserve exactly
        result = _spv_node_id("59156RAB5", "MetLife")
        assert "59156RAB5" in result


# ──────────────────────────────────────────────────────────────────────────────
# _mmf_node_id
# ──────────────────────────────────────────────────────────────────────────────


class TestMmfNodeId:
    def test_series_id_used_when_available(self) -> None:
        assert _mmf_node_id("S000004059", "0000277751") == "mmf:S000004059"

    def test_cik_fallback_when_no_series_id(self) -> None:
        result = _mmf_node_id(None, "277751")
        assert result.startswith("mmf:cik:")

    def test_cik_zero_padded_to_10_digits(self) -> None:
        result = _mmf_node_id(None, "277751")
        assert result == "mmf:cik:0000277751"

    def test_empty_series_id_uses_cik(self) -> None:
        result = _mmf_node_id("", "999999")
        assert result.startswith("mmf:cik:")

    def test_unknown_when_both_absent(self) -> None:
        result = _mmf_node_id(None, "")
        assert result == "mmf:unknown"

    def test_series_id_must_start_with_s(self) -> None:
        # IDs not starting with "S" fall back to CIK
        result = _mmf_node_id("999999", "277751")
        assert result.startswith("mmf:cik:")


# ──────────────────────────────────────────────────────────────────────────────
# _text element accessor
# ──────────────────────────────────────────────────────────────────────────────


class TestText:
    def _make_elem(self, tag: str, text: str, ns: str = _NMFP_NS) -> ET.Element:
        parent = ET.Element(f"{{{ns}}}parent")
        child = ET.SubElement(parent, f"{{{ns}}}{tag}")
        child.text = text
        return parent

    def test_finds_namespaced_child(self) -> None:
        elem = self._make_elem("fundCategory", "Prime")
        assert _text(elem, "fundCategory") == "Prime"

    def test_returns_none_when_absent(self) -> None:
        elem = ET.Element("parent")
        assert _text(elem, "missingTag") is None

    def test_strips_whitespace(self) -> None:
        elem = self._make_elem("seriesId", "  S000004059  ")
        assert _text(elem, "seriesId") == "S000004059"

    def test_empty_text_returns_none(self) -> None:
        elem = self._make_elem("seriesId", "")
        assert _text(elem, "seriesId") is None

    def test_whitespace_only_returns_none(self) -> None:
        elem = self._make_elem("seriesId", "   ")
        assert _text(elem, "seriesId") is None


# ──────────────────────────────────────────────────────────────────────────────
# _parse_nmfp_xml — prime fund fixture
# ──────────────────────────────────────────────────────────────────────────────


class TestParseNmfpXmlPrimeFund:
    """Tests using the prime_fund_q4_2024.xml fixture."""

    def _load(self, target_period: Period | None = None) -> list[ArcFact]:
        xml_bytes = PRIME_FUND_XML.read_bytes()
        return _parse_nmfp_xml(
            xml_bytes,
            source_url="fixture://prime_fund_q4_2024.xml",
            sha256="a" * 64,
            target_period=target_period,
        )

    def test_returns_list(self) -> None:
        assert isinstance(self._load(), list)

    def test_only_fabn_categories_emitted(self) -> None:
        # Fixture: 2×Other Note + 1×Other Instrument + 1×US Treasury → 3 FABN facts
        facts = self._load()
        assert len(facts) == 4  # 2 Other Note + 1 Other Instrument + 1 No-CUSIP Other Note

    def test_treasury_holding_excluded(self) -> None:
        facts = self._load()
        cusips = {
            f.source_node_id
            for f in facts
            if "912828YK0" in f.source_node_id
        }
        assert not cusips, "Treasury holding should not be in facts"

    def test_period_is_q4_2024(self) -> None:
        for f in self._load():
            assert f.period == Period("2024-Q4")

    def test_target_node_is_mmf(self) -> None:
        for f in self._load():
            assert f.target_node_id.startswith("mmf:")

    def test_mmf_uses_series_id(self) -> None:
        facts = self._load()
        assert all(f.target_node_id == "mmf:S000099999" for f in facts)

    def test_source_nodes_are_spv(self) -> None:
        for f in self._load():
            assert f.source_node_id.startswith("spv:")

    def test_cusip_based_source_node(self) -> None:
        facts = self._load()
        metlife_fact = next(
            (f for f in facts if "59156RAB5" in f.source_node_id), None
        )
        assert metlife_fact is not None
        assert metlife_fact.source_node_id == "spv:cusip:59156RAB5"

    def test_prudential_cusip_based(self) -> None:
        facts = self._load()
        pru_fact = next(
            (f for f in facts if "74432VAB3" in f.source_node_id), None
        )
        assert pru_fact is not None
        assert pru_fact.source_node_id == "spv:cusip:74432VAB3"

    def test_no_cusip_falls_back_to_name(self) -> None:
        facts = self._load()
        name_based = [f for f in facts if f.source_node_id.startswith("spv:name:")]
        assert len(name_based) == 1  # "No-CUSIP Funding SPV" holding

    def test_amounts_in_millions(self) -> None:
        facts = self._load()
        metlife_fact = next(f for f in facts if "59156RAB5" in f.source_node_id)
        # 100_000_000 raw USD → 100 MM
        assert metlife_fact.dollar_amount_millions == Decimal("100")

    def test_prudential_amount(self) -> None:
        facts = self._load()
        pru_fact = next(f for f in facts if "74432VAB3" in f.source_node_id)
        # 50_000_000 raw USD → 50 MM
        assert pru_fact.dollar_amount_millions == Decimal("50")

    def test_lincoln_amount(self) -> None:
        # Lincoln uses "Other Instrument" category
        facts = self._load()
        lincoln_fact = next(f for f in facts if "534187AA1" in f.source_node_id)
        # 75_000_000 raw USD → 75 MM
        assert lincoln_fact.dollar_amount_millions == Decimal("75")

    def test_arc_class_is_a2(self) -> None:
        for f in self._load():
            assert f.instrument_class == ArcClass.A2

    def test_measurement_basis_is_stock_eop(self) -> None:
        for f in self._load():
            assert f.measurement_basis == "stock_eop"

    def test_data_quality_flag_direct_measured(self) -> None:
        for f in self._load():
            assert f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED

    def test_provenance_source_is_sec_nmfp(self) -> None:
        for f in self._load():
            assert f.provenance_source == "sec_nmfp"

    def test_provenance_filing_contains_cik(self) -> None:
        for f in self._load():
            assert "0000999999" in (f.provenance_filing or "")

    def test_sha256_stored(self) -> None:
        sha = "b" * 64
        xml_bytes = PRIME_FUND_XML.read_bytes()
        facts = _parse_nmfp_xml(xml_bytes, "fixture://x", sha)
        for f in facts:
            assert f.sha256_of_source == sha

    def test_target_period_filter_accepts_matching(self) -> None:
        facts = self._load(target_period=Period("2024-Q4"))
        assert len(facts) > 0

    def test_target_period_filter_rejects_wrong_period(self) -> None:
        facts = self._load(target_period=Period("2024-Q3"))
        assert len(facts) == 0

    def test_provenance_field_contains_category(self) -> None:
        facts = self._load()
        for f in facts:
            assert "category=" in f.provenance_field


# ──────────────────────────────────────────────────────────────────────────────
# _parse_nmfp_xml — government fund (should be filtered)
# ──────────────────────────────────────────────────────────────────────────────


class TestParseNmfpXmlGovtFund:
    def test_government_fund_returns_empty(self) -> None:
        xml_bytes = GOVT_FUND_XML.read_bytes()
        facts = _parse_nmfp_xml(xml_bytes, "fixture://govt_fund.xml", "c" * 64)
        assert facts == []

    def test_government_fund_returns_list(self) -> None:
        xml_bytes = GOVT_FUND_XML.read_bytes()
        result = _parse_nmfp_xml(xml_bytes, "fixture://govt_fund.xml", "d" * 64)
        assert isinstance(result, list)


# ──────────────────────────────────────────────────────────────────────────────
# _parse_nmfp_xml — edge cases via minimal XML
# ──────────────────────────────────────────────────────────────────────────────


class TestParseNmfpXmlEdgeCases:
    def test_empty_bytes_returns_empty(self) -> None:
        facts = _parse_nmfp_xml(b"", "test://empty", "0" * 64)
        assert facts == []

    def test_malformed_xml_returns_empty(self) -> None:
        facts = _parse_nmfp_xml(b"<not valid xml>", "test://bad", "0" * 64)
        assert facts == []

    def test_missing_form_data_returns_empty(self) -> None:
        xml = b'<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp"/>'
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_missing_gen_info_returns_empty(self) -> None:
        xml = b"""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp">
  <formData/>
</edgarSubmission>"""
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_invalid_rep_period_date_returns_empty(self) -> None:
        xml = _make_minimal_xml(fund_category="Prime", rep_period_date="not-a-date")
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_non_prime_fund_returns_empty(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Government",
            holdings=[{"category": "Other Note", "amount": "1000000"}],
        )
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_tax_exempt_fund_returns_empty(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Tax Exempt",
            holdings=[{"category": "Other Note", "amount": "1000000"}],
        )
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_zero_amount_excluded(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Prime",
            holdings=[{"category": "Other Note", "amount": "0"}],
        )
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_missing_amount_excluded(self) -> None:
        xml = b"""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nmfp">
  <formData>
    <genInfo>
      <seriesName>Test</seriesName>
      <seriesId>S000099999</seriesId>
      <cik>0000999999</cik>
      <repPeriodDate>2024-12-31</repPeriodDate>
      <isNMFP1>N</isNMFP1>
      <fundCategory>Prime</fundCategory>
      <totalNetAssets>1000000000</totalNetAssets>
    </genInfo>
    <invstOrSec>
      <name>Test Issuer</name>
      <identifiers><cusip>123456789</cusip></identifiers>
      <category>Other Note</category>
      <maturityDate>2025-06-30</maturityDate>
    </invstOrSec>
  </formData>
</edgarSubmission>"""
        # No amortizedCostAmt element → should be skipped
        facts = _parse_nmfp_xml(xml, "test://x", "0" * 64)
        assert facts == []

    def test_negative_amount_excluded(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Prime",
            holdings=[{"category": "Other Note", "amount": "-1000000"}],
        )
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_invalid_amount_excluded(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Prime",
            holdings=[{"category": "Other Note", "amount": "not_a_number"}],
        )
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_non_fabn_category_excluded(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Prime",
            holdings=[{"category": "US Treasury Debt", "amount": "1000000"}],
        )
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_prime_fund_with_no_holdings_returns_empty(self) -> None:
        xml = _make_minimal_xml(fund_category="Prime", holdings=[])
        assert _parse_nmfp_xml(xml, "test://x", "0" * 64) == []

    def test_amount_correctly_converted_to_millions(self) -> None:
        # 1_000_000 raw USD → 1 MM
        xml = _make_minimal_xml(
            fund_category="Prime",
            holdings=[{"category": "Other Note", "amount": "1000000", "cusip": "123456789"}],
        )
        facts = _parse_nmfp_xml(xml, "test://x", "0" * 64)
        assert len(facts) == 1
        assert facts[0].dollar_amount_millions == Decimal("1")

    def test_large_amount_correctly_converted(self) -> None:
        # 5_000_000_000 raw USD → 5_000 MM
        xml = _make_minimal_xml(
            fund_category="Prime",
            holdings=[{"category": "Other Note", "amount": "5000000000", "cusip": "123456789"}],
        )
        facts = _parse_nmfp_xml(xml, "test://x", "0" * 64)
        assert facts[0].dollar_amount_millions == Decimal("5000")

    def test_other_instrument_category_included(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Prime",
            holdings=[{"category": "Other Instrument", "amount": "2000000", "cusip": "123456789"}],
        )
        facts = _parse_nmfp_xml(xml, "test://x", "0" * 64)
        assert len(facts) == 1

    def test_institutional_prime_fund_included(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Institutional Prime",
            holdings=[{"category": "Other Note", "amount": "1000000", "cusip": "123456789"}],
        )
        facts = _parse_nmfp_xml(xml, "test://x", "0" * 64)
        assert len(facts) == 1

    def test_retail_prime_fund_included(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Retail Prime",
            holdings=[{"category": "Other Note", "amount": "1000000", "cusip": "123456789"}],
        )
        facts = _parse_nmfp_xml(xml, "test://x", "0" * 64)
        assert len(facts) == 1

    def test_q3_period_from_september_date(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Prime",
            rep_period_date="2024-09-30",
            holdings=[{"category": "Other Note", "amount": "1000000", "cusip": "123456789"}],
        )
        facts = _parse_nmfp_xml(xml, "test://x", "0" * 64)
        assert facts[0].period == Period("2024-Q3")

    def test_multiple_holdings_from_same_fund(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Prime",
            holdings=[
                {"category": "Other Note", "amount": "1000000", "cusip": "111111111"},
                {"category": "Other Note", "amount": "2000000", "cusip": "222222222"},
                {"category": "Other Note", "amount": "3000000", "cusip": "333333333"},
            ],
        )
        facts = _parse_nmfp_xml(xml, "test://x", "0" * 64)
        assert len(facts) == 3

    def test_demand_feature_in_provenance_field(self) -> None:
        xml = _make_minimal_xml(
            fund_category="Prime",
            holdings=[{
                "category": "Other Note",
                "amount": "1000000",
                "cusip": "123456789",
                "isDemandFeature": "Y",
            }],
        )
        facts = _parse_nmfp_xml(xml, "test://x", "0" * 64)
        assert "isDemandFeature=Y" in facts[0].provenance_field


# ──────────────────────────────────────────────────────────────────────────────
# SecNmfpFetcher.parse — fixture-based via RawDataHandle
# ──────────────────────────────────────────────────────────────────────────────


class TestSecNmfpFetcherParse:
    def test_parse_prime_fixture_returns_facts(self, tmp_path: Path) -> None:
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        handle = _make_prime_handle(tmp_path)
        facts = fetcher.parse(handle)
        assert len(facts) > 0

    def test_parse_govt_fixture_returns_empty(self, tmp_path: Path) -> None:
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        dest = tmp_path / "govt_fund.xml"
        dest.write_bytes(GOVT_FUND_XML.read_bytes())
        handle = _make_handle([dest], Period("2024-Q4"))
        facts = fetcher.parse(handle)
        assert facts == []

    def test_parse_two_files_aggregates(self, tmp_path: Path) -> None:
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        dest1 = tmp_path / "prime.xml"
        dest2 = tmp_path / "govt.xml"
        dest1.write_bytes(PRIME_FUND_XML.read_bytes())
        dest2.write_bytes(GOVT_FUND_XML.read_bytes())
        handle = _make_handle([dest1, dest2], Period("2024-Q4"))
        facts = fetcher.parse(handle)
        assert len(facts) > 0  # Only prime fund contributes facts

    def test_parse_empty_handle_returns_empty(self, tmp_path: Path) -> None:
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        handle = _make_handle([], Period("2024-Q4"))
        assert fetcher.parse(handle) == []

    def test_parse_missing_file_skipped(self, tmp_path: Path) -> None:
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        ghost = tmp_path / "nonexistent.xml"
        # Build handle directly to avoid SHA-256 of a non-existent file.
        handle = RawDataHandle(
            source_id="sec_nmfp",
            period=Period("2024-Q4"),
            paths=(ghost,),
            sha256_by_path={str(ghost): "0" * 64},
        )
        facts = fetcher.parse(handle)
        assert facts == []

    def test_all_facts_are_arcfact_instances(self, tmp_path: Path) -> None:
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        handle = _make_prime_handle(tmp_path)
        for f in fetcher.parse(handle):
            assert isinstance(f, ArcFact)

    def test_all_facts_have_a2_arc_class(self, tmp_path: Path) -> None:
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        handle = _make_prime_handle(tmp_path)
        for f in fetcher.parse(handle):
            assert f.instrument_class == ArcClass.A2


# ──────────────────────────────────────────────────────────────────────────────
# SecNmfpFetcher.validate
# ──────────────────────────────────────────────────────────────────────────────


def _make_valid_fact(
    period: str = "2024-Q4",
    source_node: str = "spv:cusip:59156RAB5",
    target_node: str = "mmf:S000099999",
    amount: str = "100",
    arc_class: ArcClass = ArcClass.A2,
) -> ArcFact:
    return ArcFact(
        period=Period(period),
        source_node_id=source_node,
        target_node_id=target_node,
        instrument_class=arc_class,
        dollar_amount_millions=Decimal(amount),
        measurement_basis="stock_eop",
        data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
        provenance_source="sec_nmfp",
        provenance_url="test://fixture",
        provenance_filing="N-MFP_0000999999_2024-12-31",
        provenance_page=None,
        provenance_field="invstOrSec/amortizedCostAmt[category=Other Note,isDemandFeature=N]",
        sha256_of_source="a" * 64,
    )


class TestSecNmfpFetcherValidate:
    def _fetcher(self, tmp_path: Path) -> SecNmfpFetcher:
        return SecNmfpFetcher(data_root=tmp_path)

    def test_clean_facts_pass(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        facts = [_make_valid_fact(), _make_valid_fact(source_node="spv:cusip:74432VAB3")]
        report = fetcher.validate(facts)
        assert report.is_clean

    def test_empty_facts_info_not_error(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        report = fetcher.validate([])
        assert report.is_clean
        assert any(i.code == "NO_FABN_HOLDINGS" for i in report.issues)

    def test_empty_facts_info_severity(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        report = fetcher.validate([])
        info_issues = [i for i in report.issues if i.code == "NO_FABN_HOLDINGS"]
        assert all(i.severity == "info" for i in info_issues)

    def test_negative_amount_warning(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        bad_fact = ArcFact(
            period=Period("2024-Q4"),
            source_node_id="spv:cusip:123456789",
            target_node_id="mmf:S000099999",
            instrument_class=ArcClass.A2,
            dollar_amount_millions=Decimal("-10"),
            measurement_basis="stock_eop",
            data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
            provenance_source="sec_nmfp",
            provenance_url="test://x",
            provenance_filing=None,
            provenance_page=None,
            provenance_field="test",
            sha256_of_source="b" * 64,
        )
        report = fetcher.validate([bad_fact])
        assert any(i.code == "NEGATIVE_AMOUNT" for i in report.issues)
        assert any(i.severity == "warning" for i in report.issues)

    def test_wrong_arc_class_error(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        bad_fact = _make_valid_fact(arc_class=ArcClass.A3)
        report = fetcher.validate([bad_fact])
        assert not report.is_clean
        assert any(i.code == "WRONG_ARC_CLASS" for i in report.issues)

    def test_unexpected_source_prefix_warning(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        bad_fact = _make_valid_fact(source_node="insurer:MET")
        report = fetcher.validate([bad_fact])
        assert any(i.code == "UNEXPECTED_SOURCE_PREFIX" for i in report.issues)

    def test_unexpected_target_prefix_warning(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        bad_fact = _make_valid_fact(target_node="sector:fhlb")
        report = fetcher.validate([bad_fact])
        assert any(i.code == "UNEXPECTED_TARGET_PREFIX" for i in report.issues)

    def test_name_based_spv_ids_info(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        fact = _make_valid_fact(source_node="spv:name:some_funding_llc")
        report = fetcher.validate([fact])
        assert any(i.code == "NAME_BASED_SPV_IDS" for i in report.issues)
        info_issues = [i for i in report.issues if i.code == "NAME_BASED_SPV_IDS"]
        assert all(i.severity == "info" for i in info_issues)

    def test_validate_returns_validation_report(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        report = fetcher.validate([_make_valid_fact()])
        assert isinstance(report, ValidationReport)

    def test_report_source_id(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        report = fetcher.validate([_make_valid_fact()])
        assert report.source_id == "sec_nmfp"

    def test_multiple_name_based_ids_counted(self, tmp_path: Path) -> None:
        fetcher = self._fetcher(tmp_path)
        facts = [
            _make_valid_fact(source_node="spv:name:issuer_a"),
            _make_valid_fact(source_node="spv:name:issuer_b"),
            _make_valid_fact(source_node="spv:cusip:123456789"),
        ]
        report = fetcher.validate(facts)
        info = next(i for i in report.issues if i.code == "NAME_BASED_SPV_IDS")
        assert "2" in info.message


# ──────────────────────────────────────────────────────────────────────────────
# SecNmfpFetcher.list_available_periods
# ──────────────────────────────────────────────────────────────────────────────


class TestSecNmfpFetcherListAvailablePeriods:
    def test_empty_when_no_cache(self, tmp_path: Path) -> None:
        fetcher = SecNmfpFetcher(data_root=tmp_path / "nonexistent")
        assert fetcher.list_available_periods() == []

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        assert fetcher.list_available_periods() == []

    def test_single_period(self, tmp_path: Path) -> None:
        (tmp_path / "2024-Q4").mkdir()
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        assert fetcher.list_available_periods() == [Period("2024-Q4")]

    def test_multiple_periods_sorted(self, tmp_path: Path) -> None:
        for p in ["2024-Q4", "2024-Q1", "2023-Q3"]:
            (tmp_path / p).mkdir()
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        result = fetcher.list_available_periods()
        assert result == [Period("2023-Q3"), Period("2024-Q1"), Period("2024-Q4")]

    def test_non_period_dirs_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "2024-Q4").mkdir()
        (tmp_path / "bundle").mkdir()
        (tmp_path / "temp").mkdir()
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        assert fetcher.list_available_periods() == [Period("2024-Q4")]

    def test_files_not_counted_as_periods(self, tmp_path: Path) -> None:
        (tmp_path / "2024-Q4.xml").write_bytes(b"")
        fetcher = SecNmfpFetcher(data_root=tmp_path)
        assert fetcher.list_available_periods() == []


# ──────────────────────────────────────────────────────────────────────────────
# SecNmfpFetcher._find_primary_doc
# ──────────────────────────────────────────────────────────────────────────────


class TestFindPrimaryDoc:
    def test_returns_matching_primary_doc(self) -> None:
        sub_data = {
            "filings": {
                "recent": {
                    "accessionNumber": [
                        "0000999999-25-000001",
                        "0000999999-25-000002",
                    ],
                    "primaryDocument": [
                        "0000999999-25-000001.xml",
                        "0000999999-25-000002.xml",
                    ],
                }
            }
        }
        result = SecNmfpFetcher._find_primary_doc(sub_data, "0000999999-25-000001")
        assert result == "0000999999-25-000001.xml"

    def test_returns_none_when_accession_not_found(self) -> None:
        sub_data = {
            "filings": {
                "recent": {
                    "accessionNumber": ["0000999999-25-000001"],
                    "primaryDocument": ["0000999999-25-000001.xml"],
                }
            }
        }
        result = SecNmfpFetcher._find_primary_doc(sub_data, "0000999999-25-000099")
        assert result is None

    def test_returns_none_on_empty_data(self) -> None:
        assert SecNmfpFetcher._find_primary_doc({}, "0000999999-25-000001") is None

    def test_returns_none_on_empty_filings(self) -> None:
        sub_data = {"filings": {"recent": {"accessionNumber": [], "primaryDocument": []}}}
        assert SecNmfpFetcher._find_primary_doc(sub_data, "0000999999-25-000001") is None

    def test_handles_missing_filings_key(self) -> None:
        assert SecNmfpFetcher._find_primary_doc({"other": "data"}, "acc") is None


# ──────────────────────────────────────────────────────────────────────────────
# Module-level constant checks
# ──────────────────────────────────────────────────────────────────────────────


class TestModuleConstants:
    def test_fabn_categories_is_frozenset(self) -> None:
        assert isinstance(_FABN_CATEGORIES, frozenset)

    def test_prime_fund_categories_is_frozenset(self) -> None:
        assert isinstance(_PRIME_FUND_CATEGORIES, frozenset)

    def test_other_note_in_fabn_categories(self) -> None:
        assert "Other Note" in _FABN_CATEGORIES

    def test_prime_in_prime_categories(self) -> None:
        assert "Prime" in _PRIME_FUND_CATEGORIES

    def test_usd_to_mm_correct(self) -> None:
        assert _USD_TO_MM == Decimal("0.000001")

    def test_1M_usd_equals_1_mm(self) -> None:
        assert Decimal("1000000") * _USD_TO_MM == Decimal("1")

    def test_namespace_string(self) -> None:
        assert _NMFP_NS == "http://www.sec.gov/edgar/nmfp"

    def test_request_interval_is_positive(self) -> None:
        assert _REQUEST_INTERVAL_S > 0

    def test_request_interval_under_rate_limit(self) -> None:
        # 1 / _REQUEST_INTERVAL_S should be ≤ 10 req/sec
        assert (1 / _REQUEST_INTERVAL_S) <= 10.0

    def test_fetcher_source_id(self) -> None:
        assert SecNmfpFetcher.source_id == "sec_nmfp"

    def test_fetcher_cadence(self) -> None:
        assert SecNmfpFetcher.cadence == "monthly"


# ──────────────────────────────────────────────────────────────────────────────
# Property-based tests (hypothesis)
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(
    amount_raw=st.integers(min_value=1, max_value=10_000_000_000),
    cusip=st.text(
        alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=9,
        max_size=9,
    ),
    series_id=st.from_regex(r"S[0-9]{9}", fullmatch=True),
)
def test_property_parse_emits_valid_arcfacts(
    amount_raw: int,
    cusip: str,
    series_id: str,
) -> None:
    """All ArcFacts emitted by _parse_nmfp_xml satisfy the schema."""
    xml = _make_minimal_xml(
        fund_category="Prime",
        rep_period_date="2024-12-31",
        series_id=series_id,
        holdings=[{
            "category": "Other Note",
            "amount": str(amount_raw),
            "cusip": cusip,
        }],
    )
    facts = _parse_nmfp_xml(xml, "test://prop", "a" * 64)
    for f in facts:
        assert isinstance(f, ArcFact)
        assert f.instrument_class == ArcClass.A2
        assert f.measurement_basis == "stock_eop"
        assert f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED
        assert f.dollar_amount_millions > Decimal("0")
        assert f.source_node_id.startswith("spv:")
        assert f.target_node_id.startswith("mmf:")


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(
    amount_raw=st.integers(min_value=1_000_000, max_value=1_000_000_000_000),
)
def test_property_billion_to_million_conversion(amount_raw: int) -> None:
    """amortizedCostAmt (raw USD) is converted to millions without float error."""
    expected_mm = Decimal(str(amount_raw)) * Decimal("0.000001")
    xml = _make_minimal_xml(
        fund_category="Prime",
        holdings=[{
            "category": "Other Note",
            "amount": str(amount_raw),
            "cusip": "123456789",
        }],
    )
    facts = _parse_nmfp_xml(xml, "test://prop", "a" * 64)
    if facts:
        assert facts[0].dollar_amount_millions == expected_mm


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(
    category=st.sampled_from(sorted(_PRIME_FUND_CATEGORIES)),
    amount_raw=st.integers(min_value=1, max_value=10_000_000_000),
)
def test_property_all_prime_categories_produce_facts(
    category: str,
    amount_raw: int,
) -> None:
    """Every prime fund category produces ArcFacts for FABN holdings."""
    xml = _make_minimal_xml(
        fund_category=category,
        holdings=[{
            "category": "Other Note",
            "amount": str(amount_raw),
            "cusip": "123456789",
        }],
    )
    facts = _parse_nmfp_xml(xml, "test://prop", "a" * 64)
    assert len(facts) == 1
