"""Shapes that Visio does not show.

libvisio marks a shape it should not draw with ``draw:display: none``: a shape on a layer that is hidden or
does not print. The generic SVG generator ignores the property and draws it, as a page-sized tint over
w365-azure-network-connection-6. Each drawPath call with path data writes one ``<path>``, outside the
definitions of markers and patterns, in the order of the calls: the n-th path of the page belongs to the n-th
such call, and the path of a hidden call goes. A page whose counts differ keeps its paths.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from .raw import Call, properties

SVG_NS = "http://www.w3.org/2000/svg"
# Elements whose paths are no shapes of the page
DEFINITIONS = frozenset(f"{{{SVG_NS}}}{tag}" for tag in ("defs", "marker", "pattern", "clipPath", "mask"))


def drawn_paths(page: ET.Element) -> list[tuple[ET.Element, ET.Element]]:
    """Each path of the page that a drawPath call wrote, with its parent, in document order."""
    found: list[tuple[ET.Element, ET.Element]] = []

    def walk(parent: ET.Element) -> None:
        for child in parent:
            if child.tag == f"{{{SVG_NS}}}path":
                found.append((child, parent))
            elif child.tag not in DEFINITIONS:
                walk(child)

    walk(page)
    return found


def remove_hidden(page: ET.Element, calls: list[Call]) -> bool:
    """Remove the path of each hidden drawPath call. False, and nothing removed, when the counts differ."""
    draws = [properties(argument) for name, argument in calls if name == "drawPath" and "svg:d:" in argument]
    paths = drawn_paths(page)
    if len(paths) != len(draws):
        return False
    for (path, parent), draw in zip(paths, draws, strict=True):
        if draw.get("draw:display") == "none":
            parent.remove(path)
    return True
