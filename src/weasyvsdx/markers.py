"""The arrowheads of a drawing in their own shape and size.

The generic SVG generator of librevenge gives every line end one stock arrow, sized by the width of the
line: a thin connector gets a tiny arrow, and every arrowhead the same shape. Its ``fill="solid"`` is no
color either. vsd2raw prints each style with the marker libvisio found: its path, its viewBox and its
width, as in ODF.

The generator writes one marker for each style that has one, numbered in order: the k-th ``endMarker`` of
the page belongs to the k-th style with ``draw:marker-end-path``, and so for ``startMarker``. Each marker
gets the path of its style. A page whose counts differ keeps its markers.

The marker width spans the box of the path, as LibreOffice scales it: libvisio gives some paths a
viewBox of another size (a path 3000 units wide in a viewBox 20 wide), which would blow the marker up
over the page. The viewBox serves only where the path has no box.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from .raw import Call, Properties, percent, points, properties

SVG_NS = "http://www.w3.org/2000/svg"
ENDS = {"start": "startMarker", "end": "endMarker"}
# The start of each subpath of path data
SUBPATH = re.compile(r"[Mm]")
PATH_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
# The numbers each command of path data takes
ARGUMENTS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}


def marker_styles(calls: list[Call], end: str) -> list[Properties]:
    """The styles among the calls of a page that put a marker on the given end, start or end."""
    styles = (properties(argument) for name, argument in calls if name == "setStyle")
    return [style for style in styles if f"draw:marker-{end}-path" in style]


def path_box(data: str) -> tuple[float, float, float, float] | None:
    """The box of path data, x, y, width and height, through its points and control points; None without area."""
    xs: list[float] = []
    ys: list[float] = []
    x = y = start_x = start_y = 0.0
    command = ""
    tokens = PATH_TOKEN.findall(data)
    index = 0
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command in "Zz":
                x, y = start_x, start_y
            continue
        upper = command.upper()
        count = ARGUMENTS.get(upper)
        if count is None or index + count > len(tokens):
            break
        numbers = [float(token) for token in tokens[index : index + count]]
        index += count
        base_x, base_y = (x, y) if command.islower() else (0.0, 0.0)
        if upper == "H":
            x = base_x + numbers[0]
        elif upper == "V":
            y = base_y + numbers[0]
        else:
            # An arc counts by its end point only: its radii and flags are no points
            pairs = numbers[5:] if upper == "A" else numbers
            for px, py in zip(pairs[0::2], pairs[1::2], strict=True):
                xs.append(base_x + px)
                ys.append(base_y + py)
            x, y = xs[-1], ys[-1]
        xs.append(x)
        ys.append(y)
        if upper == "M":
            start_x, start_y = x, y
            # The pairs after the first of a moveto are linetos
            command = "l" if command == "m" else "L"
    if not xs or max(xs) == min(xs) or max(ys) == min(ys):
        return None
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def viewbox(value: str | None) -> tuple[float, float, float, float] | None:
    try:
        x, y, width, height = (float(number) for number in (value or "").split())
    except ValueError:
        return None
    return (x, y, width, height) if width > 0 and height > 0 else None


def fill_marker(marker: ET.Element, style: Properties, end: str) -> bool:
    """Draw the marker of the style into the marker element. False when the style gives no usable marker."""
    box = path_box(style.get(f"draw:marker-{end}-path", "")) or viewbox(style.get(f"draw:marker-{end}-viewbox"))
    width = points(style.get(f"draw:marker-{end}-width"))
    if box is None or width <= 0:
        return False
    x, y, box_width, box_height = box
    scale = width / box_width
    # ODF draws a marker pointing up: its top middle is the end of the line, or its middle where centered.
    # SVG turns the marker to the direction of the path, along x: a start marker points back along it.
    tip_y = y + box_height / 2 if style.get(f"draw:marker-{end}-center") == "true" else y
    angle = 90 if end == "end" else -90
    for name, value in (("markerUnits", "userSpaceOnUse"), ("orient", "auto"), ("overflow", "visible"), ("markerWidth", "1"), ("markerHeight", "1"), ("refX", "0"), ("refY", "0")):
        marker.set(name, value)
    marker.attrib.pop("viewBox", None)
    for child in list(marker):
        marker.remove(child)
    data = style[f"draw:marker-{end}-path"]
    transform = f"rotate({angle}) scale({scale:g}) translate({-(x + box_width / 2):g} {-tip_y:g})"
    if len(SUBPATH.findall(data)) > 1:
        # A hollow marker, an outline around a hole, hides the line under it as in LibreOffice and Visio,
        # which end the line at the marker: white over its whole outline first
        ET.SubElement(marker, f"{{{SVG_NS}}}path", {"d": data, "transform": transform, "fill": "#ffffff", "stroke": "none"})
    shape = ET.SubElement(marker, f"{{{SVG_NS}}}path")
    shape.set("d", data)
    shape.set("transform", transform)
    # A marker takes the color of its line, which the marker element does not inherit
    shape.set("fill", style.get("svg:stroke-color", "#000000"))
    opacity = percent(style.get("svg:stroke-opacity"), 1.0)
    if opacity < 1:
        shape.set("fill-opacity", f"{opacity:g}")
    shape.set("stroke", "none")
    # A hollow marker is an outline around a hole, as LibreOffice fills its polygons
    shape.set("fill-rule", "evenodd")
    return True


def replace_markers(svg: ET.Element, calls: list[Call]) -> bool:
    """Give each marker of the page the shape and size of its style. False where the counts differ."""
    complete = True
    markers = list(svg.iter(f"{{{SVG_NS}}}marker"))
    for end, prefix in ENDS.items():
        elements = [marker for marker in markers if marker.get("id", "").startswith(prefix)]
        styles = marker_styles(calls, end)
        if len(elements) != len(styles):
            complete = False
            continue
        for marker, style in zip(elements, styles, strict=True):
            fill_marker(marker, style, end)
    return complete
