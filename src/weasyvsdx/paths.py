"""Paths of a drawing that start without a moveto.

libvisio writes some paths that start with a lineto: the first point of a geometry whose first row is
not a MoveTo. SVG requires a path to start with a moveto, and WeasyPrint draws the lineto from the origin
of the page: a line from the top left corner to the shape. LibreOffice takes the first point as the
start, so the first lineto becomes a moveto here too.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
LINETO = {"L": "M", "l": "m"}


def start_with_moveto(page: ET.Element) -> int:
    """Turn the first lineto of each path that starts with one into a moveto; return how many."""
    count = 0
    for path in page.iter(f"{{{SVG_NS}}}path"):
        data = path.get("d") or ""
        stripped = data.lstrip()
        if stripped[:1] in LINETO:
            path.set("d", LINETO[stripped[0]] + stripped[1:])
            count += 1
    return count
