"""Fill colors from the XML of a VSDX.

libvisio 0.1.8 and later fill the shapes of a VSDX with a color of its theme over their own: the icons of the
Azure stencils turned into olive disks. A VSDX holds the color of each shape, FillForegnd, in the XML of its
page, its masters and its styles; on the corpus it is the color libvisio 0.1.7 writes for 98.6 % of the paths.

Each path whose shape fills with a color gets that color back, in the SVG of vsd2xhtml and in the calls of
vsd2raw, which the hatches read. A pattern draws its lines in FillForegnd over FillBkgnd, as libvisio 0.1.7
writes all 71 hatches of the corpus. The n-th path of the page belongs to the n-th drawPath call with path data,
as in hidden.py, and its shape is the one gradients.path_shapes() names. A color of the theme draws white, as
Visio draws most of them.

libvisio draws the background pages first, and names their shapes by IDs that the page may use too. Their
paths come before the first path of a shape the background pages lack, or of a group they lack, and take
the colors of the background pages. A shape whose ID two shapes of one page share, a VSD and a VSDX that does
not read keep what libvisio wrote.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from . import gradients
from .hidden import drawn_paths
from .package import Package, Placed, cell, page_shapes, read
from .raw import Call, properties

FILL_COLOR = re.compile(r"draw:fill-color: #[0-9A-Fa-f]{6}")
LINE_COLOR = re.compile(r"draw:color: #[0-9A-Fa-f]{6}")
# The fill of a shape that takes it from the theme: Visio draws most of them white, 270 of 400 in its SVG of
# the bench, and so does libvisio 0.1.7; 0.1.11 fills them with an accent of the theme
THEMED_FILL = "#ffffff"


# The colors of a fill: its foreground, the color of a solid fill and of the lines of a pattern, and its background
Colors = tuple[str | None, str | None]


@dataclass(frozen=True)
class Fills:
    """The fill colors of the shapes of the first page and of its background pages, by ID, and the IDs of the shapes and groups of the background pages."""

    page: dict[str, Colors]
    background: dict[str, Colors]
    background_ids: frozenset[str]
    groups: frozenset[str]


def _color(value: str | None, colors: dict[str, str]) -> str | None:
    return THEMED_FILL if value == gradients.THEMED else gradients.color_of(value, colors)


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
        found[shape_id] = (_color(cell(chain, "FillForegnd"), colors), _color(cell(chain, "FillBkgnd"), colors))
    return {shape_id: color for shape_id, color in found.items() if shape_id not in ambiguous}


def _fills(package: Package) -> Fills:
    styles = package.styles()
    colors = package.colors()
    background = [placed for page in package.background_pages() for placed in page_shapes(package, page)]
    ids = frozenset(placed.shape.get("ID", "") for placed in background)
    groups = frozenset(group.shape.get("ID", "") for placed in background for group in placed.groups)
    return Fills(_colors(page_shapes(package), styles, colors), _colors(background, styles, colors), ids, groups)


def shape_fills(document: bytes) -> Fills | None:
    """The fill colors of the shapes of the first page of a VSDX and of its background pages; None for another drawing."""
    return read(document, _fills)


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
    on_background = bool(fills.background_ids)
    result: list[Call] = []
    layers: list[str] = []
    style = ""
    index = 0
    for name, argument in calls:
        if name == "setStyle":
            style = argument
        elif name == "startLayer":
            layers.append(properties(argument).get("draw:id", ""))
        elif name == "endLayer" and layers:
            layers.pop()
        if name != "drawPath" or "svg:d:" not in argument:
            result.append((name, argument))
            continue
        path, shape = paths[index][0], shapes[index]
        index += 1
        # The background ends at a shape it lacks, or at a group it lacks
        group = next((layer.removeprefix("id") for layer in reversed(layers) if layer), None)
        if on_background and (shape not in fills.background_ids or (group is not None and group not in fills.groups)):
            on_background = False
        recolored = _recolored(style, (fills.background if on_background else fills.page).get(shape, (None, None)))
        if recolored is None:
            result.append((name, argument))
            continue
        result.extend([("setStyle", recolored), (name, argument), ("setStyle", style)])
        color = properties(recolored).get("draw:fill-color")
        if properties(style).get("draw:fill") == "solid" and color:
            path.set("style", f"{path.get('style', '').rstrip()} fill: {color};".strip())
    return result


def _recolored(style: str, colors: Colors) -> str | None:
    """A setStyle argument with the colors of a shape: a solid fill takes its foreground, a hatch its lines in the
    foreground over its background; None where nothing changes."""
    current = properties(style)
    foreground, background = colors
    if current.get("draw:fill") == "solid":
        changes = [(FILL_COLOR, "draw:fill-color", foreground)]
    elif current.get("draw:fill") == "hatch":
        changes = [(FILL_COLOR, "draw:fill-color", background), (LINE_COLOR, "draw:color", foreground)]
    else:
        return None
    recolored = style
    for pattern, key, color in changes:
        if color is not None and (current.get(key) or "").lower() != color:
            recolored = pattern.sub(f"{key}: {color}", recolored)
    return recolored if recolored != style else None
