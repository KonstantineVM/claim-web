#!/usr/bin/env python3
"""Generate the FHLB Combined Financial Report test fixture PDF.

Run once to create tests/fixtures/fhlb_combined/2024-Q4-combined-financial-report.pdf.
The fixture is a minimal valid PDF whose text content mimics the key tables
in the actual FHLB Office of Finance Combined Financial Report.

Usage:
    python tests/fixtures/fhlb_combined/generate_fixture.py
"""
from __future__ import annotations

import hashlib
import pathlib


def _build_fixture_pdf() -> bytes:
    """Build a minimal, valid, pdfplumber-readable PDF.

    The content mirrors the structure of the FHLB Office of Finance Combined
    Financial Report: a header section identifying the period, an
    "ADVANCES OUTSTANDING BY MEMBER TYPE" table in billions of dollars, and
    a stub for a top-member table.  Units, labels, and layout match the real
    report closely enough to exercise the fetcher's regex patterns.
    """
    page_content = (
        "BT\n"
        "/F1 11 Tf\n"
        "50 770 Td (COMBINED FINANCIAL REPORT) Tj\n"
        "0 -18 Td (Federal Home Loan Banks) Tj\n"
        "0 -16 Td (For the Quarter Ended December 31, 2024) Tj\n"
        "0 -28 Td (ADVANCES OUTSTANDING BY MEMBER TYPE) Tj\n"
        "0 -14 Td (All dollar amounts in billions unless noted) Tj\n"
        "0 -22 Td (                                     Dec 31, 2024   Sep 30, 2024) Tj\n"
        "0 -18 Td (Depository Institutions:) Tj\n"
        "0 -16 Td (  Commercial Banks                     406.8          398.3) Tj\n"
        "0 -16 Td (  Savings Institutions                  62.4           64.1) Tj\n"
        "0 -16 Td (Insurance Companies                     89.7           87.4) Tj\n"
        "0 -16 Td (Credit Unions                           34.5           33.2) Tj\n"
        "0 -16 Td (CDFIs                                    2.1            2.0) Tj\n"
        "0 -16 Td (Other                                    0.2            0.2) Tj\n"
        "0 -18 Td (Total Advances                         595.7          585.2) Tj\n"
        "0 -32 Td (TOP TEN ADVANCE USERS - INSURANCE COMPANY MEMBERS) Tj\n"
        "0 -14 Td (All dollar amounts in millions) Tj\n"
        "0 -22 Td (Member Name                             State   Balance) Tj\n"
        "0 -18 Td (MetLife Insurance Company of Connecticut    CT    8234) Tj\n"
        "0 -16 Td (Lincoln National Life Insurance Company      PA    6789) Tj\n"
        "0 -16 Td (Athene Annuity and Life Insurance Company    IA    5432) Tj\n"
        "0 -16 Td (Transamerica Life Insurance Company          IA    4321) Tj\n"
        "0 -16 Td (Principal Life Insurance Company             IA    3876) Tj\n"
        "ET\n"
    )
    content_bytes = page_content.encode("latin-1")

    obj1 = b"<</Type /Catalog /Pages 2 0 R>>"
    obj2 = b"<</Type /Pages /Kids [3 0 R] /Count 1>>"
    obj3 = (
        b"<</Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 612 792] "
        b"/Contents 4 0 R "
        b"/Resources <</Font <</F1 5 0 R>>>>>>"
    )
    obj4 = (
        f"<</Length {len(content_bytes)}>>\nstream\n".encode("latin-1")
        + content_bytes
        + b"\nendstream"
    )
    obj5 = b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>"

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    parts: list[bytes] = [header]
    offsets: list[int] = []
    pos = len(header)

    for n, data in enumerate([obj1, obj2, obj3, obj4, obj5], start=1):
        offsets.append(pos)
        chunk = f"{n} 0 obj\n".encode() + data + b"\nendobj\n"
        parts.append(chunk)
        pos += len(chunk)

    xref_pos = pos
    xref = "xref\n0 6\n"
    xref += "0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n"

    trailer = (
        f"trailer\n<</Size 6 /Root 1 0 R>>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    )
    parts.append(xref.encode("latin-1"))
    parts.append(trailer.encode("latin-1"))
    return b"".join(parts)


def main() -> None:
    out = pathlib.Path(__file__).parent / "2024-Q4-combined-financial-report.pdf"
    pdf_bytes = _build_fixture_pdf()
    out.write_bytes(pdf_bytes)
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    print(f"Wrote {len(pdf_bytes)} bytes → {out}")
    print(f"SHA-256: {sha}")


if __name__ == "__main__":
    main()
