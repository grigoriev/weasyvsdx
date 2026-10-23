"""Paths of a drawing that start without a moveto.

libvisio writes some paths whose first segment has no start point: a geometry of Visio whose first row is
no MoveTo. SVG requires a path to start with a moveto, and WeasyPrint starts it at the origin of the page:
a line from the top left corner across the drawing. An arc is worse: libvisio computes its flags from a
start point it does not give, and the arc goes the long way round an ellipse of the size of the page, filled
white over the drawing.

Neither the start point nor the arc can be known from the path, so its first segment goes, and the end of
that segment becomes the start: a lineto becomes the moveto LibreOffice draws, an arc leaves the small shape
it closes.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from .pathdata import tokenize

SVG_NS = "http://www.w3.org/2000/svg"
# The numbers of one segment of each command that ends at a point, its end point the last two
ARGUMENTS = {"L": 2, "T": 2, "Q": 4, "S": 4, "C": 6, "A": 7}


def start_with_moveto(page: ET.Element) -> int:
    """Give each path that starts without a moveto the end of its first segment as start; return how many."""
    count = 0
    for path in page.iter(f"{{{SVG_NS}}}path"):
        data = path.get("d") or ""
        fixed = moved_to_start(data)
        if fixed != data:
            path.set("d", fixed)
            count += 1
    return count


def moved_to_start(data: str) -> str:
    """The path data with its first segment, which has no start point, replaced by a moveto to its end."""
    tokens = tokenize(data)
    if not tokens or not tokens[0][0].isalpha() or tokens[0][0] in "Mm":
        return data
    command = tokens[0][0]
    if command == "l":
        # A relative lineto from an unknown point: the moveto of the same numbers is the best start
        return "m" + data[tokens[0][2] :]
    count = ARGUMENTS.get(command)
    numbers = tokens[1 : 1 + count] if count else []
    if count is None or len(numbers) < count or any(token.isalpha() for token, _, _ in numbers):
        return data
    rest = data[numbers[-1][2] :]
    # More segments of the same command follow without its letter: the letter now has to stand there
    following = tokens[1 + count] if len(tokens) > 1 + count else None
    if following is not None and not following[0].isalpha():
        rest = f" {command}{rest}"
    return f"M{numbers[-2][0]},{numbers[-1][0]}{rest}"
