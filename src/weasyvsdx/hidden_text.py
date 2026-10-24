"""Text that Visio hides.

A shape hides its text with the HideText cell, and the icons of the Azure stencils all do: their name stays
out of the drawing. A shape that clears the text of its master hides that text too. libvisio reads neither,
and writes the name of each icon under it. A VSDX holds both in the XML of its first page and its masters.

The shapes of the XML and the text objects of vsd2raw come in nearly one order, but not quite: libvisio leaves
out some text of a master and writes some it should not. The two lists of texts are aligned as sequences, and
a text object goes only where it matches a shape of the same text that hides it. A VSD, or a VSDX that does
not read, keeps all its text.
"""

from __future__ import annotations

import difflib
import re
from xml.etree import ElementTree as ET

from .package import VISIO, Package, page_shapes, read

MAX_ALIGNMENT = 1_000_000  # shapes times texts: the largest drawing of the corpus is 196 by 165
SPACE = re.compile(r"\s+")


def normalized(text: str) -> str:
    """The text without its white space: libvisio and the XML break and pad text differently."""
    return SPACE.sub("", text)


def _text(shape: ET.Element | None) -> str | None:
    """The text of a shape, None when it has no text element."""
    element = shape.find(f"{VISIO}Text") if shape is not None else None
    return None if element is None else "".join(element.itertext())


def _hide(shape: ET.Element, master: ET.Element | None) -> bool:
    """Whether the HideText cell of the shape, else of its master, is set."""
    for source in (shape, master):
        if source is None:
            continue
        for cell in source.findall(f"{VISIO}Cell"):
            if cell.get("N") == "HideText":
                return cell.get("V") == "1"
    return False


def _hidden_text(shape: ET.Element, master_shape: ET.Element | None) -> tuple[str, bool] | None:
    """The text of a shape and whether Visio hides it; None for a shape without text."""
    own = _text(shape)
    inherited = _text(master_shape) if master_shape is not shape else None
    text = own if own and normalized(own) else inherited
    if text is None or not normalized(text):
        return None
    # An empty text of its own clears the text of the master, which libvisio writes anyway
    cleared = own is not None and not normalized(own)
    return normalized(text), cleared or _hide(shape, master_shape)


def _texts(package: Package) -> list[tuple[str, bool]]:
    return [text for placed in page_shapes(package) if (text := _hidden_text(placed.shape, placed.master_shape)) is not None]


def shape_texts(document: bytes) -> list[tuple[str, bool]] | None:
    """The texts of the shapes of the first page of a VSDX, each with whether Visio hides it; None for another drawing."""
    return read(document, _texts)


def hidden_indexes(shapes: list[tuple[str, bool]], texts: list[str]) -> frozenset[int]:
    """The indexes of the texts that match, in an alignment of both lists, a shape that hides the same text.

    The alignment costs up to the product of both lengths where many texts are equal, in the process of the
    caller: past MAX_ALIGNMENT all text stays. Lists that agree pair by position without it.
    """
    if not any(hidden for _, hidden in shapes):
        return frozenset()
    normalized_texts = [normalized(text) for text in texts]
    if [text for text, _ in shapes] == normalized_texts:
        return frozenset(index for index, (_, hidden) in enumerate(shapes) if hidden)
    if len(shapes) * len(texts) > MAX_ALIGNMENT:
        return frozenset()
    matcher = difflib.SequenceMatcher(None, [text for text, _ in shapes], normalized_texts, autojunk=False)
    return frozenset(index + offset for start, index, size in matcher.get_matching_blocks() for offset in range(size) if shapes[start + offset][1])
