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
CLIPBOARD_FORMAT_MARKER = 0xFFFFFFFF
# The formats of a metafile: a WMF (CF_METAFILEPICT) or an EMF (CF_ENHMETAFILE)
METAFILE_FORMATS = frozenset((3, 14))

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


def ole_preview(ole: bytes) -> bytes | None:
    """The EMF an OLE object shows as its picture, or None when it shows none."""
    # Bytes shorter than a sector would be taken as a file name: always a stream
    with olefile.OleFileIO(io.BytesIO(ole)) as storage:
        streams = sorted("/".join(entry) for entry in storage.listdir() if entry[0].startswith(PRESENTATION))
        for name in streams:
            stream = storage.openstream(name).read()
            # The ANSI clipboard format, the size of the target device with its own 4 bytes, the device, then
            # aspect, lindex, advf, reserved, width, height and the size of the data
            marker, kind, device = struct.unpack_from("<III", stream)
            if marker != CLIPBOARD_FORMAT_MARKER or kind not in METAFILE_FORMATS:
                continue
            start = 8 + device + 24
            (size,) = struct.unpack_from("<I", stream, start)
            data = stream[start + 4 : start + 4 + size]
            # Office stores an EMF presentation as a WMF that holds the EMF in its comments, as the corpus shows;
            # an EMF as MS-OLEDS describes it passes as it is
            emf = data if data[40:44] == EMF_SIGNATURE else embedded_emf(data)
            if emf is not None:
                return emf
    return None


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
        path.write_bytes(_emf(base64.b64decode(href[len(prefix) :], validate=True), kind))
        svg = convert(path)
    # olefile raises OSError on a broken compound file, and ValueError on a sector size too large to print;
    # ValueError covers the binascii.Error of a broken base64 too
    except (struct.error, OSError, ValueError, ConversionError) as e:
        LOGGER.warning("An image of a Visio drawing (%s) stays out: %s", kind, e)
        return None
    finally:
        path.unlink(missing_ok=True)
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
