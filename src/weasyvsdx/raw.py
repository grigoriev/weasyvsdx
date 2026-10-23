"""The output of vsd2raw: the calls libvisio makes for a drawing, one per line, with their properties.

vsd2xhtml writes SVG from the same calls, through the generic SVG generator of librevenge, which drops
part of what they carry. text.py and markers.py take that part from here.
"""

from __future__ import annotations

import re

LENGTH = re.compile(r"^(-?[0-9.]+)(in|pt)?$")
# The key of a property, in the namespaces of ODF and librevenge: fo:font-size, librevenge:path-action
KEY = re.compile(r"^[a-z]+:[A-Za-z0-9-]+: ")
PT_PER_INCH = 72.0

Properties = dict[str, str]
Call = tuple[str, str]


def parse_call(line: str) -> Call | None:
    """A line of vsd2raw as its call: the name, then the properties or the text in parentheses. None for another line.

    Read by hand, not by a regular expression: a line can hold the base64 of a large image, where the
    backtracking of a pattern around ".*" would cost more than linear time.
    """
    text = line.strip()
    end = 0
    while end < len(text) and text[end].isascii() and text[end].isalpha():
        end += 1
    if end == 0:
        return None
    rest = text[end:].lstrip()
    if not rest:
        return text[:end], ""
    if rest[0] == "(" and rest[-1] == ")":
        return text[:end], rest[1:-1]
    return None


def first_page(raw: str) -> list[Call]:
    """The calls of the first page, each its name and its argument."""
    calls: list[Call] = []
    pages = 0
    # Lines end at a newline only: splitlines() also breaks at the U+2028 that Visio puts inside a text
    for line in raw.split("\n"):
        call = parse_call(line)
        if call is None:
            continue
        if call[0] == "startPage":
            pages += 1
            if pages > 1:
                break
        if pages == 1:
            calls.append(call)
    return calls


def properties(text: str) -> Properties:
    """The properties of a call, ``key: value, key: value``. A value may hold a list in parentheses."""
    result: Properties = {}
    depth, start = 0, 0
    parts = []
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0 and text.startswith(", ", index):
            parts.append(text[start:index])
            start = index + 2
    parts.append(text[start:])
    key = None
    for part in parts:
        if KEY.match(part):
            key, _, value = part.partition(": ")
            result[key] = value
        elif key is not None:
            # A comma inside a value, as in a title or a font name
            result[key] += ", " + part
    return result


def points(value: str | None, default: float = 0.0) -> float:
    """A length in points, the user unit of the SVG of vsd2xhtml. A number without a unit is in inches."""
    if not value:
        return default
    match = LENGTH.match(value.strip())
    if match is None:
        return default
    number = float(match.group(1))
    return number if match.group(2) == "pt" else number * PT_PER_INCH


def percent(value: str | None, default: float) -> float:
    """A percentage as a ratio."""
    if not value or not value.endswith("%"):
        return default
    try:
        return float(value[:-1]) / 100
    except ValueError:
        return default
