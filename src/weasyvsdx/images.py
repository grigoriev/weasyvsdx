"""The EMF and WMF images of a drawing as SVG.

Visio stores many icons and pasted pictures as EMF, the vector metafile of Windows, and vsd2xhtml passes
them on as ``data:image/emf`` images. WeasyPrint cannot read EMF, so they were left out. emf2svg-conv turns
each into SVG, which stays vector in the PDF. An EMF it cannot convert stays as it is, and WeasyPrint leaves
it out as before.

A WMF, the older metafile, that Office wrote holds an EMF of the same picture in its comment records
(MS-WMF META_ESCAPE_ENHANCED_METAFILE): that EMF converts as any other. A WMF without one stays out.

An OLE object, a picture or a drawing pasted from another program, comes as ``data:object/ole``. Its
presentation stream (MS-OLEDS OLEPresentationStream) holds the picture Office shows for it, a WMF with the
same embedded EMF, which converts as well.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import struct
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree as ET

import olefile

from .errors import ConversionError

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
EMF_PREFIX = "data:image/emf;base64,"
WMF_PREFIX = "data:image/wmf;base64,"
OLE_PREFIX = "data:object/ole;base64,"
LOGGER = logging.getLogger("weasyvsdx")

# The WMF records of MS-WMF that carry an EMF: META_ESCAPE with the escape MFCOMMENT, the comment "WMFC"
WMF_PLACEABLE = 0x9AC6CDD7
WMF_HEADER = 18  # bytes of the META_HEADER
WMF_PLACEABLE_HEADER = 22
META_EOF = 0x0000
META_ESCAPE = 0x0626
MFCOMMENT = 0x000F
WMFC = b"WMFC"
ENHANCED_METAFILE = 1
EMF_SIGNATURE = b" EMF"

# The presentation streams of MS-OLEDS: a clipboard format, the target device, then the fields up to the data
PRESENTATION = "\x02OlePres"
# Either marker means a standard clipboard format follows (MS-OLEDS ClipboardFormatOrAnsiString)
CLIPBOARD_FORMAT_MARKERS = frozenset((0xFFFFFFFF, 0xFFFFFFFE))
# The formats of a metafile: a WMF (CF_METAFILEPICT) or an EMF (CF_ENHMETAFILE)
METAFILE_FORMATS = frozenset((3, 14))

# EMR_STRETCHDIBITS: its destination y at 28, the offsets and sizes of its header and bits at 48, its
# destination height at 76; in the BITMAPINFOHEADER the width, height, bit count and compression
EMR_STRETCHDIBITS = 81
UNCOMPRESSED = frozenset((0, 3))  # BI_RGB, BI_BITFIELDS

# Takes the path of an EMF file, returns its SVG; raises ConversionError
Converter = Callable[[Path], bytes]


def embedded_emf(wmf: bytes) -> bytes | None:
    """The EMF a WMF holds in its comment records, or None when it holds none."""
    offset = WMF_PLACEABLE_HEADER if wmf[:4] == struct.pack("<I", WMF_PLACEABLE) else 0
    offset += WMF_HEADER
    chunks = []
    while offset + 6 <= len(wmf):
        # A record: its size in 16-bit words, its function, then its parameters
        words, function = struct.unpack_from("<IH", wmf, offset)
        if function == META_EOF or words < 3:
            break
        # The escape: MFCOMMENT, the byte count, then the comment: "WMFC", type, version, checksum, flags,
        # record count, the size of this chunk, the bytes to come, the size of the whole EMF, the chunk
        if function == META_ESCAPE and offset + 44 <= len(wmf):
            (escape,) = struct.unpack_from("<H", wmf, offset + 6)
            comment = offset + 10
            identifier, kind = struct.unpack_from("<4sI", wmf, comment)
            if escape == MFCOMMENT and identifier == WMFC and kind == ENHANCED_METAFILE:
                (size,) = struct.unpack_from("<I", wmf, comment + 22)
                chunks.append(wmf[comment + 34 : comment + 34 + size])
        offset += words * 2
    emf = b"".join(chunks)
    # An EMF starts with its header record, the signature " EMF" at byte 40
    return emf if emf[40:44] == EMF_SIGNATURE else None


def upright_bitmaps(emf: bytes) -> bytes:
    """The EMF with each bitmap drawn to a negative height turned into one drawn upside down to a positive height.

    Office draws the bitmap of a picture with a negative destination height, which flips it, onto a bottom-up
    bitmap. emf2svg-conv mirrors such a bitmap left to right instead. Reversing its rows and the sign of the
    height draws the same picture, which emf2svg-conv converts right.
    """
    data = bytearray(emf)
    offset = 0
    while offset + 8 <= len(data):
        kind, size = struct.unpack_from("<II", data, offset)
        if size < 8 or offset + size > len(data):
            break
        if kind == EMR_STRETCHDIBITS and size >= 80:
            _flip_rows(data, offset, size)
        offset += size
    return bytes(data)


def _flip_rows(data: bytearray, offset: int, size: int) -> None:
    """Draw the bitmap of one EMR_STRETCHDIBITS record at offset upright to a positive height, if it is flipped."""
    (y,) = struct.unpack_from("<i", data, offset + 28)
    header, header_size, bits, bits_size = struct.unpack_from("<4I", data, offset + 48)
    (height,) = struct.unpack_from("<i", data, offset + 76)
    if height >= 0 or header_size < 20 or header + 20 > size:
        return
    width, rows, _, bit_count, compression = struct.unpack_from("<iiHHI", data, offset + header + 4)
    stride = (abs(width) * bit_count + 31) // 32 * 4
    rows = abs(rows)
    if compression not in UNCOMPRESSED or stride * rows > bits_size or bits + stride * rows > size:
        return
    start = offset + bits
    lines = [bytes(data[start + row * stride : start + (row + 1) * stride]) for row in range(rows)]
    data[start : start + stride * rows] = b"".join(reversed(lines))
    struct.pack_into("<i", data, offset + 28, y + height)
    struct.pack_into("<i", data, offset + 76, -height)


def ole_preview(ole: bytes) -> bytes | None:
    """The EMF an OLE object shows as its picture, or None when it shows none."""
    # Bytes shorter than a sector would be taken as a file name: always a stream
    with olefile.OleFileIO(io.BytesIO(ole)) as storage:
        streams = sorted("/".join(entry) for entry in storage.listdir() if entry[0].startswith(PRESENTATION))
        for name in streams:
            emf = presentation_emf(storage.openstream(name).read())
            if emf is not None:
                return emf
    return None


def presentation_emf(stream: bytes) -> bytes | None:
    """The EMF of a presentation stream, or None when it holds no metafile or is cut short."""
    # The ANSI clipboard format, the size of the target device with its own 4 bytes, the device, then
    # aspect, lindex, advf, reserved, width, height and the size of the data
    if len(stream) < 12:
        return None
    marker, kind, device = struct.unpack_from("<III", stream)
    start = 8 + device + 24
    if marker not in CLIPBOARD_FORMAT_MARKERS or kind not in METAFILE_FORMATS or start + 4 > len(stream):
        return None
    (size,) = struct.unpack_from("<I", stream, start)
    data = stream[start + 4 : start + 4 + size]
    # Office stores an EMF presentation as a WMF that holds the EMF in its comments, as the corpus shows;
    # an EMF as MS-OLEDS describes it passes as it is
    return data if data[40:44] == EMF_SIGNATURE else embedded_emf(data)


def replace_emf(page: ET.Element, convert: Converter, folder: Path) -> int:
    """Turn each EMF image of the page, and the EMF inside each WMF and OLE object, into SVG; return how many. Each converts once."""
    done: dict[str, str | None] = {}
    count = 0
    for image in page.iter(f"{{{SVG_NS}}}image"):
        href = image.get(XLINK_HREF) or image.get("href") or ""
        if not href.startswith((EMF_PREFIX, WMF_PREFIX, OLE_PREFIX)):
            continue
        key = hashlib.sha256(href.encode()).hexdigest()
        if key not in done:
            done[key] = _svg_url(href, convert, folder / f"{key[:16]}.emf")
        url = done[key]
        if url is not None:
            image.attrib.pop("href", None)
            image.set(XLINK_HREF, url)
            count += 1
    return count


def _emf(data: bytes, kind: str) -> bytes:
    """The EMF of an image of the kind, the EMF inside a WMF or the picture of an OLE object; raises ConversionError."""
    if kind == "EMF":
        return data
    emf = embedded_emf(data) if kind == "WMF" else ole_preview(data)
    if emf is None:
        raise ConversionError(f"the {kind} holds no EMF")
    return emf


def _svg_url(href: str, convert: Converter, path: Path) -> str | None:
    """The EMF of the data URL, or the EMF inside its WMF or OLE object, as an SVG data URL; None when it does not convert."""
    prefix = next(prefix for prefix in (EMF_PREFIX, WMF_PREFIX, OLE_PREFIX) if href.startswith(prefix))
    kind = {EMF_PREFIX: "EMF", WMF_PREFIX: "WMF", OLE_PREFIX: "OLE object"}[prefix]
    try:
        path.write_bytes(upright_bitmaps(_emf(base64.b64decode(href[len(prefix) :], validate=True), kind)))
        svg = convert(path)
    # olefile raises OSError on a broken compound file, and ValueError on a sector size too large to print;
    # ValueError covers the binascii.Error of a broken base64 too
    except (struct.error, OSError, ValueError, ConversionError) as e:
        LOGGER.warning("An image of a Visio drawing (%s) stays out: %s", kind, e)
        return None
    finally:
        path.unlink(missing_ok=True)
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
