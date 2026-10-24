"""Shapes whose geometry only their master holds.

A shape of a master group that the page lists inherits its geometry from the master when it has none of its
own. libvisio 0.1.7 takes the geometry of such a shape from the page only, and draws nothing: parts of the
icons of the Azure stencils went missing, the head of a user, the arrow of a cloud. A VSDX holds that
geometry in the XML of the master.

Each such shape gets a path built from the rows of the geometry of its master, at the size of the shape, and
turned, flipped and moved onto the page through the shape and the groups around it. It fills and strokes
with the cells of the shape, its master and its styles, with its gradient where it has one. It goes after
the last path of the shapes before it, so it keeps its place in the order of the drawing. A shape that
libvisio drew, one on a hidden layer and one whose ID another shape shares keep what libvisio drew.
"""

from __future__ import annotations

import bisect
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from . import gradients
from .hidden import MASTER_CLASS, SVG_NS, drawn_paths
from .package import VISIO, Package, Placed, cell, number, page_shapes, read
from .raw import Call, properties

PT_PER_INCH = 72.0
ARC_SEGMENTS = 24  # line segments of a full turn of an arc
NURBS_SEGMENTS = 8  # line segments of each span of a NURBS
# The points and the degree of one NURBS: a hostile drawing would cost the square of either, in the process of WeasyPrint
MAX_NURBS_POINTS = 1000
MAX_DEGREE = 9
MAX_SEGMENTS = 100_000  # line segments of all shapes of a page: a drawing of huge arcs stays bounded
INHERITED = "inherited"  # an attribute that marks a cell of a merged section that comes from the master
# The dashes of each LinePattern, in line widths, as the SVG of Visio draws them. Each family of seven shares
# its gap: the bench measured 2 to 5, 9 to 11, 13, 14, 16 and 20, and the others follow their family.
DASHES = {
    "2": (7, 5), "3": (0, 5), "4": (7, 5, 0, 5), "5": (7, 5, 0, 5, 0, 5), "6": (7, 5, 7, 5, 0, 5), "7": (21, 5, 7, 5), "8": (21, 5, 7, 5, 7, 5),
    "9": (3, 3), "10": (0, 3), "11": (3, 3, 0, 3), "12": (3, 3, 0, 3, 0, 3), "13": (3, 3, 3, 3, 0, 3), "14": (9, 3, 3, 3), "15": (9, 3, 3, 3, 3, 3),
    "16": (15, 9), "17": (0, 9), "18": (15, 9, 0, 9), "19": (15, 9, 0, 9, 0, 9), "20": (15, 9, 15, 9, 0, 9), "21": (45, 9, 15, 9), "22": (45, 9, 15, 9, 15, 9),
    "23": (1, 2),
}  # fmt: skip
NUMBER = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
# A NURBS or POLYLINE formula of numbers only: one that refers to other cells is not read
LITERAL = re.compile(r"\s*(?:NURBS|POLYLINE)\(([-+0-9.eE,\s]*)\)\s*")

# A point in inches, y up; a command of a path: M, L, C or Z with its points
Point = tuple[float, float]
Command = tuple[str, tuple[Point, ...]]


@dataclass(frozen=True)
class Affine:
    """The map (x, y) to (a x + c y + e, b x + d y + f)."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def apply(self, point: Point) -> Point:
        x, y = point
        return self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f

    def then(self, outer: Affine) -> Affine:
        """This map, then outer."""
        return Affine(
            outer.a * self.a + outer.c * self.b,
            outer.b * self.a + outer.d * self.b,
            outer.a * self.c + outer.c * self.d,
            outer.b * self.c + outer.d * self.d,
            outer.a * self.e + outer.c * self.f + outer.e,
            outer.b * self.e + outer.d * self.f + outer.f,
        )


@dataclass(frozen=True)
class Missing:
    """A shape libvisio leaves out: its outline on the page, in points, and its style."""

    shape_id: str
    data: str
    style: str
    gradient: gradients.Gradient | None


def _chain(placed: Placed) -> list[ET.Element]:
    return [placed.shape] if placed.master_shape is None or placed.master_shape is placed.shape else [placed.shape, placed.master_shape]


def _value(chain: list[ET.Element], name: str, default: float = 0.0) -> float:
    return number(cell(chain, name), default)


def _placement(chain: list[ET.Element]) -> Affine:
    """The map from the coordinates of a shape to those of its group or page: around its pin, flipped, turned and moved."""
    angle = math.remainder(_value(chain, "Angle"), math.tau)
    flip_x = -1.0 if cell(chain, "FlipX") == "1" else 1.0
    flip_y = -1.0 if cell(chain, "FlipY") == "1" else 1.0
    cos, sin = math.cos(angle), math.sin(angle)
    to_pin = Affine(e=-_value(chain, "LocPinX"), f=-_value(chain, "LocPinY"))
    turn = Affine(cos * flip_x, sin * flip_x, -sin * flip_y, cos * flip_y, _value(chain, "PinX"), _value(chain, "PinY"))
    return to_pin.then(turn)


def _on_page(placed: Placed) -> Affine:
    """The map from the coordinates of a shape to those of the page, through the groups around it."""
    form = _placement(_chain(placed))
    for group in reversed(placed.groups):
        form = form.then(_placement(_chain(group)))
    return form


def _rows(section: ET.Element) -> Iterator[tuple[str, dict[str, str], dict[str, str], set[str]]]:
    """The rows of a geometry section in order: their type, the values and the formulas of their cells, and the cells from the master."""
    rows = [row for row in section.findall(f"{VISIO}Row") if row.get("Del") != "1"]
    rows.sort(key=lambda row: int(row.get("IX", "0")) if row.get("IX", "0").isdigit() else 0)
    for row in rows:
        cells = row.findall(f"{VISIO}Cell")
        values = {element.get("N", ""): element.get("V", "") for element in cells}
        yield row.get("T", ""), values, {element.get("N", ""): element.get("F", "") for element in cells}, {element.get("N", "") for element in cells if element.get(INHERITED)}


class _Outline:
    """The commands of the geometry of a shape, in its own coordinates, at its size."""

    def __init__(self, width: float, height: float, scale_x: float, scale_y: float) -> None:
        self.width, self.height = width, height
        # The rows of a master hold their values at the size of the master
        self.scale_x, self.scale_y = scale_x, scale_y
        self.commands: list[Command] = []
        self.current: Point = (0.0, 0.0)
        # The cells of the current row that come from the master
        self.inherited: set[str] = set()

    def absolute(self, values: dict[str, str], x: str = "X", y: str = "Y") -> Point:
        return number(values.get(x), 0.0) * self.scale(x, self.scale_x), number(values.get(y), 0.0) * self.scale(y, self.scale_y)

    def scale(self, name: str, factor: float) -> float:
        """The factor for a cell of the master, which holds a value at the size of the master; 1 for a cell of the shape."""
        return factor if name in self.inherited else 1.0

    def relative(self, values: dict[str, str], x: str = "X", y: str = "Y") -> Point:
        return number(values.get(x), 0.0) * self.width, number(values.get(y), 0.0) * self.height

    def move(self, point: Point) -> None:
        self.commands.append(("M", (point,)))
        self.current = point

    def line(self, point: Point) -> None:
        self.commands.append(("L", (point,)))
        self.current = point

    def curve(self, first: Point, second: Point, end: Point) -> None:
        self.commands.append(("C", (first, second, end)))
        self.current = end

    def lines(self, points: list[Point]) -> None:
        for point in points:
            self.line(point)

    def row(self, kind: str, values: dict[str, str], formulas: dict[str, str], inherited: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        """Add the commands of one row."""
        self.inherited = set(inherited)
        relative = kind.startswith("Rel")
        place = self.relative if relative else self.absolute
        if kind in ("MoveTo", "RelMoveTo"):
            self.move(place(values))
        elif kind in ("LineTo", "RelLineTo"):
            self.line(place(values))
        elif kind == "RelCubBezTo":
            self.curve(place(values, "A", "B"), place(values, "C", "D"), place(values))
        elif kind == "RelQuadBezTo":
            # A quadratic curve as the cubic of the same shape
            control, end = place(values, "A", "B"), place(values)
            start = self.current
            self.curve(_toward(start, control, 2 / 3), _toward(end, control, 2 / 3), end)
        elif kind in ("EllipticalArcTo", "RelEllipticalArcTo"):
            ratio = number(values.get("D"), 1.0)
            self.lines(_elliptical_arc(self.current, place(values, "A", "B"), place(values), number(values.get("C"), 0.0), ratio))
        elif kind == "ArcTo":
            self.lines(_arc(self.current, place(values), number(values.get("A"), 0.0) * self.scale("A", self.scale_y)))
        elif kind == "Ellipse":
            self.ellipse(place(values), place(values, "A", "B"), place(values, "C", "D"))
        elif kind == "NURBSTo":
            self.lines(self.nurbs(values, formulas))
        elif kind == "PolylineTo":
            self.lines([point for point, _ in self.listed(formulas.get("A", ""), 2, 0, "A")] + [place(values)])

    def ellipse(self, center: Point, major: Point, minor: Point) -> None:
        """An ellipse through the ends of its axes, closed."""
        u = (major[0] - center[0], major[1] - center[1])
        v = (minor[0] - center[0], minor[1] - center[1])
        points = [(center[0] + u[0] * math.cos(t) + v[0] * math.sin(t), center[1] + u[1] * math.cos(t) + v[1] * math.sin(t)) for t in _steps(math.tau)]
        self.move(points[0])
        self.lines(points[1:])
        self.commands.append(("Z", ()))

    def listed(self, formula: str, start: int, extra: int, name: str) -> list[tuple[Point, list[float]]]:
        """The points of a POLYLINE or NURBS formula, each with the numbers after it.

        The types at start - 2 and start - 1 say whether x and y are relative to the size (0) or absolute (1).
        """
        numbers = _numbers(formula)
        if len(numbers) < start:
            return []
        x_type, y_type = numbers[start - 2 : start]
        result = []
        step = 2 + extra
        for index in range(start, len(numbers) - step + 1, step):
            x, y = numbers[index : index + 2]
            point = (x * (self.scale(name, self.scale_x) if x_type else self.width), y * (self.scale(name, self.scale_y) if y_type else self.height))
            result.append((point, numbers[index + 2 : index + step]))
        return result

    def nurbs(self, values: dict[str, str], formulas: dict[str, str]) -> list[Point]:
        """The points of a NURBS, as lines: NURBS(last knot, degree, x type, y type, x, y, knot, weight, ...) in E."""
        formula = formulas.get("E", "")
        numbers = _numbers(formula)
        end = self.absolute(values)
        if len(numbers) < 4:
            return [end]
        listed = self.listed(formula, 4, 2, "E")
        points = [self.current] + [point for point, _ in listed] + [end]
        knots = [number(values.get("C"), 0.0)] + [extra[0] for _, extra in listed] + [number(values.get("A"), 0.0), numbers[0]]
        weights = [number(values.get("D"), 1.0)] + [extra[1] for _, extra in listed] + [number(values.get("B"), 1.0)]
        return _nurbs(points, knots, weights, max(int(numbers[1]), 1))


def _numbers(formula: str) -> list[float]:
    """The numbers of a NURBS or POLYLINE formula; none for a formula that refers to other cells."""
    literal = LITERAL.fullmatch(formula)
    numbers = [float(match) for match in NUMBER.findall(literal.group(1))] if literal else []
    return numbers if all(math.isfinite(value) for value in numbers) else []


def _toward(start: Point, end: Point, share: float) -> Point:
    return start[0] + (end[0] - start[0]) * share, start[1] + (end[1] - start[1]) * share


def _steps(span: float) -> list[float]:
    count = max(2, math.ceil(abs(span) / math.tau * ARC_SEGMENTS))
    return [span * index / count for index in range(count + 1)]


def _circle(first: Point, second: Point, third: Point) -> tuple[Point, float] | None:
    """The center and radius of the circle through three points; None when they lie on one line."""
    (ax, ay), (bx, by), (cx, cy) = first, second, third
    determinant = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(determinant) < 1e-12:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    center = ((a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / determinant, (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / determinant)
    return center, math.hypot(ax - center[0], ay - center[1])


def _through(start: Point, middle: Point, end: Point) -> list[Point]:
    """The arc of a circle from start through middle to end, as points after start; a line where they lie on one."""
    circle = _circle(start, middle, end)
    if circle is None:
        return [end]
    (x, y), radius = circle
    begin = math.atan2(start[1] - y, start[0] - x)
    through = (math.atan2(middle[1] - y, middle[0] - x) - begin) % math.tau
    span = (math.atan2(end[1] - y, end[0] - x) - begin) % math.tau
    # The way round that passes the middle point
    if through > span:
        span -= math.tau
    return [(x + radius * math.cos(begin + t), y + radius * math.sin(begin + t)) for t in _steps(span)[1:-1]] + [end]


def _arc(start: Point, end: Point, bow: float) -> list[Point]:
    """An ArcTo: the arc whose middle stands bow from the middle of the chord, to the right of it going from start to end, y up."""
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length == 0 or bow == 0:
        return [end]
    normal = ((end[1] - start[1]) / length, -(end[0] - start[0]) / length)
    middle = ((start[0] + end[0]) / 2 + normal[0] * bow, (start[1] + end[1]) / 2 + normal[1] * bow)
    return _through(start, middle, end)


def _elliptical_arc(start: Point, control: Point, end: Point, angle: float, ratio: float) -> list[Point]:
    """An EllipticalArcTo: through control, on an ellipse whose axis at angle is ratio times the other one."""
    if ratio <= 0:
        return [end]
    cos, sin = math.cos(angle), math.sin(angle)

    def squeezed(point: Point) -> Point:
        # Turned so that the axis at angle runs along x, then shrunk along it: the ellipse becomes a circle
        return (point[0] * cos + point[1] * sin) / ratio, -point[0] * sin + point[1] * cos

    def stretched(point: Point) -> Point:
        x, y = point[0] * ratio, point[1]
        return x * cos - y * sin, x * sin + y * cos

    arc = _through(squeezed(start), squeezed(control), squeezed(end))
    return [stretched(point) for point in arc[:-1]] + [end]


def _nurbs(points: list[Point], knots: list[float], weights: list[float], degree: int) -> list[Point]:
    """A rational B-spline as points after its first, the knot vector filled at its end as libvisio does."""
    count = len(points)
    if count > MAX_NURBS_POINTS:
        return points[-1:]
    degree = min(degree, MAX_DEGREE, count - 1)
    knots = knots[: count + degree + 1]
    while len(knots) < count + degree + 1:
        knots.append(knots[-1])
    weights = (weights + [1.0] * count)[:count]
    low, high = knots[degree], knots[count]
    if high <= low:
        return points[1:]
    samples = []
    spans = max(count - degree, 1) * NURBS_SEGMENTS
    for index in range(1, spans):
        samples.append(_de_boor(low + (high - low) * index / spans, points, knots, weights, degree))
    return samples + [points[-1]]


def _de_boor(t: float, points: list[Point], knots: list[float], weights: list[float], degree: int) -> Point:
    """The point of a rational B-spline at t."""
    # The last knot at or before t, among those a span of the curve starts at
    span = min(max(bisect.bisect_right(knots, t, degree, len(points)) - 1, degree), len(points) - 1)
    # Homogeneous points: x w, y w, w
    work = [(points[i][0] * weights[i], points[i][1] * weights[i], weights[i]) for i in range(span - degree, span + 1)]
    for level in range(1, degree + 1):
        for j in range(degree, level - 1, -1):
            i = span - degree + j
            denominator = knots[i + degree - level + 1] - knots[i]
            alpha = (t - knots[i]) / denominator if denominator else 0.0
            work[j] = tuple(alpha * work[j][k] + (1 - alpha) * work[j - 1][k] for k in range(3))  # type: ignore[assignment]
    x, y, w = work[degree]
    return (x / w, y / w) if w else points[-1]


def _merged(own: ET.Element | None, inherited: ET.Element | None) -> ET.Element:
    """A section of the shape over the same section of its master: its cells and rows by index, each cell from the shape where it sets it."""
    merged = ET.Element(f"{VISIO}Section")
    rows: dict[str, ET.Element] = {}
    for source in (inherited, own):
        if source is None:
            continue
        for element in source.findall(f"{VISIO}Cell"):
            _set(merged, element, source is inherited)
        for row in source.findall(f"{VISIO}Row"):
            _merge_row(rows, row, source is inherited)
    merged.extend(rows.values())
    return merged


def _merge_row(rows: dict[str, ET.Element], row: ET.Element, inherited: bool) -> None:
    """Set a row over the row of its index, or delete it."""
    index = row.get("IX", "")
    if row.get("Del") == "1":
        rows.pop(index, None)
        return
    target = rows.setdefault(index, ET.Element(f"{VISIO}Row", {"IX": index}))
    if row.get("T"):
        target.set("T", row.get("T", ""))
    for element in row.findall(f"{VISIO}Cell"):
        _set(target, element, inherited)


def _set(target: ET.Element, element: ET.Element, inherited: bool) -> None:
    """Set a copy of a cell on target, over the cell of that name it has, marked where it comes from the master."""
    for existing in target.findall(f"{VISIO}Cell"):
        if existing.get("N") == element.get("N"):
            target.remove(existing)
    copied = ET.SubElement(target, element.tag, dict(element.attrib))
    if inherited:
        copied.set(INHERITED, "1")


def _sections(placed: Placed) -> tuple[list[ET.Element], ET.Element | None]:
    """The geometry sections of a shape that show, and its master shape where it inherits from one, None for none."""
    master = placed.master_shape if placed.master_shape is not placed.shape else None

    def by_index(source: ET.Element | None) -> dict[str, ET.Element]:
        return {section.get("IX", ""): section for section in source.findall(f"{VISIO}Section[@N='Geometry']")} if source is not None else {}

    own, inherited = by_index(placed.shape), by_index(master)
    sections = []
    for index in sorted(own.keys() | inherited.keys(), key=lambda index: int(index) if index.isdigit() else 0):
        section = own.get(index)
        if section is not None and section.get("Del") == "1":
            continue
        merged = _merged(section, inherited.get(index))
        if cell([merged], "NoShow") != "1":
            sections.append(merged)
    return sections, master


def outline(placed: Placed, sections: list[ET.Element], master: ET.Element | None) -> list[Command]:
    """The commands of the geometry sections of a shape, on the page, in inches."""
    chain = _chain(placed)
    width, height = _value(chain, "Width"), _value(chain, "Height")
    master_width = _value([master], "Width") if master is not None else 0.0
    master_height = _value([master], "Height") if master is not None else 0.0
    shape = _Outline(width, height, width / master_width if master_width else 1.0, height / master_height if master_height else 1.0)
    for section in sections:
        for kind, values, formulas, inherited in _rows(section):
            shape.row(kind, values, formulas, inherited)
    form = _on_page(placed)
    return [(name, tuple(form.apply(point) for point in points)) for name, points in shape.commands]


def path_data(commands: list[Command], page_height: float) -> str:
    """SVG path data in points, y down, of commands in inches, y up."""
    parts = []
    for name, points in commands:
        coordinates = " ".join(f"{x * PT_PER_INCH:.4f},{(page_height - y) * PT_PER_INCH:.4f}" for x, y in points)
        parts.append(f"{name}{coordinates}")
    return " ".join(parts)


def _closed(commands: list[Command]) -> bool:
    """Whether a path ends where it starts, which Visio fills."""
    points = [point for _, points in commands for point in points]
    return bool(points) and (commands[-1][0] == "Z" or math.dist(points[0], points[-1]) < 1e-6)


def _paint(chain: list[ET.Element], color: str, pattern: str, transparency: str, colors: dict[str, str]) -> tuple[str, float] | None:
    """A color and its opacity from the cells of a fill or a line; None for none or a color of the theme."""
    if cell(chain, pattern) == "0":
        return None
    value = gradients.color_of(cell(chain, color), colors)
    if value is None:
        return None
    return value, 1.0 - min(max(number(cell(chain, transparency), 0.0), 0.0), 1.0)


class _Painter:
    """The paths of the shapes libvisio leaves out, styled from their cells."""

    def __init__(self, package: Package, page_height: float) -> None:
        self.styles = package.styles()
        self.colors = package.colors()
        self.page_height = page_height
        self.segments = 0

    def paths(self, placed: Placed) -> list[tuple[ET.Element, gradients.Gradient | None]]:
        """The fill path, then the line path, of a shape, each with its gradient."""
        sections, master = _sections(placed)
        fill_chain = gradients.chain_of(placed.shape, placed.master_shape, self.styles)
        line_chain = gradients.chain_of(placed.shape, placed.master_shape, self.styles, "LineStyle")
        gradient = gradients.gradient_of(fill_chain, self.colors, gradients.turn_of(placed)) if cell(fill_chain, "FillPattern") != "0" else None
        fill = _paint(fill_chain, "FillForegnd", "FillPattern", "FillForegndTrans", self.colors)
        line = _paint(line_chain, "LineColor", "LinePattern", "LineColorTrans", self.colors)
        filled, lined = _split(placed, sections, master)
        result = []
        if filled and (fill is not None or gradient is not None):
            style = f"fill-rule: evenodd; fill: {fill[0] if fill else 'none'}; fill-opacity: {fill[1] if fill else 1:g}; stroke: none;"
            result.append((self.path(filled, style), gradient))
        if lined and line is not None:
            result.append((self.path(lined, _line_style(line_chain, line)), None))
        return result

    def path(self, commands: list[Command], style: str) -> ET.Element:
        self.segments += len(commands)
        return ET.Element(f"{{{SVG_NS}}}path", {"class": MASTER_CLASS, "d": path_data(commands, self.page_height), "style": style})


def _split(placed: Placed, sections: list[ET.Element], master: ET.Element | None) -> tuple[list[Command], list[Command]]:
    """The commands of the sections that fill, closed ones without NoFill, and of those that stroke, without NoLine."""
    filled: list[Command] = []
    lined: list[Command] = []
    for section in sections:
        commands = outline(placed, [section], master)
        if cell([section], "NoFill") != "1" and _closed(commands):
            filled.extend(commands)
        if cell([section], "NoLine") != "1":
            lined.extend(commands)
    return filled, lined


def _line_style(chain: list[ET.Element], line: tuple[str, float]) -> str:
    """The style of a line: its color, opacity, width and dashes."""
    width = number(cell(chain, "LineWeight"), 0.01) * PT_PER_INCH
    dashes = DASHES.get(cell(chain, "LinePattern") or "")
    # A dash of no length is a dot: the round cap draws it
    dasharray = f" stroke-dasharray: {', '.join(f'{dash * width:.4f}' for dash in dashes)};" if dashes else ""
    return f"fill: none; stroke: {line[0]}; stroke-opacity: {line[1]:g}; stroke-width: {width:.4f}; stroke-linecap: round; stroke-linejoin: round;{dasharray}"


def _candidates(package: Package, drawn: set[str], hidden: set[str]) -> Iterator[tuple[Placed, bool]]:
    """Each shape of the page in order, with whether it is one libvisio leaves out and this module draws."""
    layers = package.hidden_layers()
    ambiguous = package.background_ids()
    shapes = list(page_shapes(package))
    seen: set[str] = set()
    for placed in shapes:
        shape_id = placed.shape.get("ID", "")
        if shape_id in seen:
            ambiguous.add(shape_id)
        seen.add(shape_id)
    for placed in shapes:
        shape_id = placed.shape.get("ID", "")
        master = placed.master_shape
        missing = (
            master is not None
            and master is not placed.shape
            and shape_id not in drawn
            and shape_id not in ambiguous
            and placed.shape.find(f"{VISIO}Section[@N='Geometry']") is None
            and master.find(f"{VISIO}Section[@N='Geometry']") is not None
            # A group that libvisio hides hides the shape too, and so does a hidden layer
            and not any(group.shape.get("ID", "") in hidden for group in placed.groups)
            and not (set((cell(_chain(placed), "LayerMember") or "").split(";")) & layers)
        )
        yield placed, missing


def add_missing(page: ET.Element, calls: list[Call], document: bytes) -> int | None:
    """Draw the shapes of master groups that libvisio leaves out; their count, None when the page does not pair with the calls.

    Each goes after the last path of the shapes before it. Their paths carry MASTER_CLASS, so the steps that pair the
    paths of the page with the drawPath calls pass them by.
    """
    shapes = gradients.path_shapes(calls)
    paths = drawn_paths(page)
    if len(paths) != len(shapes):
        return None
    last: dict[str, tuple[ET.Element, ET.Element]] = {}
    for (path, parent), shape_id in zip(paths, shapes, strict=True):
        last[shape_id] = (path, parent)
    hidden = {shape_id for shape_id, (name, argument) in zip(shapes, [call for call in calls if call[0] == "drawPath" and "svg:d:" in call[1]], strict=True) if properties(argument).get("draw:display") == "none"}
    viewbox = (page.get("viewBox") or "").split()
    page_height = float(viewbox[3]) / PT_PER_INCH if len(viewbox) == 4 else 0.0
    added = read(document, lambda package: _add(page, package, last, hidden, page_height))
    return added or 0


def _add(page: ET.Element, package: Package, last: dict[str, tuple[ET.Element, ET.Element]], hidden: set[str], page_height: float) -> int:
    painter = _Painter(package, page_height)
    # The path of the last shape drawn so far, and the parent and index after which the next path goes
    drawn: tuple[ET.Element, ET.Element] | None = None
    position: tuple[ET.Element, int] | None = None
    defs = None
    added = 0
    for placed, missing in _candidates(package, set(last), hidden):
        shape_id = placed.shape.get("ID", "")
        if shape_id in last:
            drawn, position = last[shape_id], None
        if not missing or painter.segments > MAX_SEGMENTS:
            continue
        for path, gradient in painter.paths(placed):
            if gradient is not None:
                had = defs is not None
                defs = _gradient(page, defs, path, gradient)
                # New definitions go first in the page, before the place of the next path
                if not had and position is not None and position[0] is page:
                    position = (page, position[1] + 1)
            position = _insert(page, drawn, position, path)
            added += 1
    return added


def _gradient(page: ET.Element, defs: ET.Element | None, path: ET.Element, gradient: gradients.Gradient) -> ET.Element:
    """Fill a path with a gradient, defined in the definitions this module adds, which it returns."""
    if defs is None:
        defs = ET.Element(f"{{{SVG_NS}}}defs")
        page.insert(0, defs)
    identifier = f"weasyvsdx-master-gradient-{len(defs)}"
    defs.append(gradients.gradient_element(identifier, gradient))
    path.set("style", f"{path.get('style')} fill: url(#{identifier});")
    return defs


def _insert(page: ET.Element, drawn: tuple[ET.Element, ET.Element] | None, position: tuple[ET.Element, int] | None, path: ET.Element) -> tuple[ET.Element, int]:
    """Insert a path where the last one went, else after the path drawn last, else before all paths of the page after its
    definitions; the place of the path.

    The path drawn last is looked for once for each run of paths after it: a search for each would cost the square.
    """
    if position is None:
        position = _after(page, drawn)
    parent, index = position
    parent.insert(index + 1, path)
    return parent, index + 1


def _after(page: ET.Element, drawn: tuple[ET.Element, ET.Element] | None) -> tuple[ET.Element, int]:
    """The parent and index of the path drawn last, or of the last definitions of the page: the next path goes after it."""
    if drawn is None:
        return page, sum(1 for child in page if child.tag == f"{{{SVG_NS}}}defs") - 1
    return drawn[1], list(drawn[1]).index(drawn[0])
