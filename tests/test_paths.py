"""Paths of a drawing that start without a moveto."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from weasyvsdx.paths import SVG_NS, moved_to_start, shortened, start_with_moveto


def test_each_path_without_a_moveto_gets_one() -> None:
    page = ET.fromstring(f'<svg xmlns="{SVG_NS}"><path d=" L361.13,544.43 L361.13,539.00 Z"/><path d="M1,1 L2,2"/><path/></svg>')
    assert start_with_moveto(page) == 1
    assert [path.get("d") for path in page] == ["M361.13,544.43 L361.13,539.00 Z", "M1,1 L2,2", None]


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        # A lineto: its point is the start
        ("L361.13,544.43 L361.13,539.00 M358.86,542.85 Z", "M361.13,544.43 L361.13,539.00 M358.86,542.85 Z"),
        ("L213.8043,163.6080 Z", "M213.8043,163.6080 Z"),
        ("l1,2 3,4", "m1,2 3,4"),
        # An arc of an unknown start goes, its end is the start: no arc the long way round the page
        ("A953.3186,366.0715 0.0000 1,0 1131.3662,578.7887 A71.2201,27.3483 0.0000 0,0 1102.9427,553.5856 Z", "M1131.3662,578.7887 A71.2201,27.3483 0.0000 0,0 1102.9427,553.5856 Z"),
        # More segments of the same command keep their letter
        ("C1,1 2,2 3,3 4,4 5,5 6,6", "M3,3 C 4,4 5,5 6,6"),
        ("Q1,1 2,2 3,3 4,4", "M2,2 Q 3,3 4,4"),
        # A path that starts right, or that cannot be read, stays
        ("M1,1 L2,2", "M1,1 L2,2"),
        ("", ""),
        ("5 5", "5 5"),
        ("A1,1 0 0", "A1,1 0 0"),
        ("C1,1 2,2 Z", "C1,1 2,2 Z"),
        ("H5", "H5"),
        ("a1,1 0 0,1 5,5", "a1,1 0 0,1 5,5"),
    ],
)
def test_the_first_segment_without_a_start(data: str, expected: str) -> None:
    assert moved_to_start(data) == expected


@pytest.mark.parametrize(
    ("data", "end", "expected"),
    [
        # Back along the last lineto, by the length
        ("M0,0 L10,0", "end", "M0,0 L8.0000,0.0000"),
        ("\nM0.0000,0.0000\nL0.0000,10.0000", "start", "\nM0.0000,2.0000\nL0.0000,10.0000"),
        # A curve moves its control point next to the end, or to the start, with it
        ("M0,0 C0,5 10,5 10,0", "end", "M0,0 C0,5 10.0000,7.0000 10.0000,2.0000"),
        ("M0,0 C0,5 10,5 10,0", "start", "M0.0000,2.0000 C0.0000,7.0000 10,5 10,0"),
        # Too short, closed, an arc, or no line at all: no change
        ("M0,0 L1,0", "end", "M0,0 L1,0"),
        ("M0,0 L10,0 Z", "end", "M0,0 L10,0 Z"),
        ("M0,0 A5,5 0 0,1 10,0", "end", "M0,0 A5,5 0 0,1 10,0"),
        ("M0,0", "end", "M0,0"),
        ("", "end", ""),
    ],
)
def test_a_line_ends_at_the_base_of_its_arrowhead(data: str, end: str, expected: str) -> None:
    assert shortened(data, 2.0, end) == expected


def test_no_length_no_change() -> None:
    assert shortened("M0,0 L10,0", 0.0, "end") == "M0,0 L10,0"
