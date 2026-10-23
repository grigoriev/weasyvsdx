"""Hatched fills."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from weasyvsdx import hatch
from weasyvsdx.hatch import MAX_LINES, draw_styles, fill_hatches, hatch_lines
from weasyvsdx.hidden import SVG_NS, remove_hidden
from weasyvsdx.raw import first_page

PATH = "drawPath (svg:d: ((librevenge:path-action: M, svg:x: 0in, svg:y: 0in)))"
HATCH = "setStyle (draw:color: #c5e0b3, draw:distance: 0.1000in, draw:fill: hatch, draw:fill-color: #ffffff, draw:fill-hatch-solid: true, draw:rotation: 45, draw:style: single, svg:fill-rule: evenodd)"
SOLID = "setStyle (draw:fill: solid, draw:fill-color: #ff0000)"
SQUARE = "M0,0 L72,0 L72,72 L0,72 Z"


def calls(*lines: str) -> list[tuple[str, str]]:
    return first_page("startPage()\n" + "\n".join(lines) + "\nendPage\n")


def page(*data: str) -> ET.Element:
    paths = "".join(f'<path d="{d}" style="stroke-width: 0.25; fill-rule: evenodd; "/>' for d in data)
    return ET.fromstring(f'<svg xmlns="{SVG_NS}"><g>{paths}</g></svg>')


def test_each_path_has_the_style_set_before_its_call() -> None:
    styles = draw_styles(calls(PATH, SOLID, PATH, "drawPath (draw:id: 7)", HATCH, PATH))
    assert [style.get("draw:fill") for style in styles] == [None, "solid", "hatch"]


def test_a_hatched_path_gets_its_fill_and_its_lines_clipped_to_it() -> None:
    svg = page(SQUARE, SQUARE)
    assert fill_hatches(svg, calls(SOLID, PATH, HATCH, PATH))
    solid, hatched, lines = svg[1]
    assert "fill: url" not in (solid.get("style") or "")
    assert "fill: #ffffff" not in (solid.get("style") or "")
    assert (hatched.get("style") or "").endswith("fill: #ffffff;")
    assert lines.get("stroke") == "#c5e0b3"
    clip = svg[0][0]
    assert lines.get("clip-path") == f"url(#{clip.get('id')})"
    assert clip[0].get("d") == SQUARE
    assert clip[0].get("clip-rule") == "evenodd"
    # Counterclockwise in ODF, about the center of the shape
    [turned] = list(lines)
    assert turned.get("transform") == "translate(36 36) rotate(-45)"
    # Lines 7.2 points apart, past the half diagonal of 101.8 points each way
    offsets = [float(line.get("y1") or 0) for line in turned]
    assert len(offsets) == 17
    assert offsets[9] - offsets[8] == 7.2


def test_the_lines_of_the_hatch_drawn_add_no_path() -> None:
    # The hidden shapes pair the paths of the page with the calls after the hatches are drawn
    svg = page(SQUARE, SQUARE)
    assert fill_hatches(svg, calls(HATCH, PATH, PATH))
    assert remove_hidden(svg, calls(PATH, PATH))


def test_a_hidden_hatched_shape_gets_no_lines() -> None:
    hidden = "drawPath (draw:display: none, svg:d: ((librevenge:path-action: M, svg:x: 0in, svg:y: 0in)))"
    svg = page(SQUARE)
    assert fill_hatches(svg, calls(HATCH, hidden))
    assert remove_hidden(svg, calls(hidden))
    assert list(svg[0]) == []


def test_a_hatch_without_solid_fill_leaves_the_shape_open() -> None:
    svg = page(SQUARE)
    assert fill_hatches(svg, calls(HATCH.replace("draw:fill-hatch-solid: true", "draw:fill-hatch-solid: false"), PATH))
    assert (svg[1][0].get("style") or "").endswith("fill: none;")


def test_crossed_hatches_and_defaults() -> None:
    double = hatch_lines(SQUARE, {"draw:style": "double"})
    triple = hatch_lines(SQUARE, {"draw:style": "triple", "draw:rotation": "30"})
    odd = hatch_lines(SQUARE, {"draw:style": "dotted"})
    assert double is not None
    assert triple is not None
    assert odd is not None
    assert [turned.get("transform") for turned in double] == ["translate(36 36) rotate(0)", "translate(36 36) rotate(-90)"]
    assert [turned.get("transform") for turned in triple] == ["translate(36 36) rotate(-30)", "translate(36 36) rotate(-120)", "translate(36 36) rotate(-75)"]
    assert len(odd) == 1
    assert double.get("stroke") == "#000000"


def test_a_tiny_distance_draws_a_bounded_number_of_lines() -> None:
    lines = hatch_lines("M0,0 L7200,0 L7200,7200 Z", {"draw:distance": "0.0001in"})
    assert lines is not None
    assert len(lines[0]) == 2 * MAX_LINES + 1


def test_a_page_draws_a_bounded_number_of_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    # Each square takes 17 lines: the second passes a budget of 20 and keeps its fill only
    monkeypatch.setattr(hatch, "MAX_PAGE_LINES", 20)
    svg = page(SQUARE, SQUARE)
    assert fill_hatches(svg, calls(HATCH, PATH, PATH))
    assert [child.tag.split("}")[1] for child in svg[1]] == ["path", "g", "path"]
    assert (svg[1][2].get("style") or "").endswith("fill: #ffffff;")


def test_a_path_without_area_gets_no_lines() -> None:
    svg = page("M0,0 L72,0")
    assert fill_hatches(svg, calls(HATCH, PATH))
    assert len(svg[0]) == 1
    assert hatch_lines("", {}) is None


def test_other_counts_leave_the_paths() -> None:
    svg = page(SQUARE)
    assert not fill_hatches(svg, calls(HATCH, PATH, PATH))
    assert "fill: #ffffff" not in (svg[0][0].get("style") or "")
