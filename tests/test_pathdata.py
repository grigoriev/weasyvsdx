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
        ("", []),
    ],
)
def test_tokens(data: str, tokens: list[str]) -> None:
    assert [token for token, _, _ in tokenize(data)] == tokens


def test_each_token_keeps_its_place() -> None:
    data = "M1,2 L30,4"
    assert [(token, data[start:end]) for token, start, end in tokenize(data)] == [(token, token) for token in ("M", "1", "2", "L", "30", "4")]
