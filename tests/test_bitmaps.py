"""The BMP images of a drawing, with the offset of their pixels counted right."""

from __future__ import annotations

import base64
import io
import struct
from xml.etree import ElementTree as ET

from PIL import Image

from weasyvsdx.bitmaps import SVG_NS, XLINK_HREF, fix_bitmaps, pixel_offset_fixed

XLINK_NS = "http://www.w3.org/1999/xlink"
RED, GREEN, BLUE = (255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)
WHITE = (255, 255, 255, 255)


def bitfields_bmp(row: list[tuple[int, int, int, int]], offset: int = 54, compression: int = 3) -> bytes:
    """A BMP of one row of 32 bit pixels with BI_BITFIELDS masks, as Visio writes it: its offset leaves the masks out."""
    pixels = b"".join(bytes((blue, green, red, alpha)) for red, green, blue, alpha in row)
    masks = struct.pack("<III", 0x00FF0000, 0x0000FF00, 0x000000FF)
    if compression == 6:
        masks += struct.pack("<I", 0xFF000000)
    info = struct.pack("<IiiHHIIiiII", 40, len(row), 1, 1, 32, compression, len(pixels), 0, 0, 0, 0)
    size = 14 + len(info) + len(masks) + len(pixels)
    return b"BM" + struct.pack("<IHHI", size, 0, 0, offset) + info + masks + pixels


def read(bmp: bytes) -> list[tuple[int, ...]]:
    with Image.open(io.BytesIO(bmp)) as image:
        rgba = image.convert("RGBA")
        return [tuple(rgba.getpixel((x, 0))) for x in range(rgba.width)]  # type: ignore[arg-type]


def test_the_pixels_start_after_the_masks() -> None:
    row = [WHITE, RED, GREEN, BLUE]
    bmp = bitfields_bmp(row)
    # As Visio writes it, the masks come out as pixels and the row moves right
    assert read(bmp) != row
    fixed = pixel_offset_fixed(bmp)
    assert struct.unpack_from("<I", fixed, 10) == (66,)
    assert read(fixed) == row


def test_four_masks_of_alpha_bitfields() -> None:
    bmp = bitfields_bmp([WHITE, RED], offset=54, compression=6)
    assert struct.unpack_from("<I", pixel_offset_fixed(bmp), 10) == (70,)


def test_other_bitmaps_stay() -> None:
    right = bitfields_bmp([WHITE, RED], offset=66)
    plain = bytearray(bitfields_bmp([WHITE, RED]))
    struct.pack_into("<I", plain, 30, 0)  # BI_RGB, which has no masks
    v5 = bytearray(bitfields_bmp([WHITE, RED]))
    struct.pack_into("<I", v5, 14, 124)  # a BITMAPV5HEADER holds its masks itself
    for bmp in (right, bytes(plain), bytes(v5), b"BM", b"not a bitmap" * 10):
        assert pixel_offset_fixed(bmp) == bmp
    # A file without room for its rows after the masks keeps its offset
    cut = bitfields_bmp([WHITE, RED])[:-4]
    assert pixel_offset_fixed(cut) == cut


def test_each_bmp_image_of_a_page() -> None:
    bmp = "data:image/bmp;base64," + base64.b64encode(bitfields_bmp([WHITE, RED])).decode()
    right = "data:image/bmp;base64," + base64.b64encode(bitfields_bmp([WHITE, RED], offset=66)).decode()
    hrefs = (bmp, right, "data:image/bmp;base64,not base64!", "data:image/png;base64,AAAA")
    images = "".join(f'<image xlink:href="{href}"/>' for href in hrefs) + f'<image href="{bmp}"/>'
    page = ET.fromstring(f'<svg xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}">{images}</svg>')
    assert fix_bitmaps(page) == 2
    assert page[0].get(XLINK_HREF) == right
    assert [element.get(XLINK_HREF) for element in page[1:4]] == list(hrefs[1:])
    # An SVG 2 href changes in place
    assert page[4].get("href") == right
    assert page[4].get(XLINK_HREF) is None
