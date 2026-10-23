"""The EMF images of a drawing as SVG.

Visio stores many icons and pasted pictures as EMF, the vector metafile of Windows, and vsd2xhtml passes
them on as ``data:image/emf`` images. WeasyPrint cannot read EMF, so they were left out. emf2svg-conv turns
each into SVG, which stays vector in the PDF. An EMF it cannot convert stays as it is, and WeasyPrint leaves
it out as before.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree as ET

from .errors import ConversionError

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
EMF_PREFIX = "data:image/emf;base64,"
LOGGER = logging.getLogger("weasyvsdx")

# Takes the path of an EMF file, returns its SVG; raises ConversionError
Converter = Callable[[Path], bytes]


def replace_emf(page: ET.Element, convert: Converter, folder: Path) -> int:
    """Turn each EMF image of the page into SVG, and return how many. The same EMF converts once."""
    done: dict[str, str | None] = {}
    count = 0
    for image in page.iter(f"{{{SVG_NS}}}image"):
        href = image.get(XLINK_HREF) or image.get("href") or ""
        if not href.startswith(EMF_PREFIX):
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
    """The EMF of the data URL as an SVG data URL, or None when it does not convert."""
    try:
        path.write_bytes(base64.b64decode(href[len(EMF_PREFIX) :], validate=True))
        svg = convert(path)
    except (binascii.Error, ConversionError) as e:
        LOGGER.warning("An EMF image of a Visio drawing stays out: %s", e)
        return None
    finally:
        path.unlink(missing_ok=True)
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
