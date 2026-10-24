"""Fill colors from the XML of a VSDX."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest
from helpers import vsdx

from weasyvsdx import geometry
from weasyvsdx.fills import Box, Fills, recolor, shape_fills
from weasyvsdx.hidden import SVG_NS
from weasyvsdx.raw import first_page

GREEN = "<Cell N='FillForegnd' V='#00ff00'/><Cell N='FillBkgnd' V='#ffff00'/>"
THEME = "setStyle (draw:fill: solid, draw:fill-color: #83992a, svg:fill-rule: evenodd)"
HATCH = "setStyle (draw:fill: hatch, draw:color: #83992a, draw:fill-color: #83992a, draw:fill-hatch-solid: true)"
NONE = "setStyle (draw:fill: none, draw:fill-color: #83992a)"


def path(shape: str) -> str:
    return f"drawPath (draw:id: id{shape}, svg:d: ((librevenge:path-action: M, svg:x: 0in, svg:y: 0in)))"


def calls(*lines: str) -> list[tuple[str, str]]:
    return first_page("startPage()\n" + "\n".join(lines) + "\nendPage\n")


def page(count: int, data: tuple[str, ...] = ()) -> ET.Element:
    """A page of 10 by 10 inches with paths of the data given, and of a point for the rest."""
    data = data + ("M0,0",) * (count - len(data))
    paths = "".join(f'<path d="{d}" style="fill-rule: evenodd; fill: #83992a; "/>' for d in data)
    return ET.fromstring(f'<svg xmlns="{SVG_NS}" viewBox="0 0 720 720"><g>{paths}</g></svg>')


def fills(page: dict[str, tuple[str | None, str | None]], background: dict[str, tuple[str | None, str | None]] | None = None, groups: frozenset[str] = frozenset()) -> Fills:
    """Fills of the page and the background, the shapes of the background in the order of its keys."""
    background = background or {}
    return Fills(page, background, {shape: index for index, shape in enumerate(background)}, groups)


def test_the_colors_of_the_shapes_their_masters_and_styles() -> None:
    master = f"<Shape ID='5'>{GREEN}</Shape>"
    styles = "<StyleSheets><StyleSheet ID='3'><Cell N='FillForegnd' V='2'/></StyleSheet></StyleSheets>"
    shapes = (
        "<Shape ID='1' Master='2'/>"
        # A color of the theme of quick style 100 draws white, an accent keeps what libvisio draws, and so does a shape without a fill color
        "<Shape ID='2'><Cell N='FillForegnd' V='Themed'/><Cell N='QuickStyleFillColor' V='100'/></Shape>"
        "<Shape ID='7'><Cell N='FillForegnd' V='Themed'/><Cell N='QuickStyleFillColor' V='201'/></Shape>"
        "<Shape ID='3' FillStyle='3'/><Shape ID='4'/>"
        # Two shapes of one ID keep what libvisio drew
        "<Shape ID='6'/><Shape ID='6'/>"
    )
    found = shape_fills(vsdx(shapes, master, document=styles))
    assert found is not None
    # An index of the palette, as shape 3 has through its style, is a color too
    assert found.page == {"1": ("#00ff00", "#ffff00"), "2": ("#ffffff", None), "7": (None, None), "3": ("#ff0000", None), "4": (None, None)}
    assert found.background == {}


def test_the_background_pages_their_shapes_and_groups() -> None:
    found = shape_fills(vsdx("<Shape ID='1'/>", backed=True))
    assert found is not None
    # The background page of the helper has a shape 1 with text only
    assert found.background == {"1": (None, None)}
    assert found.background_order == {"1": 0}
    assert found.groups == frozenset()


def test_another_drawing_has_no_fills() -> None:
    assert shape_fills(b"\xd0\xcf\x11\xe0 a VSD") is None


def test_a_solid_fill_takes_the_color_of_its_shape() -> None:
    svg = page(3)
    result = recolor(svg, calls(THEME, path("1"), path("2"), path("3")), fills({"1": ("#00ff00", None), "2": ("#83992a", None)}))
    assert result is not None
    styles = [element.get("style") for element in svg.iter(f"{{{SVG_NS}}}path")]
    # Shape 2 has the color libvisio wrote, shape 3 none in the XML
    assert styles == ["fill-rule: evenodd; fill: #83992a; fill: #00ff00;", "fill-rule: evenodd; fill: #83992a; ", "fill-rule: evenodd; fill: #83992a; "]
    # A setStyle of its own around the path whose color changes
    assert [name for name, _ in result] == ["startPage", "setStyle", "setStyle", "drawPath", "setStyle", "drawPath", "drawPath", "endPage"]
    assert "draw:fill-color: #00ff00" in result[2][1]
    assert result[4][1] == result[1][1]


def test_a_hatch_draws_its_lines_in_the_foreground_over_the_background() -> None:
    svg = page(1)
    result = recolor(svg, calls(HATCH, path("1")), fills({"1": ("#00ff00", "#ffff00")}))
    assert result is not None
    assert "draw:color: #00ff00" in result[2][1]
    assert "draw:fill-color: #ffff00" in result[2][1]
    # The hatch step fills the path, not this one
    assert svg[0][0].get("style") == "fill-rule: evenodd; fill: #83992a; "


def test_no_fill_keeps_its_style() -> None:
    result = recolor(page(1), calls(NONE, path("1")), fills({"1": ("#00ff00", None)}))
    assert result == calls(NONE, path("1"))


def test_the_background_comes_first_and_ends_at_a_shape_or_group_it_lacks() -> None:
    # Shape 1 of the background, then shape 1 of the page inside its group 1, which the background lacks
    svg = page(4)
    lines = (THEME, path("1"), path("2"), "startLayer (draw:id: id1)", path("1"), "endLayer", path("2"))
    result = recolor(svg, calls(*lines), fills({"1": ("#0000ff", None), "2": ("#000001", None)}, {"1": ("#ffffff", None), "2": ("#ffff00", None)}))
    assert result is not None
    assert [(element.get("style") or "").split("fill: ")[-1] for element in svg.iter(f"{{{SVG_NS}}}path")] == ["#ffffff;", "#ffff00;", "#0000ff;", "#000001;"]


def test_the_background_ends_where_its_shapes_start_over() -> None:
    # Shapes 1 and 2 of the background, then shape 1 of the page, outside any group: the order starts over
    svg = page(4)
    lines = (THEME, path("1"), path("1"), path("2"), path("1"))
    result = recolor(svg, calls(*lines), fills({"1": ("#0000ff", None)}, {"1": ("#ffffff", None), "2": ("#ffff00", None)}))
    assert result is not None
    assert [(element.get("style") or "").split("fill: ")[-1] for element in svg.iter(f"{{{SVG_NS}}}path")] == ["#ffffff;", "#ffffff;", "#ffff00;", "#0000ff;"]


def test_a_shape_of_the_page_and_of_its_background_of_one_id_goes_by_its_outline() -> None:
    # The background rectangle 1 fills the page, the shape 1 of the page is an inch square at its top left
    whole, square, line = "M0,0 L720,0 L720,720 L0,720 Z", "M0,0 L72,0 L72,72 L0,72 Z", "M0,0 L72,0"
    boxes: dict[str, tuple[Box | None, Box | None]] = {"1": ((0.0, 0.0, 10.0, 10.0), (0.0, 9.0, 1.0, 10.0))}
    colors = Fills({"1": ("#0000ff", None)}, {"1": ("#ffffff", None)}, {"1": 0}, frozenset(), boxes)
    svg = page(3, (whole, line, square))
    assert recolor(svg, calls(THEME, path("1"), path("1"), path("1")), colors) is not None
    # The line has no box to tell: it keeps what libvisio drew
    assert [(element.get("style") or "").split("fill: ")[-1] for element in svg.iter(f"{{{SVG_NS}}}path")] == ["#ffffff;", "#83992a; ", "#0000ff;"]
    # Without the outline of either shape, both keep it
    svg = page(1, (whole,))
    assert recolor(svg, calls(THEME, path("1")), Fills({"1": ("#0000ff", None)}, {"1": ("#ffffff", None)}, {"1": 0}, frozenset(), {"1": (None, None)})) is not None
    assert svg[0][0].get("style") == "fill-rule: evenodd; fill: #83992a; "


def test_the_boxes_of_the_shapes_of_one_id() -> None:
    square = "<Cell N='Width' V='1'/><Cell N='Height' V='1'/><Cell N='PinX' V='0.5'/><Cell N='PinY' V='0.5'/><Cell N='LocPinX' V='0.5'/><Cell N='LocPinY' V='0.5'/>"
    geometry = "<Section N='Geometry' IX='0'><Row T='RelMoveTo' IX='1'><Cell N='X' V='0'/><Cell N='Y' V='0'/></Row><Row T='RelLineTo' IX='2'><Cell N='X' V='1'/><Cell N='Y' V='1'/></Row></Section>"
    found = shape_fills(vsdx(f"<Shape ID='1'>{square}{geometry}</Shape>", backed=True))
    assert found is not None
    # The shape 1 of the background of the helper has no geometry
    assert found.boxes == {"1": (None, (0.0, 0.0, 1.0, 1.0))}


def test_the_outlines_past_the_budget_of_a_page_have_no_box(monkeypatch: pytest.MonkeyPatch) -> None:
    square = "<Cell N='Width' V='1'/><Cell N='Height' V='1'/><Cell N='PinX' V='0.5'/><Cell N='PinY' V='0.5'/><Cell N='LocPinX' V='0.5'/><Cell N='LocPinY' V='0.5'/>"
    geometry_rows = "<Section N='Geometry' IX='0'><Row T='RelMoveTo' IX='1'><Cell N='X' V='0'/><Cell N='Y' V='0'/></Row><Row T='RelLineTo' IX='2'><Cell N='X' V='1'/><Cell N='Y' V='1'/></Row></Section>"
    monkeypatch.setattr(geometry, "MAX_SEGMENTS", 3)
    found = shape_fills(vsdx(f"<Shape ID='1'>{square}{geometry_rows}</Shape>", backed=True))
    assert found is not None
    assert found.boxes == {"1": (None, None)}


def test_a_group_of_the_background_stays_on_the_background() -> None:
    svg = page(2)
    lines = (THEME, "startLayer (draw:id: id7)", path("8"), "endLayer", path("9"))
    result = recolor(svg, calls(*lines), fills({"8": ("#0000ff", None), "9": ("#0000fe", None)}, {"8": ("#ffffff", None)}, frozenset({"7"})))
    assert result is not None
    assert [(element.get("style") or "").split("fill: ")[-1] for element in svg.iter(f"{{{SVG_NS}}}path")] == ["#ffffff;", "#0000fe;"]


def test_a_page_whose_counts_differ_keeps_its_colors() -> None:
    svg = page(1)
    assert recolor(svg, calls(THEME, path("1"), path("1")), fills({"1": ("#00ff00", None)})) is None
    assert svg[0][0].get("style") == "fill-rule: evenodd; fill: #83992a; "
