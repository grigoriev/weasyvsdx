"""The arrowheads of a drawing in their own shape and size."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from weasyvsdx.markers import SVG_NS, fill_marker, marker_styles, path_box, replace_markers
from weasyvsdx.raw import first_page, properties

END = "draw:marker-end-path: m10 0-10 20h20z, draw:marker-end-viewbox: 0 0 20 20, draw:marker-end-width: 0.1528in, svg:stroke-color: #41719c, svg:stroke-opacity: 100.0000%"
START = "draw:marker-start-path: m0 0 10 10, draw:marker-start-viewbox: 0 0 20 10, draw:marker-start-width: 1in, draw:marker-start-center: true, svg:stroke-opacity: 50%"
STOCK = '<marker id="{}" markerUnits="strokeWidth" viewBox="0 0 10 10"><polyline points="0,0 10,5 0,10 1,5" fill="solid"/></marker>'


def page(*styles: str) -> list[tuple[str, str]]:
    return first_page("startPage()\n" + "\n".join(f"setStyle({style})" for style in styles) + "\nendPage\n")


def svg(*ids: str) -> ET.Element:
    return ET.fromstring(f'<svg xmlns="{SVG_NS}"><defs>' + "".join(STOCK.format(marker_id) for marker_id in ids) + "</defs></svg>")


def stock(marker_id: str) -> ET.Element:
    """The stock marker of vsd2xhtml, alone."""
    [marker] = svg(marker_id).iter(f"{{{SVG_NS}}}marker")
    return marker


def test_the_styles_with_a_marker_on_each_end() -> None:
    calls = page("draw:fill: none", END, START, f"{END}, {START}")
    assert len(marker_styles(calls, "end")) == 2
    assert len(marker_styles(calls, "start")) == 2


def test_an_end_marker_takes_the_path_and_width_of_its_style() -> None:
    marker = stock("endMarker1")
    assert fill_marker(marker, properties(END), "end")
    assert marker.get("markerUnits") == "userSpaceOnUse"
    assert marker.get("viewBox") is None
    assert marker.get("overflow") == "visible"
    [path] = marker
    assert path.get("d") == "m10 0-10 20h20z"
    # 0.1528in is 11.0016pt over a viewBox 20 wide; the tip, the top middle, at the end of the line
    assert path.get("transform") == "rotate(90) scale(0.55008) translate(-10 -0)"
    assert path.get("fill") == "#41719c"
    assert path.get("fill-opacity") is None
    assert path.get("stroke") == "none"
    assert path.get("fill-rule") == "evenodd"


def test_a_start_marker_points_back_and_may_be_centered() -> None:
    marker = stock("startMarker1")
    assert fill_marker(marker, properties(START), "start")
    [path] = marker
    # The path spans 10 x 10 of its viewBox of 20 x 10: the box of the path sets the size
    assert path.get("transform") == "rotate(-90) scale(7.2) translate(-5 -5)"
    assert path.get("fill") == "#000000"
    assert path.get("fill-opacity") == "0.5"


def test_a_marker_without_a_usable_box_stays() -> None:
    marker = stock("endMarker1")
    assert not fill_marker(marker, properties("draw:marker-end-path: m0 0, draw:marker-end-viewbox: 0 0 0 20, draw:marker-end-width: 1in"), "end")
    assert not fill_marker(marker, properties("draw:marker-end-path: m0 0, draw:marker-end-viewbox: a b, draw:marker-end-width: 1in"), "end")
    assert not fill_marker(marker, properties("draw:marker-end-path: m0 0, draw:marker-end-viewbox: 0 0 20 20"), "end")
    assert marker[0].tag == f"{{{SVG_NS}}}polyline"


def test_each_marker_gets_the_style_of_its_number() -> None:
    image = svg("startMarker1", "endMarker1", "endMarker2")
    assert replace_markers(image, page(END, START, END.replace("0.1528in", "1in")))
    widths = [marker[0].get("transform", "").split()[1] for marker in image.iter(f"{{{SVG_NS}}}marker")]
    assert widths == ["scale(7.2)", "scale(0.55008)", "scale(3.6)"]


def test_other_counts_leave_those_markers_alone() -> None:
    image = svg("endMarker1", "startMarker1")
    assert not replace_markers(image, page(START))
    markers = list(image.iter(f"{{{SVG_NS}}}marker"))
    assert markers[0][0].tag == f"{{{SVG_NS}}}polyline"
    assert markers[1][0].tag == f"{{{SVG_NS}}}path"


def test_a_path_wider_than_its_viewbox_takes_the_width_of_its_style() -> None:
    marker = stock("startMarker1")
    style = "draw:marker-start-path: M1500 0l1500 2789v211h-114l-1286-2392v2392h-200v-2392l-1286 2392h-114v-211z, draw:marker-start-viewbox: 0 0 20 30, draw:marker-start-width: 0.1088in"
    assert fill_marker(marker, properties(style), "start")
    # 0.1088in over the 3000 units of the path, not over the 20 of the viewBox
    assert marker[0].get("transform") == "rotate(-90) scale(0.0026112) translate(-1500 -0)"


@pytest.mark.parametrize(
    ("data", "box"),
    [
        ("m10 0-10 20h20z", (0.0, 0.0, 20.0, 20.0)),
        ("M1 1 L 5 9", (1.0, 1.0, 4.0, 8.0)),
        ("m0 0 h10 V5 Z l2 2", (0.0, 0.0, 10.0, 5.0)),
        ("M0 0 C 0 -4 10 -4 10 0", (0.0, -4.0, 10.0, 4.0)),
        ("M0 0 A5 5 0 0 1 10 10", (0.0, 0.0, 10.0, 10.0)),
        ("M0 0 q5 -5 10 0 t10 0 s5 5 10 0", (0.0, -5.0, 30.0, 10.0)),
        ("M0 0 1e1 2.5", (0.0, 0.0, 10.0, 2.5)),
        ("M0 0", None),
        ("M0 0 H10", None),
        ("M0 0 L", None),
        ("5 5", None),
        # A number of two dots is no number
        ("M1.2.3 0 L 5 5", None),
    ],
)
def test_the_box_of_path_data(data: str, box: tuple[float, float, float, float] | None) -> None:
    assert path_box(data) == box


def test_a_hollow_marker_hides_the_line_under_it() -> None:
    marker = stock("endMarker1")
    ring = "M10 20c-5 0-10-5-10-10s5-10 10-10 10 5 10 10-5 10-10 10zM10 18c-4 0-8-4-8-8s4-8 8-8 8 4 8 8-4 8-8 8z"
    assert fill_marker(marker, properties(f"draw:marker-end-path: {ring}, draw:marker-end-viewbox: 0 0 20 20, draw:marker-end-width: 1in"), "end")
    under, shape = marker
    assert under.get("fill") == "#ffffff"
    assert under.get("fill-rule") is None
    assert under.get("d") == shape.get("d") == ring
    assert under.get("transform") == shape.get("transform")
    assert shape.get("fill-rule") == "evenodd"


def test_a_solid_marker_gets_no_underlay() -> None:
    marker = stock("endMarker1")
    assert fill_marker(marker, properties(END), "end")
    assert len(marker) == 1
