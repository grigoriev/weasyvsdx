"""Hatched fills.

libvisio turns a fill pattern of Visio into an ODF hatch: ``draw:fill: hatch`` with the color, distance and
rotation of its lines, and, with ``draw:fill-hatch-solid``, the fill color behind them. The generic SVG
generator writes no fill for a hatch, and SVG fills such a path black: a hatched room of a floor plan became a
black block. Each such path gets its fill color, or none, and the lines of its hatch clipped to it. The n-th
path of the page belongs to the n-th drawPath call with path data, as in hidden.py, and its style is the last
setStyle before that call.
"""

from __future__ import annotations

import math
from xml.etree import ElementTree as ET

from .hidden import SVG_NS, drawn_paths
from .markers import path_box
from .raw import Call, Properties, points, properties

# The lines of each hatch style, as angles to the first line: single, double crossed, triple with a diagonal
LINES = {"single": (0,), "double": (0, 90), "triple": (0, 90, 45)}
DEFAULT_DISTANCE = 7.2  # points, 0.1 inch: the distance LibreOffice draws when none is given
LINE_WIDTH = 0.4  # points, a hairline as LibreOffice draws it
DISPLAY = "draw:display"
MAX_PAGE_LINES = 100_000  # all hatch lines of a page: many hatched shapes at a tiny distance stay bounded
MAX_LINES = 500  # each way from the center: a hatch of a huge shape at a tiny distance stays drawable


def draw_styles(calls: list[Call]) -> list[Properties]:
    """The style of each drawPath call with path data: the last setStyle before it, and its own draw:display."""
    style: Properties = {}
    styles = []
    for name, argument in calls:
        if name == "setStyle":
            style = properties(argument)
        elif name == "drawPath" and "svg:d:" in argument:
            display = properties(argument).get(DISPLAY)
            styles.append({**style, DISPLAY: display} if display else style)
    return styles


def hatch_lines(data: str, style: Properties) -> ET.Element | None:
    """The lines of a hatch over the box of the path data, in a group to clip; None for a path without area.

    The lines are drawn, not tiled: a tiled pattern shows seams between its tiles in PDF viewers.
    """
    box = path_box(data)
    if box is None:
        return None
    x, y, width, height = box
    distance = points(style.get("draw:distance")) or DEFAULT_DISTANCE
    # Past the half diagonal: an arc bulges out of the box of its end points
    reach = math.hypot(width, height) * 0.6
    count = min(int(reach / distance), MAX_LINES)
    # ODF turns the hatch counterclockwise, SVG with y down turns clockwise
    rotation = 0 - float(style.get("draw:rotation", "0") or 0)
    group = ET.Element(f"{{{SVG_NS}}}g", {"stroke": style.get("draw:color", "#000000"), "stroke-width": f"{LINE_WIDTH:g}", "fill": "none"})
    for angle in LINES.get(style.get("draw:style", "single"), LINES["single"]):
        turned = ET.SubElement(group, f"{{{SVG_NS}}}g", {"transform": f"translate({x + width / 2:g} {y + height / 2:g}) rotate({rotation - angle:g})"})
        # Lines, not one path: the paths of the page pair with the drawPath calls by their count
        for step in range(-count, count + 1):
            offset = f"{step * distance:.2f}"
            ET.SubElement(turned, f"{{{SVG_NS}}}line", {"x1": f"{-reach:.2f}", "y1": offset, "x2": f"{reach:.2f}", "y2": offset})
    return group


def fill_hatches(page: ET.Element, calls: list[Call]) -> bool:
    """Draw the hatch of each hatched path over its fill; return False, and change nothing, when the counts differ."""
    styles = draw_styles(calls)
    paths = drawn_paths(page)
    if len(paths) != len(styles):
        return False
    defs = None
    used = 0
    for (path, parent), style in zip(paths, styles, strict=True):
        # A hidden shape goes with hidden.py, which removes its path but would leave its lines
        if style.get("draw:fill") != "hatch" or style.get(DISPLAY) == "none":
            continue
        fill = style.get("draw:fill-color", "#ffffff") if style.get("draw:fill-hatch-solid") == "true" else "none"
        path.set("style", f"{path.get('style', '').rstrip()} fill: {fill};".strip())
        lines = hatch_lines(path.get("d") or "", style)
        if lines is None:
            continue
        # Past the budget of the page a shape keeps its fill without lines
        count = sum(len(turned) for turned in lines)
        if used + count > MAX_PAGE_LINES:
            continue
        used += count
        if defs is None:
            defs = ET.Element(f"{{{SVG_NS}}}defs")
            page.insert(0, defs)
        clip_lines(defs, lines, path, style)
        parent.insert(list(parent).index(path) + 1, lines)
    return True


def clip_lines(defs: ET.Element, lines: ET.Element, path: ET.Element, style: Properties) -> None:
    """Clip the lines of a hatch to its path, through a clipPath added to the definitions."""
    clip = ET.SubElement(defs, f"{{{SVG_NS}}}clipPath", {"id": f"weasyvsdx-hatch-{len(defs)}"})
    ET.SubElement(clip, f"{{{SVG_NS}}}path", {"d": path.get("d") or "", "clip-rule": style.get("svg:fill-rule", "nonzero")})
    lines.set("clip-path", f"url(#{clip.get('id')})")
