"""Gradient fills."""

from __future__ import annotations

import logging
from pathlib import Path
from xml.etree import ElementTree as ET

import helpers
import pytest
from helpers import vsdx

from weasyvsdx.convert import Limits, Tools, convert
from weasyvsdx.gradients import Gradient, fill_gradients, gradient_element, path_shapes, shape_gradients
from weasyvsdx.hidden import SVG_NS
from weasyvsdx.raw import first_page

ON = "<Cell N='FillGradientEnabled' V='1'/>"
STOPS = (
    "<Section N='FillGradient'><Row IX='0'><Cell N='GradientStopColor' V='#32D4F5'/><Cell N='GradientStopPosition' V='0.22'/></Row>"
    "<Row IX='1'><Cell N='GradientStopColor' V='#198ab3'/><Cell N='GradientStopColorTrans' V='0.25'/><Cell N='GradientStopPosition' V='1'/></Row>"
    "<Row IX='2' Del='1'/></Section>"
)
UP = "<Cell N='FillGradientAngle' V='1.570796326794897'/>"
SQUARE = "M0,0 L72,0 L72,72 L0,72 Z"
SOLID = "setStyle (draw:fill: solid, draw:fill-color: #000000)"
LIGHT = Gradient("", 90.0, ((0.22, "#32d4f5", 1.0), (1.0, "#198ab3", 0.75)))


def path(shape: str) -> str:
    return f"drawPath (draw:id: id{shape}, svg:d: ((librevenge:path-action: M, svg:x: 0in, svg:y: 0in)))"


def calls(*lines: str) -> list[tuple[str, str]]:
    return first_page("startPage()\n" + "\n".join(lines) + "\nendPage\n")


def page(count: int) -> ET.Element:
    paths = "".join(f'<path d="{SQUARE}" style="fill: #000000; "/>' for _ in range(count))
    return ET.fromstring(f'<svg xmlns="{SVG_NS}"><g>{paths}</g></svg>')


def test_the_gradient_of_a_shape_of_a_master() -> None:
    master = f"<Shape ID='5' Type='Group'><Shapes><Shape ID='6'>{ON}{UP}{STOPS}</Shape></Shapes></Shape>"
    page = "<Shape ID='10' Master='2'><Shapes><Shape ID='11' MasterShape='6'/></Shapes></Shape>"
    assert shape_gradients(vsdx(page, master)) == {"11": LIGHT}


def test_a_shape_overrides_the_cells_and_stops_of_its_master() -> None:
    master = f"<Shape ID='5'>{ON}{UP}{STOPS}</Shape>"
    own = "<Section N='FillGradient'><Row IX='0'><Cell N='GradientStopColor' V='#ffffff'/></Row><Row IX='1' Del='1'/></Section>"
    page = f"<Shape ID='1' Master='2'><Cell N='FillGradientAngle' V='0'/>{own}</Shape><Shape ID='2' Master='2'><Cell N='FillGradientEnabled' V='0'/></Shape>"
    assert shape_gradients(vsdx(page, master)) == {"1": Gradient("", 0.0, ((0.22, "#ffffff", 1.0),))}


def test_a_shape_that_deletes_the_stops_of_its_master_has_its_own_only() -> None:
    master = f"<Shape ID='5'>{ON}{STOPS}</Shape>"
    own = "<Section N='FillGradient' Del='1'/><Section N='FillGradient'><Row IX='3'><Cell N='GradientStopColor' V='#ffffff'/></Row></Section>"
    page = f"<Shape ID='1' Master='2'><Section N='FillGradient' Del='1'/></Shape><Shape ID='2' Master='2'>{own}</Shape>"
    assert shape_gradients(vsdx(page, master)) == {"2": Gradient("", 0.0, ((0.0, "#ffffff", 1.0),))}


def test_a_gradient_of_a_style_and_the_styles_it_inherits() -> None:
    styles = f"<StyleSheets><StyleSheet ID='3' FillStyle='4'><Cell N='FillGradientDir' V='Themed'/></StyleSheet><StyleSheet ID='4' FillStyle='3'>{ON}{STOPS}</StyleSheet></StyleSheets>"
    page = "<Shape ID='1' FillStyle='3'/><Shape ID='2' FillStyle='9'/>"
    assert shape_gradients(vsdx(page, document=styles)) == {"1": Gradient("Themed", 0.0, LIGHT.stops)}


@pytest.mark.parametrize(("direction", "attributes"), [("1", ("1", "1", "1.4")), ("3", ("0.5", "0.5", "0.73")), ("4", ("0.5", "0", "1.1")), ("7", ("0", "0", "1.4"))])
def test_a_radial_gradient_from_a_corner_an_edge_or_the_center(direction: str, attributes: tuple[str, str, str]) -> None:
    gradients = shape_gradients(vsdx(f"<Shape ID='1'>{ON}<Cell N='FillGradientDir' V='{direction}'/>{STOPS}</Shape>")) or {}
    element = gradient_element("g", gradients["1"])
    assert element.tag == f"{{{SVG_NS}}}radialGradient"
    center = (element.get("cx"), element.get("cy"), element.get("r"))
    assert center == attributes


def test_the_colors_of_the_palette_and_of_the_document() -> None:
    stops = "".join(f"<Row IX='{index}'><Cell N='GradientStopColor' V='{color}'/></Row>" for index, color in enumerate(("2", "24", "#ABCDEF")))
    colors = "<Colors><ColorEntry IX='24' RGB='#7F7F7F'/></Colors>"
    gradients = shape_gradients(vsdx(f"<Shape ID='1'>{ON}<Section N='FillGradient'>{stops}</Section></Shape>", document=colors)) or {}
    assert [color for _, color, _ in gradients["1"].stops] == ["#ff0000", "#7f7f7f", "#abcdef"]


@pytest.mark.parametrize(
    "cells",
    [
        # A kind of gradient the SVG of Visio does not show
        f"{ON}<Cell N='FillGradientDir' V='10'/>{STOPS}",
        # A color of the theme, one past the palette, one that is no color
        f"{ON}<Section N='FillGradient'><Row IX='0'><Cell N='GradientStopColor' V='Themed'/></Row></Section>",
        f"{ON}<Section N='FillGradient'><Row IX='0'><Cell N='GradientStopColor' V='99'/></Row></Section>",
        f"{ON}<Section N='FillGradient'><Row IX='0'><Cell N='GradientStopColor' V='#fff'/></Row></Section>",
        f"{ON}<Section N='FillGradient'><Row IX='0'/></Section>",
        # No stops, no gradient
        ON,
        STOPS,
    ],
)
def test_a_gradient_this_module_does_not_draw(cells: str) -> None:
    assert shape_gradients(vsdx(f"<Shape ID='1'>{cells}</Shape>")) == {}


def test_offsets_and_opacities_stay_between_zero_and_one() -> None:
    stops = "<Row IX='0'><Cell N='GradientStopColor' V='#000000'/><Cell N='GradientStopPosition' V='-1'/><Cell N='GradientStopColorTrans' V='Themed'/></Row>"
    stops += "<Row IX='1'><Cell N='GradientStopColor' V='#000000'/><Cell N='GradientStopPosition' V='7'/><Cell N='GradientStopColorTrans' V='2'/></Row>"
    gradients = shape_gradients(vsdx(f"<Shape ID='1'>{ON}<Cell N='FillGradientAngle' V='x'/><Section N='FillGradient'>{stops}</Section></Shape>")) or {}
    assert gradients["1"] == Gradient("", 0.0, ((0.0, "#000000", 1.0), (1.0, "#000000", 0.0)))


def test_a_shape_of_an_id_on_the_background_page_keeps_its_fill() -> None:
    shapes = f"<Shape ID='1'>{ON}{STOPS}</Shape><Shape ID='2'>{ON}{STOPS}</Shape>"
    assert list(shape_gradients(vsdx(shapes)) or {}) == ["1", "2"]
    assert list(shape_gradients(vsdx(shapes, backed=True)) or {}) == ["2"]


@pytest.mark.parametrize("value", ["1e309", "-inf", "nan"])
def test_a_number_out_of_range_takes_the_default(value: str) -> None:
    stops = f"<Row IX='0'><Cell N='GradientStopColor' V='#000000'/><Cell N='GradientStopPosition' V='{value}'/><Cell N='GradientStopColorTrans' V='{value}'/></Row>"
    gradients = shape_gradients(vsdx(f"<Shape ID='1'>{ON}<Cell N='FillGradientAngle' V='{value}'/><Section N='FillGradient'>{stops}</Section></Shape>")) or {}
    assert gradients["1"] == Gradient("", 0.0, ((0.0, "#000000", 1.0),))
    gradient_element("g", gradients["1"])


def test_the_gradient_turns_and_flips_with_its_shape_and_its_groups() -> None:
    turned = "<Cell N='Angle' V='1.570796326794897'/>"
    master = f"<Shape ID='5'>{ON}{STOPS}</Shape>"
    page = (
        # A quarter turn counterclockwise: the gradient runs up, not right
        f"<Shape ID='1' Master='2'>{turned}</Shape>"
        # Inside a group of a quarter turn and flipped across: down
        f"<Shape ID='2'>{turned}<Cell N='FlipX' V='1'/><Shapes><Shape ID='3' Master='2'/></Shapes></Shape>"
        # Flipped both ways: left
        f"<Shape ID='4' Master='2'><Cell N='FlipX' V='1'/><Cell N='FlipY' V='1'/></Shape>"
        # Flipped upside down, a radial gradient from the top left corner starts at the bottom left
        f"<Shape ID='6' Master='2'><Cell N='FlipY' V='1'/><Cell N='FillGradientDir' V='7'/></Shape>"
        # A fill that keeps its gradient straight
        f"<Shape ID='7' Master='2'>{turned}<Cell N='RotateGradientWithShape' V='0'/></Shape>"
    )
    gradients = shape_gradients(vsdx(page, master)) or {}
    ends = {shape: tuple(float(gradient_element("g", gradients[shape]).get(key) or "") for key in ("x1", "y1", "x2", "y2")) for shape in ("1", "3", "4", "7")}
    assert ends == {"1": (0.5, 1.0, 0.5, 0.0), "3": (0.5, 0.0, 0.5, 1.0), "4": (1.0, 0.5, 0.0, 0.5), "7": (0.0, 0.5, 1.0, 0.5)}
    radial = gradient_element("g", gradients["6"])
    assert (radial.get("cx"), radial.get("cy")) == ("0", "1")


def test_an_id_that_a_shape_of_a_master_shares_with_the_page_keeps_its_fill() -> None:
    # The page does not list the shapes of the group: libvisio draws shape 1 of the master, and the page has a shape 1
    master = f"<Shape ID='5' Type='Group'><Shapes><Shape ID='1'>{ON}{STOPS}</Shape><Shape ID='8'>{ON}{STOPS}</Shape></Shapes></Shape>"
    page = f"<Shape ID='1'>{ON}{STOPS}</Shape><Shape ID='2' Master='2'/>"
    assert list(shape_gradients(vsdx(page, master)) or {}) == ["8"]
    # The same where the shape of the page fills without a gradient
    assert list(shape_gradients(vsdx("<Shape ID='1'/><Shape ID='2' Master='2'/>", master)) or {}) == ["8"]


def test_another_drawing_has_no_gradients() -> None:
    assert shape_gradients(b"\xd0\xcf\x11\xe0 a VSD") is None


def test_a_path_without_a_name_belongs_to_the_layer_around_it() -> None:
    unnamed = "drawPath (svg:d: ((librevenge:path-action: M, svg:x: 0in, svg:y: 0in)))"
    lines = (unnamed, "startLayer (draw:id: id5)", unnamed, path("6"), "startLayer ()", unnamed, "endLayer", unnamed, "endLayer", "endLayer", unnamed, "drawPath (draw:id: id9)")
    assert path_shapes(calls(*lines)) == ["", "5", "6", "", "5", ""]


def test_a_linear_gradient_runs_along_its_angle_through_the_box() -> None:
    element = gradient_element("g", LIGHT)
    assert element.tag == f"{{{SVG_NS}}}linearGradient"
    assert {key: element.get(key) for key in ("x1", "y1", "x2", "y2")} == {"x1": "0.5000", "y1": "0.0000", "x2": "0.5000", "y2": "1.0000"}
    assert [(stop.get("offset"), stop.get("stop-color"), stop.get("stop-opacity")) for stop in element] == [("0.22", "#32d4f5", "1"), ("1", "#198ab3", "0.75")]


def test_each_path_of_a_shape_with_a_gradient_fills_with_it() -> None:
    svg = page(5)
    hatch = "setStyle (draw:fill: hatch, draw:color: #000000)"
    assert fill_gradients(svg, calls(SOLID, path("1"), path("2"), path("1"), "setStyle (draw:fill: none)", path("1"), hatch, path("1")), {"1": LIGHT})
    defs, group = svg
    assert [element.get("id") for element in defs] == ["weasyvsdx-gradient-0"]
    styles = [element.get("style") for element in group]
    assert styles == ["fill: #000000; fill: url(#weasyvsdx-gradient-0);", "fill: #000000; ", "fill: #000000; fill: url(#weasyvsdx-gradient-0);", "fill: #000000; ", "fill: #000000; "]


def test_two_gradients_share_one_definition_element() -> None:
    svg = page(2)
    dark = Gradient("7", 0.0, ((0.0, "#000000", 1.0),))
    assert fill_gradients(svg, calls(SOLID, path("1"), path("2")), {"1": LIGHT, "2": dark})
    defs = svg[0]
    assert [(element.tag, element.get("id")) for element in defs] == [(f"{{{SVG_NS}}}linearGradient", "weasyvsdx-gradient-0"), (f"{{{SVG_NS}}}radialGradient", "weasyvsdx-gradient-1")]


def test_a_page_whose_counts_differ_keeps_its_fills() -> None:
    svg = page(1)
    assert not fill_gradients(svg, calls(SOLID, path("1"), path("1")), {"1": LIGHT})
    assert len(svg) == 1


def tool(tmp_path: Path, body: str) -> str:
    """A vsd2raw of a shell script."""
    path = tmp_path / "fake-vsd2raw"
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return str(path)


def test_a_drawing_fills_its_shapes_with_their_gradients(tmp_path: Path) -> None:
    # libvisio names no shape in this drawing: the vsd2raw here names shape 7, which has a gradient, for each path
    raw = tool(tmp_path, f"{helpers.TOOLS.raw} \"$@\" | sed 's/drawPath (svg:d:/drawPath (draw:id: id7, svg:d:/'")
    root = ET.fromstring(convert(helpers.drawing("poi/test.vsdx"), Tools(helpers.CONVERTER, raw=raw), Limits()))
    assert [element.tag for element in root.iter() if element.get("id", "").startswith("weasyvsdx-gradient-")] == [f"{{{SVG_NS}}}linearGradient"]
    assert any("url(#weasyvsdx-gradient-0)" in (element.get("style") or "") for element in root.iter(f"{{{SVG_NS}}}path"))


def test_the_fills_stay_when_the_tools_count_other_paths(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    raw = tool(tmp_path, "printf 'startPage()\\nendPage\\n'")
    with caplog.at_level(logging.WARNING, logger="weasyvsdx"):
        root = ET.fromstring(convert(helpers.drawing("poi/test.vsdx"), Tools(helpers.CONVERTER, raw=raw), Limits()))
    assert not any(element.tag == f"{{{SVG_NS}}}linearGradient" for element in root.iter())
    assert "fill with a gradient may fill black" in caplog.text
