"""Fill colors from the XML of a VSDX.

libvisio 0.1.8 and later fill the shapes of a VSDX with a color of its theme over their own: the icons of the
Azure stencils turned into olive disks. A VSDX holds the color of each shape, FillForegnd, in the XML of its
page, its masters and its styles, as the value Visio worked out when it saved the drawing: a color written
out or an index of the palette. On the corpus it is the color libvisio 0.1.7 writes for 98.6 % of the paths.

Each path whose shape fills with a color gets that color back, in the SVG of vsd2xhtml and in the calls of
vsd2raw, which the hatches read. A pattern draws its lines in FillForegnd over FillBkgnd, as libvisio 0.1.7
writes all 71 hatches of the corpus. The n-th path of the page belongs to the n-th drawPath call with path data,
as in hidden.py, and its shape is the one gradients.path_shapes() names. A color of the theme of quick style color
100 draws white, as Visio draws most of them; an accent of the theme keeps what libvisio draws.

libvisio draws the background pages first, and names their shapes by IDs that the page may use too. Their
paths come before the first path of a shape or a group the background pages lack, or of a shape that comes
earlier in their order than the shape before it, and take the colors of the background pages. Where a shape
of the page and of its background have one ID, the path goes with the one whose outline its box is nearer
to. A shape whose ID two shapes of one page share, a VSD and a VSDX that does
not read keep what libvisio wrote.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from . import geometry, gradients
from .hidden import drawn_paths
from .markers import path_box
from .package import Package, Placed, cell, page_shapes, read
from .raw import Call, properties

FILL_KEY = "draw:fill"
FILL_COLOR_KEY = "draw:fill-color"
FILL_COLOR = re.compile(r"draw:fill-color: #[0-9A-Fa-f]{6}")
PT_PER_INCH = 72.0
LINE_COLOR = re.compile(r"draw:color: #[0-9A-Fa-f]{6}")
# The fill of a shape that takes it from the theme, with the quick style color 100: Visio draws most of them
# white, 300 of 330 in its SVG of the bench, and so does libvisio 0.1.7; 0.1.11 fills them with an accent of
# the theme. A fill of another quick style color, an accent, keeps what libvisio draws: 0.1.7 and 0.1.11 tell
# them apart, and the bench has no SVG of Visio to tell which is right.
THEMED_FILL = "#ffffff"
WHITE_QUICK_STYLE = "100"


# A box on the page in inches, y up: left, bottom, right, top
Box = tuple[float, float, float, float]
# The colors of a fill: its foreground, the color of a solid fill and of the lines of a pattern, and its background
Colors = tuple[str | None, str | None]


@dataclass(frozen=True)
class Fills:
    """The fill colors of the shapes of the first page and of its background pages, by ID, the place of each
    shape of the background pages in the order libvisio draws them, and the IDs of their groups."""

    page: dict[str, Colors]
    background: dict[str, Colors]
    background_order: dict[str, int]
    groups: frozenset[str]
    # The boxes of the shapes whose ID the page and its background share, on the background and on the page
    boxes: dict[str, tuple[Box | None, Box | None]] = field(default_factory=dict)
    # The IDs of the shapes of the background that draw no path: a path of such an ID is of the page
    pathless: frozenset[str] = frozenset()


def _color(value: str | None, colors: dict[str, str], quick_style: str | None) -> str | None:
    """The color of a fill cell to restore; None where libvisio keeps its own."""
    if value == gradients.THEMED:
        return THEMED_FILL if quick_style == WHITE_QUICK_STYLE else None
    # The value Visio worked out when it saved the drawing: a color written out or an index of the palette
    return gradients.color_of(value, colors)


def _colors(shapes: Iterable[Placed], styles: dict[str, ET.Element], colors: dict[str, str]) -> dict[str, Colors]:
    """The fill colors of each shape by its ID, without the IDs two shapes share."""
    found: dict[str, Colors] = {}
    seen: set[str] = set()
    ambiguous: set[str] = set()
    for placed in shapes:
        shape_id = placed.shape.get("ID", "")
        if shape_id in seen:
            ambiguous.add(shape_id)
        seen.add(shape_id)
        chain = gradients.chain_of(placed.shape, placed.master_shape, styles)
        quick_style = cell(chain, "QuickStyleFillColor")
        found[shape_id] = (_color(cell(chain, "FillForegnd"), colors, quick_style), _color(cell(chain, "FillBkgnd"), colors, None))
    return {shape_id: color for shape_id, color in found.items() if shape_id not in ambiguous}


def _fills(package: Package) -> Fills:
    styles = package.styles()
    colors = package.colors()
    background = [placed for page in package.background_pages() for placed in page_shapes(package, page)]
    order: dict[str, int] = {}
    for placed in background:
        order.setdefault(placed.shape.get("ID", ""), len(order))
    groups = frozenset(group.shape.get("ID", "") for placed in background for group in placed.groups)
    shapes = list(page_shapes(package))
    # libvisio names a shape of the page and of its background alike: their outlines tell their paths apart
    page, colors_of_background = _colors(shapes, styles, colors), _colors(background, styles, colors)
    by_id = {placed.shape.get("ID", ""): placed for placed in background}
    # One budget for the outlines of all these shapes, as for the shapes geometry.py draws on a page
    budget = geometry.Budget(geometry.MAX_SEGMENTS)
    shared = {shape_id: placed for placed in shapes if (shape_id := placed.shape.get("ID", "")) in by_id and (shape_id in page or shape_id in colors_of_background)}
    pathless = frozenset(shape_id for shape_id in shared if not geometry.has_outline(by_id[shape_id], budget))
    boxes = {shape_id: (geometry.shape_box(by_id[shape_id], budget), geometry.shape_box(placed, budget)) for shape_id, placed in shared.items()}
    return Fills(page, colors_of_background, order, groups, boxes, pathless)


def shape_fills(document: bytes) -> Fills | None:
    """The fill colors of the shapes of the first page of a VSDX and of its background pages; None for another drawing."""
    return read(document, _fills)


class _Recolor:
    """The walk over the calls of a page: the style, the layers and whether the background is still being drawn."""

    def __init__(self, fills: Fills, page_height: float) -> None:
        self.fills = fills
        self.page_height = page_height
        self.on_background = bool(fills.background_order)
        self.place = 0
        self.layers: list[str] = []
        self.style = ""

    def track(self, name: str, argument: str) -> None:
        """Follow the style and the layers."""
        if name == "setStyle":
            self.style = argument
        elif name == "startLayer":
            self.layers.append(properties(argument).get("draw:id", ""))
        elif name == "endLayer" and self.layers:
            self.layers.pop()

    def colors(self, shape: str, data: str) -> Colors | None:
        """The colors of the shape of a path; None where the path keeps what libvisio drew."""
        fills = self.fills
        # The background ends at a shape or a group it lacks, or where its shapes start over
        group = next((layer.removeprefix("id") for layer in reversed(self.layers) if layer), None)
        if self.on_background and (fills.background_order.get(shape, -1) < self.place or (group is not None and group not in fills.groups)):
            self.on_background = False
        self.place = fills.background_order.get(shape, self.place)
        if self.on_background and shape in fills.pathless:
            self.on_background = False
        if self.on_background and shape in fills.boxes:
            side = _side(data, fills.boxes[shape], self.page_height)
            if side is None:
                # Neither outline tells
                return None
            self.on_background = side
        return (fills.background if self.on_background else fills.page).get(shape, (None, None))


def recolor(page: ET.Element, calls: list[Call], fills: Fills) -> list[Call] | None:
    """Fill each path with the color of its shape; the calls with that color too. None, and nothing changed, when the counts differ.

    A path whose color changes gets a setStyle of its own before its drawPath call, and the style before it
    comes back after, so the paths around it keep theirs. Those calls are for the hatches only: the
    arrowheads count the setStyle calls.
    """
    shapes = gradients.path_shapes(calls)
    paths = drawn_paths(page)
    if len(paths) != len(shapes):
        return None
    viewbox = (page.get("viewBox") or "").split()
    walk = _Recolor(fills, float(viewbox[3]) / PT_PER_INCH if len(viewbox) == 4 else 0.0)
    result: list[Call] = []
    drawn = iter(zip(paths, shapes, strict=True))
    for name, argument in calls:
        walk.track(name, argument)
        if name != "drawPath" or "svg:d:" not in argument:
            result.append((name, argument))
            continue
        (path, _), shape = next(drawn)
        colors = walk.colors(shape, path.get("d") or "")
        recolored = _recolored(walk.style, colors) if colors is not None else None
        if recolored is None:
            result.append((name, argument))
            continue
        result.extend([("setStyle", recolored), (name, argument), ("setStyle", walk.style)])
        color = properties(recolored).get(FILL_COLOR_KEY)
        if properties(walk.style).get(FILL_KEY) == "solid" and color:
            path.set("style", f"{path.get('style', '').rstrip()} fill: {color};".strip())
    return result


def _side(data: str, boxes: tuple[Box | None, Box | None], page_height: float) -> bool | None:
    """Whether a path is the shape of the background rather than the shape of the page of its ID: the one whose
    box its own box is nearer to. None where a box is missing."""
    box = path_box(data)
    background, page = boxes
    if box is None or background is None or page is None:
        return None
    x, y, width, height = box
    # Points, y down, as inches, y up
    own = (x / PT_PER_INCH, page_height - (y + height) / PT_PER_INCH, (x + width) / PT_PER_INCH, page_height - y / PT_PER_INCH)
    return _distance(own, background) <= _distance(own, page)


def _distance(first: Box, second: Box) -> float:
    return sum(abs(a - b) for a, b in zip(first, second, strict=True))


def _recolored(style: str, colors: Colors) -> str | None:
    """A setStyle argument with the colors of a shape: a solid fill takes its foreground, a hatch its lines in the
    foreground over its background; None where nothing changes."""
    current = properties(style)
    foreground, background = colors
    if current.get(FILL_KEY) == "solid":
        changes = [(FILL_COLOR, FILL_COLOR_KEY, foreground)]
    elif current.get(FILL_KEY) == "hatch":
        changes = [(FILL_COLOR, FILL_COLOR_KEY, background), (LINE_COLOR, "draw:color", foreground)]
    else:
        return None
    recolored = style
    for pattern, key, color in changes:
        if color is not None and (current.get(key) or "").lower() != color:
            recolored = pattern.sub(f"{key}: {color}", recolored)
    return recolored if recolored != style else None
