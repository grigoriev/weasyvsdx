"""The BMP images of a drawing, with the offset of their pixels counted right.

Visio stores some icons as BMP files with color masks (BI_BITFIELDS): three masks of 4 bytes follow the
40 bytes of the BITMAPINFOHEADER. Their file header gives the offset of the pixels as if the masks were
not there. Visio reads the pixels after the masks; Pillow, and so WeasyPrint, reads them at the offset.
It takes the masks for the first three pixels, and the picture moves right by three pixels and wraps
around. vsd2xhtml passes the file on as it is, as a ``data:image/bmp`` image.
"""

from __future__ import annotations

import base64
import binascii
import struct
from xml.etree import ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
BMP_PREFIX = "data:image/bmp;base64,"

FILE_HEADER = 14  # BITMAPFILEHEADER: "BM", the size of the file, 4 reserved bytes, the offset of the pixels
INFO_HEADER = 40  # BITMAPINFOHEADER; the larger headers hold the masks themselves
# The bytes of the masks after a BITMAPINFOHEADER: BI_BITFIELDS has three, BI_ALPHABITFIELDS four
MASKS = {3: 12, 6: 16}


def pixel_offset_fixed(bmp: bytes) -> bytes:
    """The BMP with the offset of its pixels past its masks, where it points at the masks; any other BMP as it is."""
    if len(bmp) < FILE_HEADER + INFO_HEADER or bmp[:2] != b"BM":
        return bmp
    (offset,) = struct.unpack_from("<I", bmp, 10)
    header_size, width, height, _, bit_count, compression = struct.unpack_from("<IiiHHI", bmp, FILE_HEADER)
    (colors,) = struct.unpack_from("<I", bmp, FILE_HEADER + 32)
    masks = MASKS.get(compression, 0)
    if header_size != INFO_HEADER or masks == 0:
        return bmp
    palette = 4 * (colors or (1 << bit_count if bit_count <= 8 else 0))
    pixels = FILE_HEADER + INFO_HEADER + masks + palette
    stride = (abs(width) * bit_count + 31) // 32 * 4
    # Only a file which holds all its rows after the masks: one whose offset is right in another way stays
    if offset != pixels - masks or len(bmp) < pixels + stride * abs(height):
        return bmp
    fixed = bytearray(bmp)
    struct.pack_into("<I", fixed, 10, pixels)
    return bytes(fixed)


def fix_bitmaps(page: ET.Element) -> int:
    """Count the offset of the pixels of each BMP image of the page past its masks; return how many changed."""
    count = 0
    for image in page.iter(f"{{{SVG_NS}}}image"):
        attribute = XLINK_HREF if image.get(XLINK_HREF) is not None else "href"
        href = image.get(attribute) or ""
        if not href.startswith(BMP_PREFIX):
            continue
        try:
            bmp = base64.b64decode(href[len(BMP_PREFIX) :], validate=True)
        except binascii.Error:
            continue
        fixed = pixel_offset_fixed(bmp)
        if fixed != bmp:
            image.set(attribute, BMP_PREFIX + base64.b64encode(fixed).decode())
            count += 1
    return count
