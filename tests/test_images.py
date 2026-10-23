"""The EMF images of a drawing as SVG."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from xml.etree import ElementTree as ET

import helpers
import pytest

from weasyvsdx.errors import ConversionError
from weasyvsdx.images import SVG_NS, XLINK_HREF, replace_emf

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
