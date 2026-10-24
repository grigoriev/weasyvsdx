"""Shared helpers: install weasyvsdx once, render a drawing through WeasyPrint, read the PDF back."""

from __future__ import annotations

import base64
import io
import struct
import zipfile
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
NS = "xmlns='http://schemas.microsoft.com/office/visio/2012/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'"
PACKAGE = "xmlns='http://schemas.openxmlformats.org/package/2006/relationships'"


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


def presentation(data: bytes, clipboard_format: int = 14, marker: int = 0xFFFFFFFF) -> bytes:
    """An MS-OLEDS OLEPresentationStream of the data, with no target device."""
    # Marker, format, target device size, aspect, lindex, advf, reserved, width, height, data size
    return struct.pack("<IIIIiIIIII", marker, clipboard_format, 4, 1, -1, 0, 0, 100, 60, len(data)) + data


def ole_holding(streams: dict[str, bytes]) -> bytes:
    """A compound file of version 3 with the streams under its root, at most three, each in plain sectors."""
    sector, end, free, nostream = 512, 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFF
    # Streams under 4096 bytes would go to the mini stream: pad them past it
    bodies = [data.ljust(4096, b"\0") for data in streams.values()]
    fat = [0xFFFFFFFD, end]
    entries = [_directory_entry("Root Entry", 5, child=1 if streams else nostream, start=end, size=0)]
    for index, (name, body) in enumerate(zip(streams, bodies, strict=True)):
        start, count = len(fat), -(-len(body) // sector)
        fat += [*range(start + 1, start + count), end]
        following = index + 2 if index + 1 < len(bodies) else nostream
        entries.append(_directory_entry(name, 2, right=following, start=start, size=len(body)))
    entries += [b"\0" * 64 + struct.pack("<HBBIII", 0, 0, 0, nostream, nostream, nostream) + b"\0" * 48] * (4 - len(entries))
    # Header: signature, CLSID, versions, byte order, sector shifts, counts, the directory start, mini stream
    # cutoff, no mini FAT, no DIFAT, then the DIFAT array with the one FAT sector
    header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16
    header += struct.pack("<HHHHH6sIIIIIIIII", 0x3E, 3, 0xFFFE, 9, 6, b"", 0, 1, 1, 0, 4096, end, 0, end, 0)
    header += struct.pack("<109I", 0, *[free] * 108)
    fat_sector = struct.pack(f"<{len(fat)}I", *fat) + struct.pack("<I", free) * (128 - len(fat))
    return header + fat_sector + b"".join(entries) + b"".join(body.ljust(-(-len(body) // sector) * sector, b"\0") for body in bodies)


def _directory_entry(name: str, kind: int, *, right: int = 0xFFFFFFFF, child: int = 0xFFFFFFFF, start: int, size: int) -> bytes:
    """A directory entry of 128 bytes: the name, its type, black, its siblings and child, its sectors."""
    encoded = (name + "\0").encode("utf-16-le")
    return encoded.ljust(64, b"\0") + struct.pack("<HBBIII16sIQQIQ", len(encoded), kind, 1, 0xFFFFFFFF, right, child, b"", 0, 0, 0, start, size)


def stretch_dibits(rows: list[bytes], height: int, *, bit_count: int = 8, compression: int = 0, width: int = 4) -> bytes:
    """An EMR_STRETCHDIBITS record of a bottom-up bitmap of the rows, drawn at y 100 to the destination height."""
    bits = b"".join(rows)
    # BITMAPINFOHEADER: size, width, height, planes, bit count, compression, image size, resolution, colors
    info = struct.pack("<IiiHHIIiiII", 40, width, len(rows), 1, bit_count, compression, len(bits), 0, 0, 0, 0)
    size = 80 + len(info) + len(bits)
    # Type, size, bounds, x and y, source x, y, width and height, header and bits, usage, operation, width, height
    record = struct.pack("<II4iiiiiiiIIIIIIii", 81, size, 0, 0, 0, 0, 2, 100, 0, 0, width, len(rows), 80, len(info), 80 + len(info), len(bits), 0, 0xCC0020, 50, height)
    return record + info + bits


def vsdx(page: str | None, master: str | None = None, *, foreground: bool = True, copies: int = 0, document: str | None = None, backed: bool = False, layers: str = "") -> bytes:
    """A VSDX of a background page with a shape of ID 1 and the page, on that background if backed, with one master of ID 2, the content of document.xml and the page sheet if given; a page of None has no shapes."""
    # The background page is the background of itself: a loop that a reader must stop
    back = " BackPage='4'" if backed else ""
    pages = f"<Pages {NS}><Page ID='4' Background='1' BackPage='4'><Rel r:id='rId1'/></Page>" + (f"<Page ID='0'{back}>{layers}<Rel r:id='rId2'/></Page>" if foreground else "") + "</Pages>"
    parts = {
        "visio/pages/pages.xml": pages,
        "visio/pages/_rels/pages.xml.rels": f"<Relationships {PACKAGE}><Relationship Id='rId1' Target='page1.xml'/><Relationship Id='rId2' Target='page2.xml'/></Relationships>",
        "visio/pages/page1.xml": f"<PageContents {NS}><Shapes><Shape ID='1'><Text>Background</Text></Shape></Shapes></PageContents>",
        "visio/pages/page2.xml": f"<PageContents {NS}>" + (f"<Shapes>{page}</Shapes>" if page is not None else "") + "</PageContents>",
    }
    if master is not None:
        parts["visio/masters/masters.xml"] = f"<Masters {NS}><Master ID='2'><Rel r:id='rId1'/></Master><Master ID='3'/>" + "<Master ID='4'><Rel r:id='rId1'/></Master>" * copies + "</Masters>"
        parts["visio/masters/_rels/masters.xml.rels"] = f"<Relationships {PACKAGE}><Relationship Id='rId1' Target='master1.xml'/></Relationships>"
        parts["visio/masters/master1.xml"] = f"<MasterContents {NS}><Shapes>{master}</Shapes></MasterContents>"
    if document is not None:
        parts["visio/document.xml"] = f"<VisioDocument {NS}>{document}</VisioDocument>"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return buffer.getvalue()
