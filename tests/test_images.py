"""The EMF images of a drawing as SVG."""

from __future__ import annotations

import base64
import logging
import struct
from pathlib import Path
from xml.etree import ElementTree as ET

import helpers
import pytest

from weasyvsdx.errors import ConversionError
from weasyvsdx.images import SVG_NS, XLINK_HREF, embedded_emf, ole_preview, presentation_emf, replace_emf, upright_bitmaps

XLINK_NS = "http://www.w3.org/1999/xlink"


def page(*hrefs: str) -> ET.Element:
    images = "".join(f'<image xlink:href="{href}"/>' for href in hrefs)
    return ET.fromstring(f'<svg xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}">{images}</svg>')


def test_each_emf_becomes_svg_and_the_same_converts_once(tmp_path: Path) -> None:
    emf = "data:image/emf;base64," + base64.b64encode(helpers.emf_rectangle()).decode()
    other = "data:image/emf;base64," + base64.b64encode(helpers.emf_rectangle(right=50)).decode()
    seen: list[bytes] = []

    def convert(path: Path) -> bytes:
        seen.append(path.read_bytes())
        return b"<svg/>"

    image = page(emf, "data:image/png;base64,AAAA", emf, other)
    assert replace_emf(image, convert, tmp_path) == 3
    assert len(seen) == 2
    hrefs = [element.get(XLINK_HREF) for element in image]
    assert hrefs[0] == hrefs[2] == "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode()
    assert hrefs[1] == "data:image/png;base64,AAAA"
    # The EMF files go once converted
    assert list(tmp_path.iterdir()) == []


def test_an_emf_that_does_not_convert_stays(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    def fail(path: Path) -> bytes:
        raise ConversionError("emf2svg-conv failed with exit code 1")

    image = page("data:image/emf;base64,AAAA", "data:image/emf;base64,not base64!")
    with caplog.at_level(logging.WARNING, logger="weasyvsdx"):
        assert replace_emf(image, fail, tmp_path) == 0
    assert [element.get(XLINK_HREF) for element in image] == ["data:image/emf;base64,AAAA", "data:image/emf;base64,not base64!"]
    assert len(caplog.records) == 2


def test_an_svg_2_href_converts_too(tmp_path: Path) -> None:
    image = ET.fromstring(f'<svg xmlns="{SVG_NS}"><image href="data:image/emf;base64,AAAA"/></svg>')
    assert replace_emf(image, lambda path: b"<svg/>", tmp_path) == 1
    assert image[0].get("href") is None
    assert (image[0].get(XLINK_HREF) or "").startswith("data:image/svg+xml;base64,")


@pytest.mark.parametrize("placeable", [False, True])
def test_the_emf_a_wmf_holds_in_its_comments(placeable: bool) -> None:
    emf = helpers.emf_rectangle()
    assert embedded_emf(helpers.wmf_holding(emf, chunk=50, placeable=placeable)) == emf


def test_a_wmf_without_an_emf() -> None:
    plain = helpers.wmf_holding(b"")
    assert embedded_emf(plain) is None
    # A comment that is no EMF, and a record that claims fewer words than a record has
    assert embedded_emf(helpers.wmf_holding(b"x" * 60)) is None
    assert embedded_emf(plain[:18] + b"\0" * 6) is None
    assert embedded_emf(b"") is None


def test_other_escapes_and_a_cut_escape_carry_no_emf() -> None:
    emf = helpers.emf_rectangle()
    whole = helpers.wmf_holding(emf, chunk=len(emf))
    escape = whole[18:-6]
    # Another escape function than MFCOMMENT, and a comment of another kind than "WMFC"
    other_escape = escape[:6] + struct.pack("<H", 0x0001) + escape[8:]
    other_comment = escape[:10] + b"XXXX" + escape[14:]
    assert embedded_emf(whole[:18] + other_escape + other_comment + whole[-6:]) is None
    # An escape cut before its comment ends the file
    assert embedded_emf(whole[:18] + escape[:30]) is None


def test_the_emf_inside_a_wmf_becomes_svg(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    wmf = "data:image/wmf;base64," + base64.b64encode(helpers.wmf_holding(helpers.emf_rectangle())).decode()
    empty = "data:image/wmf;base64," + base64.b64encode(helpers.wmf_holding(b"")).decode()
    seen: list[bytes] = []

    def convert(path: Path) -> bytes:
        seen.append(path.read_bytes())
        return b"<svg/>"

    image = page(wmf, empty)
    with caplog.at_level(logging.WARNING, logger="weasyvsdx"):
        assert replace_emf(image, convert, tmp_path) == 1
    assert seen == [helpers.emf_rectangle()]
    assert (image[0].get(XLINK_HREF) or "").startswith("data:image/svg+xml;base64,")
    assert image[1].get(XLINK_HREF) == empty
    assert "An image of a Visio drawing (WMF) stays out: the WMF holds no EMF" in caplog.text


def test_the_picture_an_ole_object_shows() -> None:
    emf = helpers.emf_rectangle()
    shown = helpers.presentation(helpers.wmf_holding(emf))
    assert ole_preview(helpers.ole_holding({"\x01CompObj": b"x", "\x02OlePres000": shown})) == emf
    # A presentation of another clipboard format, a bitmap, goes for the next one
    bitmap = helpers.presentation(b"BM", clipboard_format=2)
    assert ole_preview(helpers.ole_holding({"\x02OlePres000": bitmap, "\x02OlePres001": shown})) == emf
    # A presentation whose target device runs past its end goes for the next one
    broken = shown[:8] + struct.pack("<I", 0xFFFF0000) + shown[12:]
    assert ole_preview(helpers.ole_holding({"\x02OlePres000": broken, "\x02OlePres001": shown})) == emf
    # An EMF as it is, and a WMF of CF_METAFILEPICT that holds one
    assert ole_preview(helpers.ole_holding({"\x02OlePres000": helpers.presentation(emf)})) == emf
    assert ole_preview(helpers.ole_holding({"\x02OlePres000": helpers.presentation(helpers.wmf_holding(emf), clipboard_format=3)})) == emf


def test_a_presentation_cut_short() -> None:
    shown = helpers.presentation(helpers.wmf_holding(helpers.emf_rectangle()))
    # In its header, and before the size of its data
    assert presentation_emf(shown[:8]) is None
    assert presentation_emf(shown[:30]) is None


def test_both_markers_of_a_clipboard_format() -> None:
    emf = helpers.emf_rectangle()
    assert presentation_emf(helpers.presentation(emf, marker=0xFFFFFFFE)) == emf
    # A clipboard format by name, a length in place of the marker, carries no metafile
    assert presentation_emf(helpers.presentation(emf, marker=8)) is None


def test_an_ole_object_that_shows_no_emf() -> None:
    assert ole_preview(helpers.ole_holding({"\x02OlePres000": helpers.presentation(helpers.wmf_holding(b""))})) is None
    assert ole_preview(helpers.ole_holding({"\x01Ole10Native": b"x"})) is None
    assert ole_preview(helpers.ole_holding({})) is None


def test_the_picture_of_an_ole_object_becomes_svg(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    emf = helpers.emf_rectangle()
    ole = helpers.ole_holding({"\x02OlePres000": helpers.presentation(helpers.wmf_holding(emf))})
    empty = helpers.ole_holding({"\x01Ole10Native": b"x"})
    hrefs = ["data:object/ole;base64," + base64.b64encode(data).decode() for data in (ole, empty, b"not an OLE object")]
    seen: list[bytes] = []

    def convert(path: Path) -> bytes:
        seen.append(path.read_bytes())
        return b"<svg/>"

    image = page(*hrefs)
    with caplog.at_level(logging.WARNING, logger="weasyvsdx"):
        assert replace_emf(image, convert, tmp_path) == 1
    assert seen == [emf]
    assert [element.get(XLINK_HREF) for element in image][1:] == hrefs[1:]
    assert "An image of a Visio drawing (OLE object) stays out: the OLE object holds no EMF" in caplog.text
    assert len(caplog.records) == 2


def test_an_ole_object_of_a_huge_sector_size_stays(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    ole = bytearray(helpers.ole_holding({"\x02OlePres000": helpers.presentation(helpers.wmf_holding(helpers.emf_rectangle()))}))
    # The sector shift of the header: olefile computes 2 ** 65535 and fails to print it as ValueError
    ole[30:32] = b"\xff\xff"
    href = "data:object/ole;base64," + base64.b64encode(bytes(ole)).decode()
    image = page(href)
    with caplog.at_level(logging.WARNING, logger="weasyvsdx"):
        assert replace_emf(image, lambda path: b"<svg/>", tmp_path) == 0
    assert image[0].get(XLINK_HREF) == href
    assert "An image of a Visio drawing (OLE object) stays out" in caplog.text


def test_a_bitmap_drawn_to_a_negative_height_turns_upright() -> None:
    rows = [b"\x01\x01\x01\x01", b"\x02\x02\x02\x02", b"\x03\x03\x03\x03"]
    record = helpers.stretch_dibits(rows, -30)
    upright = upright_bitmaps(helpers.emf_rectangle() + record)[len(helpers.emf_rectangle()) :]
    # The destination starts where the flipped one ended and runs down, over the rows in reverse
    assert struct.unpack_from("<i", upright, 28) == (70,)
    assert struct.unpack_from("<i", upright, 76) == (30,)
    assert upright[120:] == b"".join(reversed(rows))
    # The whole bitmap as source stays the whole bitmap
    assert struct.unpack_from("<i", upright, 36) == (0,)


def test_a_band_of_rows_as_source_stays_that_band() -> None:
    rows = [b"\x01" * 4, b"\x02" * 4, b"\x03" * 4]
    record = bytearray(helpers.stretch_dibits(rows, -30))
    # The first row only: after the reversal it is the last
    struct.pack_into("<ii", record, 40, 4, 1)
    struct.pack_into("<i", record, 36, 0)
    upright = upright_bitmaps(bytes(record))
    assert struct.unpack_from("<i", upright, 36) == (2,)


def test_other_bitmaps_stay() -> None:
    rows = [b"\x01" * 4, b"\x02" * 4]
    for record in (
        helpers.stretch_dibits(rows, 30),
        helpers.stretch_dibits(rows, -30, compression=1),
        # More rows than the bits hold
        helpers.stretch_dibits(rows, -30, width=40),
    ):
        assert upright_bitmaps(record) == record
    # No bits per row, which any count of rows would fit: the height of 2**31 - 1 rows stays unread
    empty = bytearray(helpers.stretch_dibits(rows, -30, bit_count=0))
    struct.pack_into("<i", empty, 88, 2**31 - 1)
    assert upright_bitmaps(bytes(empty)) == bytes(empty)
    # A record cut short, or of a size past the end, ends the walk
    whole = helpers.stretch_dibits(rows, -30)
    assert upright_bitmaps(whole[:60]) == whole[:60]
    assert upright_bitmaps(struct.pack("<II", 81, 4)) == struct.pack("<II", 81, 4)
