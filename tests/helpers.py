"""Shared helpers: install weasyvsdx once, render a drawing through WeasyPrint, read the PDF back."""

from __future__ import annotations

import base64
import struct
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import weasyprint

import weasyvsdx
from weasyvsdx.convert import find_tools

CONVERTER = weasyvsdx.install()
TOOLS = find_tools(CONVERTER)

VISIO = Path(__file__).resolve().parents[1] / "corpus" / "visio"
VSDX_TYPE = "application/vnd.ms-visio.drawing"


def drawing(source: str) -> bytes:
    """A drawing of the corpus, by its path below corpus/visio."""
    return (VISIO / source).read_bytes()


def data_url(data: bytes, media_type: str = VSDX_TYPE) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode()}"


def page_html(body: str) -> str:
    return f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>@page{{size:1200px 900px;margin:0}} body{{margin:0}} img{{display:block;width:1100px}}</style></head><body>{body}</body></html>"


def render(body: str, **options: Any) -> bytes:
    """The PDF of a page with body."""
    pdf: bytes = weasyprint.HTML(string=page_html(body), **options).write_pdf()
    return pdf


def text_of(pdf: bytes) -> str:
    """The text PDFium extracts from the first page."""
    document = pdfium.PdfDocument(pdf)
    page = document[0]
    textpage = page.get_textpage()
    try:
        text: str = textpage.get_text_range()
        return text
    finally:
        # Children first: on PyPy a page finalized after its document fails an assertion
        for item in (textpage, page, document):
            item.close()


def objects_of(pdf: bytes) -> int:
    """How many objects the first page draws: paths, text and images."""
    document = pdfium.PdfDocument(pdf)
    page = document[0]
    try:
        return sum(1 for _ in page.get_objects(max_depth=8))
    finally:
        page.close()
        document.close()


def emf_rectangle(left: int = 10, top: int = 10, right: int = 90, bottom: int = 50) -> bytes:
    """An EMF of one rectangle: a header, EMR_RECTANGLE and EMR_EOF, as the EMF specification lays them out."""
    rectangle = struct.pack("<II4i", 43, 24, left, top, right, bottom)
    eof = struct.pack("<5I", 14, 20, 0, 16, 20)
    size = 88 + len(rectangle) + len(eof)
    # Type, size, bounds, frame in 0.01 mm, signature " EMF", version, bytes, records, handles, reserved,
    # description length and offset, palette entries, device size in pixels and in millimeters
    header = struct.pack("<II4i4iIIIIHHIIIiiii", 1, 88, 0, 0, 100, 60, 0, 0, 2646, 1588, 0x464D4520, 0x10000, size, 3, 1, 0, 0, 0, 0, 1920, 1080, 508, 286)
    return header + rectangle + eof


def wmf_holding(emf: bytes, chunk: int = 64, placeable: bool = False) -> bytes:
    """A WMF that holds emf in META_ESCAPE comment records of chunk bytes each, as Office writes it."""
    records = []
    pieces = [emf[start : start + chunk] for start in range(0, len(emf), chunk)]
    remaining = len(emf)
    for piece in pieces:
        remaining -= len(piece)
        # "WMFC", type 1, version, checksum, flags, record count, this chunk, the bytes to come, the whole EMF
        comment = struct.pack("<4sIIHIIIII", b"WMFC", 1, 0x10000, 0, 0, len(pieces), len(piece), remaining, len(emf)) + piece
        comment += b"\0" * (len(comment) % 2)
        parameters = struct.pack("<HH", 0x000F, len(comment)) + comment
        records.append(struct.pack("<IH", 3 + len(parameters) // 2, 0x0626) + parameters)
    records.append(struct.pack("<IH", 3, 0x0000))
    body = b"".join(records)
    # META_HEADER: type, header size in words, version, file size in words, objects, largest record, members
    header = struct.pack("<HHHIHIH", 1, 9, 0x0300, (18 + len(body)) // 2, 0, 0, 0)
    prefix = struct.pack("<IH4hHI", 0x9AC6CDD7, 0, 0, 0, 100, 60, 1440, 0) + b"\0\0" if placeable else b""
    return prefix + header + body
