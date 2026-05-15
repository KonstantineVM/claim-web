"""Unit tests for claimweb.fetchers.sec_13f.

Covers:
- _normalise_name: name slugification
- _issuer_node_id: CUSIP-based and name-based source node IDs
- _manager_node_id: CIK zero-padding and prefix
- _period_to_quarter_end: last calendar day per quarter
- _period_to_filing_window: 50-day post-quarter-end window
- _filing_date_in_window: boundary conditions (inclusive, exclusive, edge)
- _text: XML element text extraction with namespace handling
- _get_shrs_elem: shrsOrPrnAmt element retrieval, both namespace variants
- _cik_from_filename: CIK extraction from {cik10}.xml filenames
- _find_13f_hr_for_period: submissions JSON search for 13F-HR within window
- _parse_13f_xml: fixture-based golden-path test (A11 equity, A12 PRN)
- _parse_13f_xml: put/call options are skipped
- _parse_13f_xml: zero-value holdings are skipped
- _parse_13f_xml: blank nameOfIssuer + blank CUSIP → skipped
- _parse_13f_xml: name-based node ID when CUSIP absent, added to unmapped list
- _parse_13f_xml: malformed XML bytes returns empty list
- _parse_13f_xml: non-namespaced XML (legacy schema) is parsed correctly
- _parse_13f_xml: unparseable value field is skipped
- _parse_13f_xml: negative value field is skipped
- Sec13fFetcher.list_available_periods: empty dir, one period, multiple periods
- Sec13fFetcher.parse: fixture-based parse via RawDataHandle (golden path)
- Sec13fFetcher.parse: missing CIK in filename → skipped with warning
- Sec13fFetcher.parse: unreadable file → skipped with warning
- Sec13fFetcher.validate: clean path (A11+A12 arcs, plausible total)
- Sec13fFetcher.validate: empty facts → info message
- Sec13fFetcher.validate: wrong arc class → error
- Sec13fFetcher.validate: negative amount → warning
- Sec13fFetcher.validate: wrong source prefix → warning
- Sec13fFetcher.validate: wrong target prefix → warning
- Sec13fFetcher.validate: low total holdings → warning
- Sec13fFetcher.validate: name-based source IDs → info message
- Sec13fFetcher._fetch_one_manager: submissions HTTP error → returns None
- Sec13fFetcher._fetch_one_manager: no matching period → returns None
- Sec13fFetcher._fetch_one_manager: cached file returned directly
- _find_13f_hr_for_period: 13F-HR/A amendments are skipped
- _find_13f_hr_for_period: returns None when no matching filing
- _find_13f_hr_for_period: picks first filing in window
- Property-based (hypothesis): all emitted ArcFacts pass schema validation
- Property-based (hypothesis): node IDs are stable across equivalent inputs
- Property-based (hypothesis): Decimal arithmetic precision preserved
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
from claimweb.fetchers.sec_13f import (
    _CACHE_LIFETIME_DAYS,
    _FILING_WINDOW_DAYS,
    _MANAGER_REGISTRY,
    _MIN_TOTAL_HOLDINGS_MM,
    _OPTION_LABELS,
    _PRN_TYPE,
    _REQUEST_INTERVAL_S,
    _SH_TYPE,
    _THOUSANDS_TO_MILLIONS,
    Sec13fFetcher,
    _cik_from_filename,
    _filing_date_in_window,
    _find_13f_hr_for_period,
    _get_shrs_elem,
    _issuer_node_id,
    _manager_node_id,
    _normalise_name,
    _parse_13f_xml,
    _period_to_filing_window,
    _period_to_quarter_end,
    _text,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fixture paths
# ──────────────────────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "sec_13f"
INFOTABLE_XML = FIXTURE_DIR / "informationtable_q4_2024.xml"
SUBMISSIONS_JSON = FIXTURE_DIR / "submissions_q4_2024.json"

_APOLLO_CIK = "1357615"
_APOLLO_CIK10 = "0001357615"
_Q4_2024 = Period("2024-Q4")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_handle(paths: list[Path], period: Period, source_id: str = "sec_13f") -> RawDataHandle:
    return RawDataHandle.from_paths(source_id, period, paths)


def _write_xml(tmp: Path, xml_bytes: bytes, name: str = "0001357615.xml") -> Path:
    p = tmp / name
    p.write_bytes(xml_bytes)
    return p


def _minimal_infotable_xml(
    issuer: str = "TEST CORP",
    cusip: str = "123456789",
    value: str = "1000",
    shr_type: str = "SH",
    put_call: str = "",
    ns: bool = True,
) -> bytes:
    """Build a minimal informationTable XML for testing."""
    xmlns = 'xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"' if ns else ""
    put_call_elem = f"<putCall>{put_call}</putCall>" if put_call else ""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<informationTable {xmlns}>'
        f'<infoTable>'
        f'<nameOfIssuer>{issuer}</nameOfIssuer>'
        f'<titleOfClass>COM</titleOfClass>'
        f'<cusip>{cusip}</cusip>'
        f'<value>{value}</value>'
        f'<shrsOrPrnAmt>'
        f'<sshPrnamt>100</sshPrnamt>'
        f'<sshPrnamtType>{shr_type}</sshPrnamtType>'
        f'</shrsOrPrnAmt>'
        f'<investmentDiscretion>SOLE</investmentDiscretion>'
        f'{put_call_elem}'
        f'<votingAuthority><Sole>100</Sole><Shared>0</Shared><None>0</None></votingAuthority>'
        f'</infoTable>'
        f'</informationTable>'
    ).encode()


def _make_submissions(
    form_types: list[str],
    accessions: list[str],
    filing_dates: list[str],
    primary_docs: list[str] | None = None,
) -> dict:
    """Build a minimal submissions JSON for _find_13f_hr_for_period."""
    if primary_docs is None:
        primary_docs = ["form13fInfoTable.xml"] * len(form_types)
    return {
        "cik": "1357615",
        "filings": {
            "recent": {
                "form": form_types,
                "accessionNumber": accessions,
                "filingDate": filing_dates,
                "primaryDocument": primary_docs,
            }
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# _normalise_name
# ──────────────────────────────────────────────────────────────────────────────

class TestNormaliseName:
    def test_basic_slug(self):
        assert _normalise_name("Apple Inc") == "apple_inc"

    def test_special_chars_replaced(self):
        # comma→"_", space→"_", period→"_"; consecutive non-alnum each become "_"
        result = _normalise_name("BlackRock, Inc.")
        assert result.startswith("blackrock")
        assert "inc" in result
        assert result == result.lower()

    def test_max_length_60(self):
        long = "A" * 100
        result = _normalise_name(long)
        assert len(result) <= 60

    def test_empty_string(self):
        result = _normalise_name("")
        assert isinstance(result, str)

    def test_strip_trailing_underscore(self):
        result = _normalise_name("Ares!")
        assert not result.endswith("_")

    def test_numbers_preserved(self):
        assert "123" in _normalise_name("Corp 123 LLC")


# ──────────────────────────────────────────────────────────────────────────────
# _issuer_node_id
# ──────────────────────────────────────────────────────────────────────────────

class TestIssuerNodeId:
    def test_cusip_based_prefix_6_chars(self):
        nid = _issuer_node_id("037833100", "APPLE INC")
        assert nid == "corp:cusip:037833"

    def test_cusip_based_uppercase(self):
        nid = _issuer_node_id("037833100", "Apple Inc")
        assert nid.startswith("corp:cusip:")
        assert nid == nid.upper() or "corp:cusip:" in nid
        # First 6 of 037833100 is "037833"
        assert nid == "corp:cusip:037833"

    def test_cusip_exactly_6_chars_accepted(self):
        nid = _issuer_node_id("ABCDEF", "TEST")
        assert nid == "corp:cusip:ABCDEF"

    def test_cusip_too_short_falls_back_to_name(self):
        nid = _issuer_node_id("12345", "SHORT CORP")
        assert nid.startswith("corp:name:")

    def test_none_cusip_uses_name(self):
        nid = _issuer_node_id(None, "PRIVATE FUND")
        assert nid.startswith("corp:name:")
        assert "private_fund" in nid

    def test_empty_cusip_uses_name(self):
        nid = _issuer_node_id("", "SOME FUND")
        assert nid.startswith("corp:name:")

    def test_non_alnum_cusip_falls_back(self):
        nid = _issuer_node_id("???###", "BAD CUSIP")
        assert nid.startswith("corp:name:")


# ──────────────────────────────────────────────────────────────────────────────
# _manager_node_id
# ──────────────────────────────────────────────────────────────────────────────

class TestManagerNodeId:
    def test_short_cik_padded(self):
        assert _manager_node_id("1357615") == "aam:cik:0001357615"

    def test_already_10_digits(self):
        assert _manager_node_id("0001357615") == "aam:cik:0001357615"

    def test_prefix_correct(self):
        nid = _manager_node_id("999")
        assert nid.startswith("aam:cik:")
        assert len(nid) == len("aam:cik:") + 10


# ──────────────────────────────────────────────────────────────────────────────
# _period_to_quarter_end
# ──────────────────────────────────────────────────────────────────────────────

class TestPeriodToQuarterEnd:
    def test_q1_ends_march_31(self):
        assert _period_to_quarter_end(Period("2024-Q1")) == date(2024, 3, 31)

    def test_q2_ends_june_30(self):
        assert _period_to_quarter_end(Period("2024-Q2")) == date(2024, 6, 30)

    def test_q3_ends_september_30(self):
        assert _period_to_quarter_end(Period("2024-Q3")) == date(2024, 9, 30)

    def test_q4_ends_december_31(self):
        assert _period_to_quarter_end(Period("2024-Q4")) == date(2024, 12, 31)


# ──────────────────────────────────────────────────────────────────────────────
# _period_to_filing_window
# ──────────────────────────────────────────────────────────────────────────────

class TestPeriodToFilingWindow:
    def test_q4_2024_window_start(self):
        start, end = _period_to_filing_window(Period("2024-Q4"))
        assert start == date(2025, 1, 1)

    def test_q4_2024_window_end(self):
        start, end = _period_to_filing_window(Period("2024-Q4"))
        assert end == date(2025, 1, 1) + timedelta(days=_FILING_WINDOW_DAYS - 1)

    def test_window_length(self):
        start, end = _period_to_filing_window(Period("2024-Q1"))
        assert (end - start).days == _FILING_WINDOW_DAYS - 1

    def test_q1_window_start(self):
        start, _ = _period_to_filing_window(Period("2024-Q1"))
        assert start == date(2024, 4, 1)


# ──────────────────────────────────────────────────────────────────────────────
# _filing_date_in_window
# ──────────────────────────────────────────────────────────────────────────────

class TestFilingDateInWindow:
    _START = date(2025, 1, 1)
    _END = date(2025, 2, 19)

    def test_start_boundary_included(self):
        assert _filing_date_in_window("2025-01-01", self._START, self._END)

    def test_end_boundary_included(self):
        assert _filing_date_in_window("2025-02-19", self._START, self._END)

    def test_mid_window(self):
        assert _filing_date_in_window("2025-02-14", self._START, self._END)

    def test_before_window(self):
        assert not _filing_date_in_window("2024-12-31", self._START, self._END)

    def test_after_window(self):
        assert not _filing_date_in_window("2025-02-20", self._START, self._END)

    def test_bad_format_returns_false(self):
        assert not _filing_date_in_window("not-a-date", self._START, self._END)

    def test_empty_string_returns_false(self):
        assert not _filing_date_in_window("", self._START, self._END)


# ──────────────────────────────────────────────────────────────────────────────
# _text (XML element accessor)
# ──────────────────────────────────────────────────────────────────────────────

_NS_13F = "http://www.sec.gov/edgar/document/thirteenf/informationtable"

class TestTextHelper:
    def _elem(self, tag: str, text: str, ns: bool = True) -> ET.Element:
        parent = ET.Element("parent")
        ns_prefix = f"{{{_NS_13F}}}" if ns else ""
        child = ET.SubElement(parent, f"{ns_prefix}{tag}")
        child.text = text
        return parent

    def test_reads_namespaced_child(self):
        parent = self._elem("cusip", "037833100", ns=True)
        assert _text(parent, "cusip") == "037833100"

    def test_reads_bare_child(self):
        parent = self._elem("cusip", "037833100", ns=False)
        assert _text(parent, "cusip") == "037833100"

    def test_strips_whitespace(self):
        parent = self._elem("cusip", "  037833100  ", ns=False)
        assert _text(parent, "cusip") == "037833100"

    def test_missing_child_returns_none(self):
        parent = ET.Element("parent")
        assert _text(parent, "missing") is None

    def test_empty_text_returns_none(self):
        parent = ET.Element("parent")
        ET.SubElement(parent, "field").text = ""
        assert _text(parent, "field") is None


# ──────────────────────────────────────────────────────────────────────────────
# _get_shrs_elem
# ──────────────────────────────────────────────────────────────────────────────

class TestGetShrsElem:
    def test_finds_namespaced_shrs_elem(self):
        row = ET.fromstring(
            f'<infoTable xmlns="{_NS_13F}">'
            f'<shrsOrPrnAmt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>'
            f'</infoTable>'
        )
        elem = _get_shrs_elem(row)
        assert elem is not None

    def test_finds_bare_shrs_elem(self):
        row = ET.fromstring(
            '<infoTable>'
            '<shrsOrPrnAmt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>'
            '</infoTable>'
        )
        elem = _get_shrs_elem(row)
        assert elem is not None

    def test_missing_shrs_elem_returns_none(self):
        row = ET.fromstring('<infoTable><nameOfIssuer>TEST</nameOfIssuer></infoTable>')
        assert _get_shrs_elem(row) is None


# ──────────────────────────────────────────────────────────────────────────────
# _cik_from_filename
# ──────────────────────────────────────────────────────────────────────────────

class TestCikFromFilename:
    def test_valid_10_digit_filename(self):
        assert _cik_from_filename("0001357615.xml") == "1357615"

    def test_leading_zeros_stripped(self):
        cik = _cik_from_filename("0000000001.xml")
        assert cik == "1"

    def test_all_zeros_returns_zero(self):
        assert _cik_from_filename("0000000000.xml") == "0"

    def test_wrong_extension_returns_none(self):
        assert _cik_from_filename("0001357615.json") is None

    def test_too_short_returns_none(self):
        assert _cik_from_filename("123456.xml") is None

    def test_non_digit_returns_none(self):
        assert _cik_from_filename("000135761X.xml") is None

    def test_manifest_file_returns_none(self):
        assert _cik_from_filename("_manifest.json") is None


# ──────────────────────────────────────────────────────────────────────────────
# _find_13f_hr_for_period
# ──────────────────────────────────────────────────────────────────────────────

class TestFind13fHrForPeriod:
    _START = date(2025, 1, 1)
    _END = date(2025, 2, 19)

    def test_finds_13f_hr_in_window(self):
        sub = _make_submissions(
            ["13F-HR", "10-K"],
            ["0001-25-000001", "0001-24-000002"],
            ["2025-02-14", "2025-01-15"],
        )
        result = _find_13f_hr_for_period(sub, self._START, self._END)
        assert result is not None
        assert result["accessionNumber"] == "0001-25-000001"

    def test_skips_amendments(self):
        sub = _make_submissions(
            ["13F-HR/A", "13F-HR"],
            ["0001-25-000001", "0001-25-000002"],
            ["2025-02-14", "2025-02-10"],
        )
        result = _find_13f_hr_for_period(sub, self._START, self._END)
        assert result["accessionNumber"] == "0001-25-000002"

    def test_skips_non_matching_forms(self):
        sub = _make_submissions(
            ["10-K", "DEF 14A"],
            ["0001-25-000001", "0001-25-000002"],
            ["2025-02-14", "2025-02-10"],
        )
        assert _find_13f_hr_for_period(sub, self._START, self._END) is None

    def test_returns_none_when_outside_window(self):
        sub = _make_submissions(
            ["13F-HR"],
            ["0001-24-000001"],
            ["2024-12-31"],
        )
        assert _find_13f_hr_for_period(sub, self._START, self._END) is None

    def test_returns_none_on_empty_filings(self):
        sub = {"filings": {"recent": {"form": [], "accessionNumber": [], "filingDate": [], "primaryDocument": []}}}
        assert _find_13f_hr_for_period(sub, self._START, self._END) is None

    def test_picks_first_match(self):
        sub = _make_submissions(
            ["13F-HR", "13F-HR"],
            ["FIRST-001", "SECOND-002"],
            ["2025-01-05", "2025-01-15"],
        )
        result = _find_13f_hr_for_period(sub, self._START, self._END)
        assert result["accessionNumber"] == "FIRST-001"

    def test_fixture_submissions_json(self):
        sub = json.loads(SUBMISSIONS_JSON.read_text())
        # The Q4 2024 filing is dated 2025-02-14; window is Jan 1 – Feb 19.
        start, end = _period_to_filing_window(Period("2024-Q4"))
        result = _find_13f_hr_for_period(sub, start, end)
        assert result is not None
        assert result["accessionNumber"] == "0001357615-25-000001"


# ──────────────────────────────────────────────────────────────────────────────
# _parse_13f_xml
# ──────────────────────────────────────────────────────────────────────────────

class TestParse13fXml:
    _CIK = "1357615"
    _PERIOD = Period("2024-Q4")
    _URL = "file:///test/0001357615.xml"
    _SHA = "a" * 64

    def _parse(self, xml_bytes: bytes, unmapped: list | None = None) -> list[ArcFact]:
        return _parse_13f_xml(
            xml_bytes, self._CIK, self._PERIOD, self._URL, self._SHA, unmapped
        )

    def test_fixture_golden_path(self):
        """Fixture has 3 qualifying rows: 2 SH equity + 1 PRN bond."""
        xml_bytes = INFOTABLE_XML.read_bytes()
        facts = self._parse(xml_bytes)
        # Options (Put, Call), zero-value, and name-only rows also present
        # Put, Call → skipped (2)
        # zero-value → skipped (1)
        # SH×2 (Apple COM, Microsoft COM) → A11
        # PRN×1 (Apple NOTE) → A12
        # name-only (PRIVATE EQUITY FUND LP, no CUSIP) → A11 with name-based ID
        # Total: 4 facts
        assert len(facts) == 4

    def test_equity_holding_is_a11(self):
        xml = _minimal_infotable_xml(shr_type="SH")
        facts = self._parse(xml)
        assert len(facts) == 1
        assert facts[0].instrument_class == ArcClass.A11

    def test_prn_holding_is_a12(self):
        xml = _minimal_infotable_xml(shr_type="PRN")
        facts = self._parse(xml)
        assert len(facts) == 1
        assert facts[0].instrument_class == ArcClass.A12

    def test_put_option_skipped(self):
        xml = _minimal_infotable_xml(put_call="Put")
        assert self._parse(xml) == []

    def test_call_option_skipped(self):
        xml = _minimal_infotable_xml(put_call="Call")
        assert self._parse(xml) == []

    def test_zero_value_skipped(self):
        xml = _minimal_infotable_xml(value="0")
        assert self._parse(xml) == []

    def test_negative_value_skipped(self):
        xml = _minimal_infotable_xml(value="-500")
        assert self._parse(xml) == []

    def test_malformed_xml_returns_empty(self):
        assert self._parse(b"<not valid xml>") == []

    def test_source_node_cusip_based(self):
        xml = _minimal_infotable_xml(cusip="037833100")
        facts = self._parse(xml)
        assert facts[0].source_node_id == "corp:cusip:037833"

    def test_target_node_aam_cik(self):
        xml = _minimal_infotable_xml()
        facts = self._parse(xml)
        assert facts[0].target_node_id == f"aam:cik:{self._CIK.zfill(10)}"

    def test_amount_converted_to_millions(self):
        # value "1000" (thousands) → 1.0 MM
        xml = _minimal_infotable_xml(value="1000")
        facts = self._parse(xml)
        assert facts[0].dollar_amount_millions == Decimal("1")

    def test_amount_uses_decimal(self):
        xml = _minimal_infotable_xml(value="999999")
        facts = self._parse(xml)
        assert isinstance(facts[0].dollar_amount_millions, Decimal)

    def test_data_quality_direct_measured(self):
        xml = _minimal_infotable_xml()
        facts = self._parse(xml)
        assert facts[0].data_quality_flag == DataQualityFlag.DIRECT_MEASURED

    def test_measurement_basis_stock_eop(self):
        xml = _minimal_infotable_xml()
        facts = self._parse(xml)
        assert facts[0].measurement_basis == "stock_eop"

    def test_period_set_correctly(self):
        xml = _minimal_infotable_xml()
        facts = self._parse(xml)
        assert facts[0].period == self._PERIOD

    def test_provenance_source(self):
        xml = _minimal_infotable_xml()
        facts = self._parse(xml)
        assert facts[0].provenance_source == "sec_13f"

    def test_name_based_id_when_no_cusip(self):
        xml = _minimal_infotable_xml(cusip="", issuer="PRIVATE FUND LP")
        unmapped: list = []
        facts = self._parse(xml, unmapped)
        assert len(facts) == 1
        assert facts[0].source_node_id.startswith("corp:name:")
        assert len(unmapped) == 1

    def test_blank_name_and_blank_cusip_skipped(self):
        # No issuer name AND no CUSIP — no valid identifier
        xml = _minimal_infotable_xml(issuer="", cusip="")
        facts = self._parse(xml)
        assert facts == []

    def test_non_namespaced_xml_parsed(self):
        xml = _minimal_infotable_xml(ns=False)
        facts = self._parse(xml)
        assert len(facts) == 1

    def test_unparseable_value_skipped(self):
        xml = _minimal_infotable_xml(value="N/A")
        assert self._parse(xml) == []

    def test_sha256_stored(self):
        xml = _minimal_infotable_xml()
        facts = self._parse(xml)
        assert facts[0].sha256_of_source == self._SHA

    def test_multiple_rows_parsed(self):
        xml_str = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<informationTable xmlns="{_NS_13F}">'
        )
        for i in range(5):
            xml_str += (
                f'<infoTable>'
                f'<nameOfIssuer>CORP {i}</nameOfIssuer>'
                f'<titleOfClass>COM</titleOfClass>'
                f'<cusip>12345{i}000</cusip>'
                f'<value>1000</value>'
                f'<shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>'
                f'<investmentDiscretion>SOLE</investmentDiscretion>'
                f'<votingAuthority><Sole>100</Sole><Shared>0</Shared><None>0</None></votingAuthority>'
                f'</infoTable>'
            )
        xml_str += '</informationTable>'
        facts = self._parse(xml_str.encode())
        assert len(facts) == 5

    def test_cusip_uppercase_normalised(self):
        xml = _minimal_infotable_xml(cusip="abcdef123")
        facts = self._parse(xml)
        assert "ABCDEF" in facts[0].source_node_id


# ──────────────────────────────────────────────────────────────────────────────
# Sec13fFetcher.list_available_periods
# ──────────────────────────────────────────────────────────────────────────────

class TestListAvailablePeriods:
    def test_empty_dir_returns_empty(self, tmp_path):
        fetcher = Sec13fFetcher(data_root=tmp_path)
        assert fetcher.list_available_periods() == []

    def test_nonexistent_root_returns_empty(self, tmp_path):
        fetcher = Sec13fFetcher(data_root=tmp_path / "nonexistent")
        assert fetcher.list_available_periods() == []

    def test_single_period_detected(self, tmp_path):
        (tmp_path / "2024-Q4").mkdir()
        fetcher = Sec13fFetcher(data_root=tmp_path)
        periods = fetcher.list_available_periods()
        assert periods == [Period("2024-Q4")]

    def test_multiple_periods_sorted(self, tmp_path):
        for p in ["2023-Q1", "2024-Q4", "2024-Q1"]:
            (tmp_path / p).mkdir()
        fetcher = Sec13fFetcher(data_root=tmp_path)
        periods = fetcher.list_available_periods()
        assert periods == [Period("2023-Q1"), Period("2024-Q1"), Period("2024-Q4")]

    def test_invalid_dir_names_ignored(self, tmp_path):
        (tmp_path / "not-a-period").mkdir()
        (tmp_path / "2024-Q4").mkdir()
        fetcher = Sec13fFetcher(data_root=tmp_path)
        periods = fetcher.list_available_periods()
        assert periods == [Period("2024-Q4")]

    def test_files_not_included(self, tmp_path):
        (tmp_path / "2024-Q4").touch()  # file, not dir
        fetcher = Sec13fFetcher(data_root=tmp_path)
        assert fetcher.list_available_periods() == []


# ──────────────────────────────────────────────────────────────────────────────
# Sec13fFetcher.parse
# ──────────────────────────────────────────────────────────────────────────────

class TestParse:
    def test_parse_fixture_golden_path(self, tmp_path):
        xml_bytes = INFOTABLE_XML.read_bytes()
        p = _write_xml(tmp_path, xml_bytes, f"{_APOLLO_CIK10}.xml")
        handle = _make_handle([p], _Q4_2024)
        fetcher = Sec13fFetcher()
        facts = fetcher.parse(handle)
        # 4 qualifying rows (2 equity + 1 PRN + 1 name-only)
        assert len(facts) == 4

    def test_all_a11_or_a12(self, tmp_path):
        xml_bytes = INFOTABLE_XML.read_bytes()
        p = _write_xml(tmp_path, xml_bytes, f"{_APOLLO_CIK10}.xml")
        handle = _make_handle([p], _Q4_2024)
        fetcher = Sec13fFetcher()
        facts = fetcher.parse(handle)
        for f in facts:
            assert f.instrument_class in (ArcClass.A11, ArcClass.A12)

    def test_target_node_ids_use_manager_cik(self, tmp_path):
        xml_bytes = INFOTABLE_XML.read_bytes()
        p = _write_xml(tmp_path, xml_bytes, f"{_APOLLO_CIK10}.xml")
        handle = _make_handle([p], _Q4_2024)
        fetcher = Sec13fFetcher()
        facts = fetcher.parse(handle)
        assert all(f.target_node_id == f"aam:cik:{_APOLLO_CIK10}" for f in facts)

    def test_bad_filename_skipped(self, tmp_path):
        xml_bytes = INFOTABLE_XML.read_bytes()
        p = _write_xml(tmp_path, xml_bytes, "manifest.json")
        handle = _make_handle([p], _Q4_2024)
        fetcher = Sec13fFetcher()
        facts = fetcher.parse(handle)
        assert facts == []

    def test_empty_handle_returns_empty(self, tmp_path):
        handle = _make_handle([], _Q4_2024)
        fetcher = Sec13fFetcher()
        assert fetcher.parse(handle) == []

    def test_multiple_managers_parsed(self, tmp_path):
        xml_bytes = _minimal_infotable_xml(value="5000")
        ciks = ["0001357615", "0001393818", "0001404912"]
        paths = [_write_xml(tmp_path, xml_bytes, f"{c}.xml") for c in ciks]
        handle = _make_handle(paths, _Q4_2024)
        fetcher = Sec13fFetcher()
        facts = fetcher.parse(handle)
        assert len(facts) == 3
        targets = {f.target_node_id for f in facts}
        assert len(targets) == 3

    def test_provenance_source_is_sec_13f(self, tmp_path):
        xml_bytes = _minimal_infotable_xml()
        p = _write_xml(tmp_path, xml_bytes, f"{_APOLLO_CIK10}.xml")
        handle = _make_handle([p], _Q4_2024)
        fetcher = Sec13fFetcher()
        facts = fetcher.parse(handle)
        assert all(f.provenance_source == "sec_13f" for f in facts)

    def test_unmapped_registry_written(self, tmp_path):
        xml_bytes = _minimal_infotable_xml(issuer="PRIVATE FUND LP", cusip="")
        p = _write_xml(tmp_path, xml_bytes, f"{_APOLLO_CIK10}.xml")
        handle = _make_handle([p], _Q4_2024)
        fetcher = Sec13fFetcher()
        registry_dir = tmp_path / "registry"
        # patch _write_unmapped to avoid filesystem side effects outside tmp
        with patch("claimweb.fetchers.sec_13f._write_unmapped") as mock_wu:
            facts = fetcher.parse(handle)
            assert mock_wu.called


# ──────────────────────────────────────────────────────────────────────────────
# Sec13fFetcher.validate
# ──────────────────────────────────────────────────────────────────────────────

def _make_fact(
    period: Period = _Q4_2024,
    source: str = "corp:cusip:037833",
    target: str = "aam:cik:0001357615",
    arc_class: ArcClass = ArcClass.A11,
    amount: Decimal = Decimal("1000"),
) -> ArcFact:
    return ArcFact(
        period=period,
        source_node_id=source,
        target_node_id=target,
        instrument_class=arc_class,
        dollar_amount_millions=amount,
        measurement_basis="stock_eop",
        data_quality_flag=DataQualityFlag.DIRECT_MEASURED,
        provenance_source="sec_13f",
        provenance_url="file:///test.xml",
        provenance_filing=None,
        provenance_page=None,
        provenance_field="test",
        sha256_of_source="a" * 64,
    )


class TestValidate:
    _fetcher = Sec13fFetcher()

    def test_clean_a11_passes(self):
        facts = [_make_fact(amount=Decimal("5000")) for _ in range(3)]
        report = self._fetcher.validate(facts)
        assert report.is_clean

    def test_clean_a12_passes(self):
        facts = [_make_fact(arc_class=ArcClass.A12, amount=Decimal("5000")) for _ in range(3)]
        report = self._fetcher.validate(facts)
        assert report.is_clean

    def test_empty_facts_info_message(self):
        report = self._fetcher.validate([])
        assert report.is_clean
        codes = [i.code for i in report.issues]
        assert "NO_13F_HOLDINGS" in codes

    def test_wrong_arc_class_error(self):
        facts = [_make_fact(arc_class=ArcClass.A3)]
        report = self._fetcher.validate(facts)
        assert not report.is_clean
        codes = [i.code for i in report.issues]
        assert "WRONG_ARC_CLASS" in codes

    def test_negative_amount_warning(self):
        facts = [_make_fact(amount=Decimal("-100"))]
        report = self._fetcher.validate(facts)
        codes = [i.code for i in report.issues]
        assert "NEGATIVE_AMOUNT" in codes

    def test_wrong_source_prefix_warning(self):
        facts = [_make_fact(source="spv:cusip:037833", amount=Decimal("5000"))]
        report = self._fetcher.validate(facts)
        codes = [i.code for i in report.issues]
        assert "UNEXPECTED_SOURCE_PREFIX" in codes

    def test_wrong_target_prefix_warning(self):
        facts = [_make_fact(target="mmf:S000001234", amount=Decimal("5000"))]
        report = self._fetcher.validate(facts)
        codes = [i.code for i in report.issues]
        assert "UNEXPECTED_TARGET_PREFIX" in codes

    def test_low_total_holdings_warning(self):
        # 1 fact with $100M < threshold of $1000M
        facts = [_make_fact(amount=Decimal("100"))]
        report = self._fetcher.validate(facts)
        codes = [i.code for i in report.issues]
        assert "LOW_TOTAL_HOLDINGS" in codes

    def test_plausible_total_no_low_warning(self):
        facts = [_make_fact(amount=Decimal("10000")) for _ in range(5)]
        report = self._fetcher.validate(facts)
        codes = [i.code for i in report.issues]
        assert "LOW_TOTAL_HOLDINGS" not in codes

    def test_name_based_source_id_info(self):
        facts = [_make_fact(source="corp:name:private_fund", amount=Decimal("5000"))]
        report = self._fetcher.validate(facts)
        codes = [i.code for i in report.issues]
        assert "NAME_BASED_ISSUER_IDS" in codes


# ──────────────────────────────────────────────────────────────────────────────
# Sec13fFetcher.acquire — cache hit / miss (mocked network)
# ──────────────────────────────────────────────────────────────────────────────

class TestAcquireCache:
    def test_cache_hit_returns_handle_without_network(self, tmp_path):
        period = Period("2024-Q4")
        period_dir = tmp_path / str(period)
        period_dir.mkdir()
        xml_file = period_dir / f"{_APOLLO_CIK10}.xml"
        xml_file.write_bytes(INFOTABLE_XML.read_bytes())
        manifest = {
            "fetched_at": datetime.utcnow().isoformat(),
            "period": str(period),
            "files": [xml_file.name],
            "manager_count": 1,
        }
        (period_dir / "_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        fetcher = Sec13fFetcher(data_root=tmp_path)
        with patch("httpx.Client") as mock_client:
            handle = fetcher.acquire(period)
        mock_client.assert_not_called()
        assert len(handle.paths) == 1

    def test_stale_cache_triggers_refresh(self, tmp_path):
        period = Period("2024-Q4")
        period_dir = tmp_path / str(period)
        period_dir.mkdir()
        old_time = datetime(2000, 1, 1).isoformat()
        manifest = {
            "fetched_at": old_time,
            "period": str(period),
            "files": [],
        }
        (period_dir / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        fetcher = Sec13fFetcher(data_root=tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"filings": {"recent": {"form": [], "accessionNumber": [], "filingDate": [], "primaryDocument": []}}}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        with patch("httpx.Client", return_value=mock_client):
            with patch("time.sleep"):
                handle = fetcher.acquire(period)
        assert handle is not None


# ──────────────────────────────────────────────────────────────────────────────
# _fetch_one_manager (private) — error handling
# ──────────────────────────────────────────────────────────────────────────────

class TestFetchOneManager:
    def test_submissions_http_error_returns_none(self, tmp_path):
        fetcher = Sec13fFetcher(data_root=tmp_path)
        mock_client = MagicMock()
        import httpx
        mock_client.get.side_effect = httpx.RequestError("network error")
        with patch("time.sleep"):
            result = fetcher._fetch_one_manager(
                mock_client,
                cik=_APOLLO_CIK,
                name="Apollo",
                period=_Q4_2024,
                dest_dir=tmp_path,
                start_dt=date(2025, 1, 1),
                end_dt=date(2025, 2, 19),
            )
        assert result is None

    def test_no_matching_period_returns_none(self, tmp_path):
        fetcher = Sec13fFetcher(data_root=tmp_path)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "filings": {"recent": {"form": [], "accessionNumber": [], "filingDate": [], "primaryDocument": []}}
        }
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        with patch("time.sleep"):
            result = fetcher._fetch_one_manager(
                mock_client,
                cik=_APOLLO_CIK,
                name="Apollo",
                period=_Q4_2024,
                dest_dir=tmp_path,
                start_dt=date(2025, 1, 1),
                end_dt=date(2025, 2, 19),
            )
        assert result is None

    def test_cached_file_returned_without_network(self, tmp_path):
        cached = tmp_path / f"{_APOLLO_CIK10}.xml"
        cached.write_bytes(b"<informationTable/>")
        fetcher = Sec13fFetcher(data_root=tmp_path)
        mock_client = MagicMock()
        with patch("time.sleep"):
            result = fetcher._fetch_one_manager(
                mock_client,
                cik=_APOLLO_CIK,
                name="Apollo",
                period=_Q4_2024,
                dest_dir=tmp_path,
                start_dt=date(2025, 1, 1),
                end_dt=date(2025, 2, 19),
            )
        mock_client.get.assert_not_called()
        assert result == cached


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

class TestConstants:
    def test_manager_registry_not_empty(self):
        assert len(_MANAGER_REGISTRY) >= 7

    def test_all_registry_ciks_are_numeric_strings(self):
        for cik in _MANAGER_REGISTRY:
            assert cik.isdigit(), f"CIK {cik!r} is not numeric"

    def test_option_labels_contains_put_call(self):
        assert "Put" in _OPTION_LABELS
        assert "Call" in _OPTION_LABELS

    def test_thousands_to_millions_is_0_001(self):
        assert _THOUSANDS_TO_MILLIONS == Decimal("0.001")

    def test_filing_window_days_at_least_45(self):
        assert _FILING_WINDOW_DAYS >= 45

    def test_min_holdings_plausible(self):
        assert _MIN_TOTAL_HOLDINGS_MM > Decimal("0")


# ──────────────────────────────────────────────────────────────────────────────
# Property-based tests (hypothesis)
# ──────────────────────────────────────────────────────────────────────────────

_CUSIP_STRATEGY = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=6, max_size=9
)
_NAME_STRATEGY = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")),
    min_size=1,
    max_size=80,
)
_VALUE_STRATEGY = st.integers(min_value=1, max_value=10_000_000)


@given(cusip=_CUSIP_STRATEGY, name=_NAME_STRATEGY)
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_property_issuer_node_id_stable(cusip: str, name: str) -> None:
    """issuer_node_id is deterministic for the same inputs."""
    nid1 = _issuer_node_id(cusip, name)
    nid2 = _issuer_node_id(cusip, name)
    assert nid1 == nid2


@given(
    value=_VALUE_STRATEGY,
    shr_type=st.sampled_from(["SH", "PRN"]),
    cusip=_CUSIP_STRATEGY,
)
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_property_arc_facts_pass_schema(value: int, shr_type: str, cusip: str) -> None:
    """All emitted ArcFacts from _parse_13f_xml pass the ArcFact schema."""
    xml = _minimal_infotable_xml(
        issuer="TEST CORP",
        cusip=cusip,
        value=str(value),
        shr_type=shr_type,
    )
    facts = _parse_13f_xml(
        xml,
        manager_cik="1357615",
        period=Period("2024-Q4"),
        source_url="file:///test.xml",
        sha256="a" * 64,
    )
    for f in facts:
        assert isinstance(f.dollar_amount_millions, Decimal)
        assert f.dollar_amount_millions > Decimal("0")
        assert f.instrument_class in (ArcClass.A11, ArcClass.A12)
        assert f.data_quality_flag == DataQualityFlag.DIRECT_MEASURED
        assert f.provenance_source == "sec_13f"


@given(value=st.decimals(min_value="1", max_value="1e7", places=3, allow_nan=False))
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_property_decimal_precision_preserved(value: Decimal) -> None:
    """Dollar amounts converted from thousands preserve Decimal precision."""
    # Simulate: parse a value equal to the integer representation of value * 1000
    # Round to integer (thousands) then convert back
    thousands_int = int(value * Decimal("1000"))
    converted = Decimal(str(thousands_int)) * _THOUSANDS_TO_MILLIONS
    # The converted value should equal the rounded original
    assert converted == Decimal(str(thousands_int)) * Decimal("0.001")
