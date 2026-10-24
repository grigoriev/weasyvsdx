"""Fill colors from the XML of a VSDX."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from helpers import vsdx

from weasyvsdx.fills import Fills, recolor, shape_fills
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


def page(count: int) -> ET.Element:
    paths = "".join('<path d="M0,0" style="fill-rule: evenodd; fill: #83992a; "/>' for _ in range(count))
    return ET.fromstring(f'<svg xmlns="{SVG_NS}"><g>{paths}</g></svg>')


def fills(page: dict[str, tuple[str | None, str | None]], background: dict[str, tuple[str | None, str | None]] | None = None, groups: frozenset[str] = frozenset()) -> Fills:
    background = background or {}
    return Fills(page, background, frozenset(background) | groups, groups)


def test_the_colors_of_the_shapes_their_masters_and_styles() -> None:
    master = f"<Shape ID='5'>{GREEN}</Shape>"
    styles = "<StyleSheets><StyleSheet ID='3'><Cell N='FillForegnd' V='2'/></StyleSheet></StyleSheets>"
    shapes = (
        "<Shape ID='1' Master='2'/>"
        # A color of the theme draws white; a shape without a fill color has none
        "<Shape ID='2'><Cell N='FillForegnd' V='Themed'/></Shape><Shape ID='3' FillStyle='3'/><Shape ID='4'/>"
        # Two shapes of one ID keep what libvisio drew
        "<Shape ID='6'/><Shape ID='6'/>"
    )
    found = shape_fills(vsdx(shapes, master, document=styles))
    assert found is not None
    assert found.page == {"1": ("#00ff00", "#ffff00"), "2": ("#ffffff", None), "3": ("#ff0000", None), "4": (None, None)}
    assert found.background == {}


def test_the_background_pages_their_shapes_and_groups() -> None:
    found = shape_fills(vsdx("<Shape ID='1'/>", backed=True))
    assert found is not None
    # The background page of the helper has a shape 1 with text only
    assert found.background == {"1": (None, None)}
    assert found.background_ids == frozenset({"1"})
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
