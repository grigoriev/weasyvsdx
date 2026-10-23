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
