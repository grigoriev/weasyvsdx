"""Shapes whose geometry only their master holds."""

from __future__ import annotations

import io
import math
import zipfile
from xml.etree import ElementTree as ET

import pytest
from helpers import vsdx

from weasyvsdx import geometry
from weasyvsdx.geometry import Affine, add_missing, outline, path_data
from weasyvsdx.hidden import MASTER_CLASS, SVG_NS, drawn_paths
from weasyvsdx.package import Package, Placed, cell, page_shapes
from weasyvsdx.raw import first_page

SQUARE = (
    "<Section N='Geometry' IX='0'><Row T='RelMoveTo' IX='1'><Cell N='X' V='0'/><Cell N='Y' V='0'/></Row>"
    "<Row T='RelLineTo' IX='2'><Cell N='X' V='1'/><Cell N='Y' V='0'/></Row><Row T='RelLineTo' IX='3'><Cell N='X' V='1'/><Cell N='Y' V='1'/></Row>"
    "<Row T='RelLineTo' IX='4'><Cell N='X' V='0'/><Cell N='Y' V='1'/></Row><Row T='RelLineTo' IX='5'><Cell N='X' V='0'/><Cell N='Y' V='0'/></Row></Section>"
)
SIZE = "<Cell N='Width' V='1'/><Cell N='Height' V='1'/><Cell N='PinX' V='0.5'/><Cell N='PinY' V='0.5'/><Cell N='LocPinX' V='0.5'/><Cell N='LocPinY' V='0.5'/>"
RED = "<Cell N='FillForegnd' V='#ff0000'/><Cell N='LineColor' V='#0000ff'/><Cell N='LineWeight' V='0.01'/>"
# A master group of two shapes: 6, a square, and 7, a square without fill
MASTER = f"<Shape ID='5' Type='Group'>{SIZE}<Shapes><Shape ID='6'>{SIZE}{RED}{SQUARE}</Shape><Shape ID='7'>{SIZE}{RED}<Cell N='FillPattern' V='0'/>{SQUARE}</Shape></Shapes></Shape>"
GROUP = f"<Shape ID='1' Master='2'>{SIZE}<Shapes><Shape ID='2' MasterShape='6'/><Shape ID='3' MasterShape='7'/></Shapes></Shape>"


def shapes(page: str, master: str | None = None, **options: object) -> dict[str, Placed]:
    with zipfile.ZipFile(io.BytesIO(vsdx(page, master, **options))) as archive:  # type: ignore[arg-type]
        return {placed.shape.get("ID", ""): placed for placed in page_shapes(Package(archive))}


def points(placed: Placed) -> list[tuple[float, float]]:
    sections, master = geometry._sections(placed)
    return [(round(x, 4), round(y, 4)) for _, items in outline(placed, sections, master) for x, y in items]


def call(shape: str) -> str:
    return f"drawPath (draw:id: id{shape}, svg:d: ((librevenge:path-action: M, svg:x: 0in, svg:y: 0in)))"


def calls(*lines: str) -> list[tuple[str, str]]:
    return first_page("startPage()\n" + "\n".join(lines) + "\nendPage\n")


def page(count: int) -> ET.Element:
    paths = "".join('<path d="M0,0"/>' for _ in range(count))
    return ET.fromstring(f'<svg xmlns="{SVG_NS}" viewBox="0 0 720 720"><g>{paths}</g></svg>')


def outline_of(*rows: str, width: float = 2.0, height: float = 1.0) -> list[tuple[str, tuple[tuple[float, float], ...]]]:
    """The commands of rows, written as Visio writes them, for a shape of width and height."""
    section = ET.fromstring(f"<Section xmlns='http://schemas.microsoft.com/office/visio/2012/main'>{''.join(rows)}</Section>")
    shape = geometry._Outline(width, height, 1.0, 1.0)
    for kind, values, formulas, inherited in geometry._rows(section):
        shape.row(kind, values, formulas, inherited)
    return [(name, tuple((round(x, 4), round(y, 4)) for x, y in items)) for name, items in shape.commands]


def row(kind: str, index: int, **cells: str) -> str:
    content = "".join(f"<Cell N='{name}' V='{value}'/>" if not value.startswith("=") else f"<Cell N='{name}' V='0' F='{value[1:]}'/>" for name, value in cells.items())
    return f"<Row T='{kind}' IX='{index}'>{content}</Row>"


def test_lines_and_curves_take_the_size_of_the_shape() -> None:
    commands = outline_of(
        row("RelMoveTo", 1, X="0", Y="0"),
        row("RelLineTo", 2, X="1", Y="0"),
        row("LineTo", 3, X="2", Y="1"),
        row("RelCubBezTo", 4, X="0", Y="1", A="0.5", B="1", C="0.25", D="1"),
        row("RelQuadBezTo", 5, X="0", Y="0", A="0", B="0.5"),
        row("MoveTo", 6, X="1", Y="1"),
        row("Unknown", 7),
    )
    assert commands == [
        ("M", ((0.0, 0.0),)),
        ("L", ((2.0, 0.0),)),
        ("L", ((2.0, 1.0),)),
        ("C", ((1.0, 1.0), (0.5, 1.0), (0.0, 1.0))),
        ("C", ((0.0, 0.6667), (0.0, 0.3333), (0.0, 0.0))),
        ("M", ((1.0, 1.0),)),
    ]


def test_an_arc_bows_to_the_right_of_its_chord() -> None:
    commands = outline_of(row("MoveTo", 1, X="0", Y="0"), row("ArcTo", 2, X="1", Y="0", A="0.5"))
    points = [point for _, items in commands for point in items]
    # A half circle below the chord from (0, 0) to (1, 0)
    assert min(y for _, y in points) == pytest.approx(-0.5, abs=0.01)
    assert all(point[1] <= 0 and abs(math.dist(point, (0.5, 0.0)) - 0.5) < 1e-3 for point in points)
    assert commands[-1] == ("L", ((1.0, 0.0),))
    # No bow, or no chord: a line
    assert outline_of(row("MoveTo", 1, X="0", Y="0"), row("ArcTo", 2, X="1", Y="0", A="0"))[1:] == [("L", ((1.0, 0.0),))]
    assert outline_of(row("MoveTo", 1, X="0", Y="0"), row("ArcTo", 2, X="0", Y="0", A="1"))[1:] == [("L", ((0.0, 0.0),))]


def test_an_elliptical_arc_passes_its_control_point() -> None:
    # Half an ellipse twice as wide as high, from the left end of its axis over the top to the right end
    commands = outline_of(row("MoveTo", 1, X="-2", Y="0"), row("EllipticalArcTo", 2, X="2", Y="0", A="0", B="1", C="0", D="2"))
    points = [point for _, items in commands for point in items]
    assert max(y for _, y in points) == pytest.approx(1.0, abs=0.01)
    assert all(abs((x / 2) ** 2 + y**2 - 1) < 0.01 for x, y in points)
    # The same on an axis turned by a quarter turn
    turned = outline_of(row("MoveTo", 1, X="0", Y="-2"), row("EllipticalArcTo", 2, X="0", Y="2", A="1", B="0", C="1.5707963267949", D="2"))
    assert max(x for _, items in turned for x, _ in items) == pytest.approx(1.0, abs=0.01)
    # A ratio of zero, and three points on a line: a line
    assert outline_of(row("MoveTo", 1, X="0", Y="0"), row("EllipticalArcTo", 2, X="2", Y="0", A="1", B="1", D="0"))[1:] == [("L", ((2.0, 0.0),))]
    assert outline_of(row("MoveTo", 1, X="0", Y="0"), row("RelEllipticalArcTo", 2, X="1", Y="0", A="0.5", B="0", D="1"))[1:] == [("L", ((2.0, 0.0),))]


def test_an_ellipse_through_the_ends_of_its_axes() -> None:
    commands = outline_of(row("Ellipse", 1, X="1", Y="1", A="2", B="1", C="1", D="1.5"))
    points = [point for _, items in commands for point in items]
    assert commands[0] == ("M", ((2.0, 1.0),))
    assert commands[-1] == ("Z", ())
    assert all(abs((x - 1) ** 2 + ((y - 1) / 0.5) ** 2 - 1) < 0.01 for x, y in points)


def test_a_polyline_relative_or_absolute() -> None:
    commands = outline_of(row("MoveTo", 1, X="0", Y="0"), row("PolylineTo", 2, X="2", Y="1", A="=POLYLINE(0, 1, 0.5, 0.5, 1, 0.25)"))
    assert commands[1:] == [("L", ((1.0, 0.5),)), ("L", ((2.0, 0.25),)), ("L", ((2.0, 1.0),))]
    # A formula that refers to other cells, or that is too short, gives no points of its own
    assert outline_of(row("MoveTo", 1, X="0", Y="0"), row("PolylineTo", 2, X="2", Y="1", A="=POLYLINE(0, 0, Geometry1.X1, 1)"))[1:] == [("L", ((2.0, 1.0),))]
    assert outline_of(row("MoveTo", 1, X="0", Y="0"), row("PolylineTo", 2, X="2", Y="1", A="=POLYLINE(0)"))[1:] == [("L", ((2.0, 1.0),))]


def test_a_nurbs_runs_from_the_current_point_to_its_end() -> None:
    # A quadratic B-spline through the corner (1, 0) between (0, 0) and (1, 1): it stays within their triangle
    commands = outline_of(row("MoveTo", 1, X="0", Y="0"), row("NURBSTo", 2, X="1", Y="1", A="0", B="1", C="0", D="1", E="=NURBS(1, 2, 1, 1, 1, 0, 0, 1)"))
    points = [point for _, items in commands for point in items]
    assert points[-1] == (1.0, 1.0)
    assert len(points) > 4
    assert all(-1e-9 <= y <= x + 1e-9 for x, y in points)
    # Two spans, which meet at the inner knot 0.5
    spans = outline_of(row("MoveTo", 1, X="0", Y="0"), row("NURBSTo", 2, X="2", Y="1", A="0.5", B="1", C="0", D="1", E="=NURBS(1, 2, 1, 1, 1, 0, 0, 1, 1, 1, 0, 1)"))
    assert spans[-1] == ("L", ((2.0, 1.0),))
    assert len(spans) > 2 * geometry.NURBS_SEGMENTS
    # The degree past the count of points, knots that span nothing, weights of zero, a formula too short
    degree = outline_of(row("MoveTo", 1, X="0", Y="0"), row("NURBSTo", 2, X="1", Y="1", A="1", B="1", C="0", D="1", E="=NURBS(1, 5, 0, 0, 0.5, 0, 0, 1)"))
    assert degree[-1] == ("L", ((1.0, 1.0),))
    flat = outline_of(row("MoveTo", 1, X="0", Y="0"), row("NURBSTo", 2, X="1", Y="1", A="0", C="0", E="=NURBS(0, 2, 1, 1, 1, 0, 0, 1)"))
    assert flat[1:] == [("L", ((1.0, 0.0),)), ("L", ((1.0, 1.0),))]
    zero = outline_of(row("MoveTo", 1, X="0", Y="0"), row("NURBSTo", 2, X="1", Y="1", A="1", B="0", C="0", D="0", E="=NURBS(1, 2, 1, 1, 1, 0, 0, 0)"))
    assert zero[-1] == ("L", ((1.0, 1.0),))
    assert outline_of(row("MoveTo", 1, X="0", Y="0"), row("NURBSTo", 2, X="1", Y="1", E="=NURBS(1, 2)"))[1:] == [("L", ((1.0, 1.0),))]


@pytest.mark.parametrize("formula", ["NURBS(1, 1e999, 1, 1, 1, 0, 0, 1)", "NURBS(1, 2, 1, 1, 1, 0, 0, 1e999)"])
def test_a_nurbs_of_numbers_out_of_range_is_a_line(formula: str) -> None:
    assert outline_of(row("MoveTo", 1, X="0", Y="0"), row("NURBSTo", 2, X="1", Y="1", E=f"={formula}"))[1:] == [("L", ((1.0, 1.0),))]


def test_a_nurbs_stays_bounded() -> None:
    many = ", ".join("0.5, 0.5, 0, 1" for _ in range(geometry.MAX_NURBS_POINTS))
    assert outline_of(row("MoveTo", 1, X="0", Y="0"), row("NURBSTo", 2, X="1", Y="1", E=f"=NURBS(1, 2, 1, 1, {many})"))[1:] == [("L", ((1.0, 1.0),))]
    # A degree past the most is the most: twelve points of degree 99 make three spans of degree 9
    twelve = ", ".join(f"{index / 12}, 0, 0, 1" for index in range(1, 11))
    high = outline_of(row("MoveTo", 1, X="0", Y="0"), row("NURBSTo", 2, X="1", Y="0", A="0", C="0", E=f"=NURBS(1, 99, 1, 1, {twelve})"))
    assert len(high) == 1 + 3 * geometry.NURBS_SEGMENTS


def test_a_shape_takes_its_place_on_the_page_through_its_groups() -> None:
    turned = "<Cell N='Width' V='1'/><Cell N='Height' V='1'/><Cell N='PinX' V='5'/><Cell N='PinY' V='5'/><Cell N='LocPinX' V='0'/><Cell N='LocPinY' V='0'/>"
    page = f"<Shape ID='1'>{turned}<Cell N='Angle' V='1.5707963267949'/><Shapes><Shape ID='2'>{SIZE}{SQUARE}</Shape></Shapes></Shape><Shape ID='3'>{SIZE}<Cell N='FlipX' V='1'/><Cell N='FlipY' V='1'/>{SQUARE}</Shape>"
    found = shapes(page)
    # The square of the group, a quarter turn counterclockwise about the pin of the group at (5, 5)
    assert points(found["2"]) == [(5.0, 5.0), (5.0, 6.0), (4.0, 6.0), (4.0, 5.0), (5.0, 5.0)]
    # Flipped both ways about its own pin
    assert points(found["3"]) == [(1.0, 1.0), (0.0, 1.0), (0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]


def test_a_shape_inherits_the_geometry_of_its_master_row_by_row() -> None:
    wide = "<Cell N='Width' V='2'/><Cell N='Height' V='1'/><Cell N='PinX' V='1'/><Cell N='PinY' V='0.5'/><Cell N='LocPinX' V='1'/><Cell N='LocPinY' V='0.5'/>"
    master = (
        f"<Shape ID='5'>{SIZE}<Section N='Geometry' IX='0'><Cell N='NoFill' V='1'/>"
        "<Row T='MoveTo' IX='1'><Cell N='X' V='0'/><Cell N='Y' V='0'/></Row><Row T='LineTo' IX='2'><Cell N='X' V='1'/><Cell N='Y' V='1'/></Row>"
        "<Row T='LineTo' IX='3'><Cell N='X' V='0'/><Cell N='Y' V='1'/></Row></Section>"
        "<Section N='Geometry' IX='1'><Row T='MoveTo' IX='1'><Cell N='X' V='0'/><Cell N='Y' V='0'/></Row></Section>"
        "<Section N='Geometry' IX='2'><Cell N='NoShow' V='1'/><Row T='MoveTo' IX='1'/></Section></Shape>"
    )
    # Its own end of the first line, at its own size, and no third row nor second section
    own = "<Section N='Geometry' IX='0'><Row IX='2'><Cell N='X' V='1.5'/></Row><Row IX='3' Del='1'/></Section><Section N='Geometry' IX='1' Del='1'/>"
    found = shapes(f"<Shape ID='1' Master='2'>{wide}{own}</Shape><Shape ID='2' Master='2'>{wide}</Shape>", master)
    sections, inherits = geometry._sections(found["1"])
    assert len(sections) == 1
    assert cell(sections, "NoFill") == "1"
    # The master holds its rows at its own size, 1 by 1: they stretch to the shape, 2 by 1
    assert [point for _, items in outline(found["1"], sections, inherits) for point in items] == [(0.0, 0.0), (1.5, 1.0)]
    assert points(found["2"]) == [(0.0, 0.0), (2.0, 1.0), (0.0, 1.0), (0.0, 0.0)]


def test_path_data_in_points_with_y_down() -> None:
    assert path_data([("M", ((0.0, 0.0),)), ("L", ((1.0, 1.0),)), ("Z", ())], 10.0) == "M0.0000,720.0000 L72.0000,648.0000 Z"


def test_affine_maps_compose_in_order() -> None:
    move, turn = Affine(e=1.0), Affine(0.0, 1.0, -1.0, 0.0)
    assert move.then(turn).apply((1.0, 0.0)) == pytest.approx((0.0, 2.0))
    assert turn.then(move).apply((1.0, 0.0)) == pytest.approx((1.0, 1.0))


def test_a_missing_shape_fills_and_strokes_with_its_cells() -> None:
    svg = page(1)
    assert add_missing(svg, calls(call("1")), vsdx(GROUP, MASTER)) == 3
    added = [element for element in svg.iter(f"{{{SVG_NS}}}path") if element.get("class") == MASTER_CLASS]
    styles = [element.get("style") or "" for element in added]
    # Shape 2: its fill, then its line; shape 3: its line only, without fill
    assert styles[0].startswith("fill-rule: evenodd; fill: #ff0000; fill-opacity: 1;")
    assert styles[1].startswith("fill: none; stroke: #0000ff;")
    assert "stroke-width: 0.7200;" in styles[1]
    assert styles[2].startswith("fill: none; stroke: #0000ff;")
    assert added[0].get("d") == "M0.0000,720.0000 L72.0000,720.0000 L72.0000,648.0000 L0.0000,648.0000 L0.0000,720.0000"
    # After the path of the group, before which they come, and passed by when the paths of the page pair with the calls
    assert [element.get("class") for element in svg[0]] == [None, MASTER_CLASS, MASTER_CLASS, MASTER_CLASS]
    assert len(drawn_paths(svg)) == 1


def test_a_missing_shape_with_a_gradient_and_a_dashed_line() -> None:
    gradient = "<Cell N='FillGradientEnabled' V='1'/><Section N='FillGradient'><Row IX='0'><Cell N='GradientStopColor' V='#00ff00'/></Row></Section>"
    dashed = "<Cell N='LinePattern' V='2'/><Cell N='LineColorTrans' V='0.5'/><Cell N='FillForegndTrans' V='0.25'/>"
    child = f"{SIZE}{RED}{gradient}{dashed}{SQUARE}"
    master = f"<Shape ID='5' Type='Group'>{SIZE}<Shapes><Shape ID='6'>{child}</Shape><Shape ID='7'>{child}</Shape></Shapes></Shape>"
    svg = page(0)
    assert add_missing(svg, calls(), vsdx(GROUP, master)) == 4
    defs, fill, line = svg[0], svg[1], svg[2]
    assert [element.get("id") for element in defs] == ["weasyvsdx-master-gradient-0", "weasyvsdx-master-gradient-1"]
    assert "fill-opacity: 0.75;" in (fill.get("style") or "")
    assert (fill.get("style") or "").endswith("fill: url(#weasyvsdx-master-gradient-0);")
    assert "stroke-opacity: 0.5;" in (line.get("style") or "")
    assert (line.get("style") or "").endswith("stroke-dasharray: 5.0400, 3.6000;")


def test_definitions_added_after_a_path_keep_the_order() -> None:
    gradient = "<Cell N='FillGradientEnabled' V='1'/><Section N='FillGradient'><Row IX='0'><Cell N='GradientStopColor' V='#00ff00'/></Row></Section>"
    master = f"<Shape ID='5' Type='Group'>{SIZE}<Shapes><Shape ID='6'>{SIZE}{RED}{SQUARE}</Shape><Shape ID='7'>{SIZE}{RED}{gradient}{SQUARE}</Shape></Shapes></Shape>"
    svg = page(0)
    assert add_missing(svg, calls(), vsdx(GROUP, master)) == 4
    # The definitions go first; the paths keep the order of their shapes, before the paths of the page
    assert [element.tag.split("}")[1] for element in svg] == ["defs", "path", "path", "path", "path", "g"]
    assert "url(#" not in (svg[1].get("style") or "")
    assert "url(#weasyvsdx-master-gradient-0)" in (svg[3].get("style") or "")


def test_an_open_or_unfilled_outline_has_no_fill_and_a_theme_color_draws_nothing() -> None:
    open_line = "<Section N='Geometry' IX='0'><Row T='RelMoveTo' IX='1'><Cell N='X' V='0'/><Cell N='Y' V='0'/></Row><Row T='RelLineTo' IX='2'><Cell N='X' V='1'/><Cell N='Y' V='1'/></Row></Section>"
    themed = "<Cell N='FillForegnd' V='Themed'/><Cell N='LineColor' V='Themed'/>"
    no_line = SQUARE.replace("IX='0'>", "IX='0'><Cell N='NoLine' V='1'/>", 1)
    master = (
        f"<Shape ID='5' Type='Group'>{SIZE}<Shapes><Shape ID='6'>{SIZE}{RED}{open_line}</Shape><Shape ID='7'>{SIZE}{themed}{SQUARE}</Shape>"
        f"<Shape ID='8'>{SIZE}{RED}<Cell N='LinePattern' V='0'/>{SQUARE}</Shape><Shape ID='9'>{SIZE}{RED}{no_line}</Shape></Shapes></Shape>"
    )
    group = f"<Shape ID='1' Master='2'>{SIZE}<Shapes>" + "".join(f"<Shape ID='{index}' MasterShape='{index + 4}'/>" for index in range(2, 6)) + "</Shapes></Shape>"
    svg = page(0)
    # The open line only strokes, the shape of theme colors draws nothing, the last two only fill
    assert add_missing(svg, calls(), vsdx(group, master)) == 3
    added = [element for element in svg if element.get("class") == MASTER_CLASS]
    assert [(element.get("style") or "").split(";")[1].strip() for element in added] == ["stroke: #0000ff", "fill: #ff0000", "fill: #ff0000"]


def test_a_shape_libvisio_draws_stays() -> None:
    # Shape 2 is drawn: only shape 3, a line, is added
    assert add_missing(page(2), calls(call("1"), call("2")), vsdx(GROUP, MASTER)) == 1


def test_a_hidden_group_or_layer_hides_the_shape() -> None:
    hidden = call("1").replace("svg:d:", "draw:display: none, svg:d:")
    assert add_missing(page(1), calls(hidden), vsdx(GROUP, MASTER)) == 0
    layers = "<PageSheet><Section N='Layer'><Row IX='3'><Cell N='Visible' V='1'/><Cell N='Print' V='0'/></Row></Section></PageSheet>"
    layered = GROUP.replace("MasterShape='6'/>", "MasterShape='6'><Cell N='LayerMember' V='0;3'/></Shape>")
    assert add_missing(page(1), calls(call("1")), vsdx(layered, MASTER, layers=layers)) == 1


def test_a_shape_with_a_geometry_of_its_own_or_none_to_inherit_stays() -> None:
    page_shapes = f"<Shape ID='1' Master='2'>{SIZE}<Shapes><Shape ID='2' MasterShape='6'>{SQUARE}</Shape><Shape ID='3' MasterShape='5'/></Shapes></Shape>"
    assert add_missing(page(1), calls(call("1")), vsdx(page_shapes, MASTER)) == 0


def test_an_id_twice_or_on_the_background_stays() -> None:
    assert add_missing(page(1), calls(call("1")), vsdx(GROUP + "<Shape ID='2'/>", MASTER)) == 1
    # The background page has a shape 1: shape 3 renamed 1 stays
    assert add_missing(page(1), calls(call("9")), vsdx(GROUP.replace("ID='1' Master", "ID='9' Master").replace("ID='3'", "ID='1'"), MASTER, backed=True)) == 2


def test_a_page_that_does_not_pair_or_a_drawing_that_does_not_read() -> None:
    assert add_missing(page(2), calls(call("1")), vsdx(GROUP, MASTER)) is None
    assert add_missing(page(0), calls(), b"\xd0\xcf\x11\xe0 a VSD") == 0


def test_the_segments_of_a_page_stay_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geometry, "MAX_SEGMENTS", 0)
    assert add_missing(page(0), calls(), vsdx(GROUP, MASTER)) == 2
