"""Path data of SVG as tokens: command letters and numbers, each with its place in the text.

Read by hand, not by a regular expression: a pattern for the numbers of SVG (".5.5" is two numbers, a
second dot starts the next one) backtracks on long runs of digits.
"""

from __future__ import annotations

Token = tuple[str, int, int]


def _digits(data: str, index: int) -> int:
    while index < len(data) and data[index].isdigit():
        index += 1
    return index


def _mantissa(data: str, index: int) -> int:
    """The end of the digits, one dot and digits at index; index where there are none."""
    integer_end = _digits(data, index)
    if integer_end < len(data) and data[integer_end] == ".":
        fraction_end = _digits(data, integer_end + 1)
        # A dot alone is no number, "1." and ".5" are
        if fraction_end > integer_end + 1 or integer_end > index:
            return fraction_end
    return integer_end


def _exponent(data: str, end: int) -> int:
    """The end of the exponent at end, or end where there is none."""
    if end >= len(data) or data[end] not in "eE":
        return end
    digits = end + 1 + (1 if end + 1 < len(data) and data[end + 1] in "+-" else 0)
    digits_end = _digits(data, digits)
    return digits_end if digits_end > digits else end


def _number(data: str, start: int) -> int:
    """The end of the number at start: a sign, digits, one dot and digits, an exponent; start where there is none."""
    index = start + 1 if data[start] in "+-" else start
    end = _mantissa(data, index)
    return start if end == index else _exponent(data, end)


def tokenize(data: str) -> list[Token]:
    """The command letters and numbers of path data, each with its start and end; anything else is skipped."""
    tokens: list[Token] = []
    index = 0
    while index < len(data):
        char = data[index]
        if char.isascii() and char.isalpha():
            tokens.append((char, index, index + 1))
            index += 1
            continue
        end = _number(data, index) if char.isdigit() or char in "+-." else index
        if end > index:
            tokens.append((data[index:end], index, end))
            index = end
        else:
            index += 1
    return tokens
