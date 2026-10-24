"""Path data of SVG as tokens."""

from __future__ import annotations

import pytest

from weasyvsdx.pathdata import tokenize


@pytest.mark.parametrize(
    ("data", "tokens"),
    [
        ("M0 0L.5.5", ["M", "0", "0", "L", ".5", ".5"]),
        ("M1.2.3 2", ["M", "1.2", ".3", "2"]),
        ("m10 0-10 20h20z", ["m", "10", "0", "-10", "20", "h", "20", "z"]),
        ("C1e2,-2.5E-1 +3. 4", ["C", "1e2", "-2.5E-1", "+3.", "4"]),
        # A sign or a dot alone, and an exponent without digits, are no numbers
        ("L - . 5e", ["L", "5", "e"]),
        # The flags of an arc are one digit each, and may touch the numbers after them
        ("A10 10 0 0120 20a1 1 0 11.5.5 1 1 0 002 2", ["A", "10", "10", "0", "0", "1", "20", "20", "a", "1", "1", "0", "1", "1", ".5", ".5", "1", "1", "0", "0", "0", "2", "2"]),
        ("", []),
    ],
)
def test_tokens(data: str, tokens: list[str]) -> None:
    assert [token for token, _, _ in tokenize(data)] == tokens


def test_each_token_keeps_its_place() -> None:
    data = "M1,2 L30,4"
    assert [(token, data[start:end]) for token, start, end in tokenize(data)] == [(token, token) for token in ("M", "1", "2", "L", "30", "4")]
