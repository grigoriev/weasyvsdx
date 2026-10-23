"""Paths of a drawing that start without a moveto."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from weasyvsdx.paths import SVG_NS, start_with_moveto


def test_a_path_that_starts_with_a_lineto_starts_there() -> None:
    page = ET.fromstring(f'<svg xmlns="{SVG_NS}"><path d=" L361.13,544.43 L361.13,539.00 M358.86,542.85 Z"/><path d="l1,2 3,4"/><path d="M1,1 L2,2"/><path/></svg>')
    assert start_with_moveto(page) == 2
    assert [path.get("d") for path in page] == ["M361.13,544.43 L361.13,539.00 M358.86,542.85 Z", "m1,2 3,4", "M1,1 L2,2", None]
