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

import math
from xml.etree import ElementTree as ET

from .pathdata import Token, tokenize

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


def _replace(data: str, tokens: list[Token], changes: dict[int, float]) -> str:
    """The path data with the numbers at the given token indexes replaced, written as libvisio writes them."""
    out, last = [], 0
    for index in sorted(changes):
        _, start, end = tokens[index]
        out += [data[last:start], f"{changes[index]:.4f}"]
        last = end
    return "".join(out) + data[last:]


def shortened(data: str, length: float, end: str) -> str:
    """The path data with its start or its end, the end of a line under an arrowhead, cut back by length.

    LibreOffice and Visio end a line at the base of its arrowhead: drawn to its point, the line runs on through
    the arrowhead, and its round cap shows past the tip. The point moves back along the last lineto, or with
    the control point next to it along a curve. A line too short for it, a closed path and an arc stay.
    """
    tokens = tokenize(data)
    letters = [index for index, (token, _, _) in enumerate(tokens) if token.isalpha()]
    if length <= 0 or not letters or tokens[letters[-1]][0] in "Zz":
        return data
    numbers = [index for index, (token, _, _) in enumerate(tokens) if not token.isalpha()]
    if len(numbers) < 4 or any(tokens[index][0] not in "MLC" for index in letters):
        return data
    if end == "end":
        point, reference = numbers[-2:], numbers[-4:-2]
        moved = [point]
        # A curve moves its last control point with its end, which keeps its tangent
        if tokens[letters[-1]][0] == "C" and letters[-1] < numbers[-6]:
            moved.append(reference)
    else:
        point, reference = numbers[:2], numbers[2:4]
        moved = [point]
        # A curve moves its first control point with its start, which keeps its tangent
        if len(letters) > 1 and tokens[letters[1]][0] == "C" and letters[1] < reference[0]:
            moved.append(reference)
    x, y = (float(tokens[index][0]) for index in point)
    rx, ry = (float(tokens[index][0]) for index in reference)
    distance = math.hypot(x - rx, y - ry)
    if distance <= length:
        return data
    dx, dy = (rx - x) / distance * length, (ry - y) / distance * length
    changes = {}
    for pair in moved:
        changes[pair[0]] = float(tokens[pair[0]][0]) + dx
        changes[pair[1]] = float(tokens[pair[1]][0]) + dy
    return _replace(data, tokens, changes)
