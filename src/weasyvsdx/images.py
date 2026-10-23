"""The EMF and WMF images of a drawing as SVG.

Visio stores many icons and pasted pictures as EMF, the vector metafile of Windows, and vsd2xhtml passes
them on as ``data:image/emf`` images. WeasyPrint cannot read EMF, so they were left out. emf2svg-conv turns
each into SVG, which stays vector in the PDF. An EMF it cannot convert stays as it is, and WeasyPrint leaves
it out as before.

A WMF, the older metafile, that Office wrote holds an EMF of the same picture in its comment records
(MS-WMF META_ESCAPE_ENHANCED_METAFILE): that EMF converts as any other. A WMF without one stays out.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import struct
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree as ET

from .errors import ConversionError

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
EMF_PREFIX = "data:image/emf;base64,"
WMF_PREFIX = "data:image/wmf;base64,"
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


def replace_emf(page: ET.Element, convert: Converter, folder: Path) -> int:
    """Turn each EMF image of the page, and the EMF inside each WMF, into SVG; return how many. Each converts once."""
    done: dict[str, str | None] = {}
    count = 0
    for image in page.iter(f"{{{SVG_NS}}}image"):
        href = image.get(XLINK_HREF) or image.get("href") or ""
        if not href.startswith((EMF_PREFIX, WMF_PREFIX)):
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


def _svg_url(href: str, convert: Converter, path: Path) -> str | None:
    """The EMF of the data URL, or the EMF inside its WMF, as an SVG data URL; None when it does not convert."""
    wmf = href.startswith(WMF_PREFIX)
    try:
        data = base64.b64decode(href[len(WMF_PREFIX if wmf else EMF_PREFIX) :], validate=True)
        emf = embedded_emf(data) if wmf else data
        if emf is None:
            raise ConversionError("the WMF holds no EMF")
        path.write_bytes(emf)
        svg = convert(path)
    except (binascii.Error, struct.error, ConversionError) as e:
        LOGGER.warning("A%s image of a Visio drawing stays out: %s", " WMF" if wmf else "n EMF", e)
        return None
    finally:
        path.unlink(missing_ok=True)
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
