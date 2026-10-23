"""Shapes that Visio does not show."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from weasyvsdx.hidden import SVG_NS, remove_hidden
from weasyvsdx.raw import first_page

PATH = "drawPath (svg:d: ((librevenge:path-action: M, svg:x: 0in, svg:y: 0in)))"
HIDDEN = "drawPath (draw:display: none, svg:d: ((librevenge:path-action: M, svg:x: 1in, svg:y: 1in)))"


def calls(*lines: str) -> list[tuple[str, str]]:
    return first_page("startPage()\n" + "\n".join(lines) + "\nendPage\n")


def test_the_path_of_a_hidden_call_goes() -> None:
    page = ET.fromstring(f'<svg xmlns="{SVG_NS}"><defs><marker><path d="m0 0"/></marker></defs><path d="a"/><g><path d="b"/></g><path d="c"/></svg>')
    assert remove_hidden(page, calls(PATH, HIDDEN, "drawPath (draw:id: 7)", PATH))
    assert [path.get("d") for path in page.iter(f"{{{SVG_NS}}}path")] == ["m0 0", "a", "c"]


def test_other_counts_leave_the_paths() -> None:
    page = ET.fromstring(f'<svg xmlns="{SVG_NS}"><path d="a"/></svg>')
    assert not remove_hidden(page, calls(HIDDEN, PATH))
    assert len(list(page.iter(f"{{{SVG_NS}}}path"))) == 1
