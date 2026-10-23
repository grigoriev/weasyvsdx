"""The conversion of a drawing into the SVG of its first page, and the limits of the tools."""

from __future__ import annotations

import base64
import logging
import stat
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import helpers
import pytest

from weasyvsdx import convert as convert_module
from weasyvsdx.convert import SVG_NS, Limits, Tools, convert, find_converter, find_tools, first_page, run, serialize
from weasyvsdx.errors import ConversionError

LIMITS = Limits()
XHTML_NS = "http://www.w3.org/1999/xhtml"
PLAIN = Tools(helpers.CONVERTER)


def script(tmp_path: Path, body: str, name: str = "fake-vsd2xhtml") -> str:
    """A fake tool: a shell script with body."""
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def page_xhtml(svg_body: str) -> str:
    return f'<html xmlns="{XHTML_NS}"><body><svg:svg xmlns:svg="{SVG_NS}" xmlns:xlink="http://www.w3.org/1999/xlink" width="1in">{svg_body}</svg:svg></body></html>'


def test_the_tools_of_libvisio_and_emf2svg() -> None:
    assert helpers.TOOLS.converter == helpers.CONVERTER
    assert helpers.TOOLS.raw is not None
    assert helpers.TOOLS.raw.endswith("/vsd2raw")
    assert helpers.TOOLS.emf is not None
    assert find_tools("/nowhere/vsd2xhtml").raw is None


def test_the_first_page_is_a_standalone_svg() -> None:
    svg = convert(helpers.drawing("poi/test.vsdx"), PLAIN, LIMITS)
    root = ET.fromstring(svg)
    assert root.tag == f"{{{SVG_NS}}}svg"
    # No prefix of the XHTML of vsd2xhtml survives
    assert b"svg:" not in svg
    assert root.get("width") == "11.6929in"
    texts = "".join(element.text or "" for element in root.iter(f"{{{SVG_NS}}}tspan"))
    assert "This is a test." in texts


def test_the_text_becomes_html_that_wraps_and_aligns() -> None:
    root = ET.fromstring(convert(helpers.drawing("poi/test.vsdx"), helpers.TOOLS, LIMITS))
    assert root.find(f".//{{{SVG_NS}}}text") is None
    blocks = list(root.iter(f"{{{SVG_NS}}}foreignObject"))
    assert len(blocks) == 3
    paragraphs = [paragraph for block in blocks for paragraph in block.iter(f"{{{XHTML_NS}}}p")]
    assert ["".join(paragraph.itertext()) for paragraph in paragraphs] == ["test", "This is a test.", "Nothing fancy."]
    assert all("text-align:center" in (paragraph.get("style") or "") for paragraph in paragraphs)


def test_the_arrowheads_take_their_own_shape() -> None:
    root = ET.fromstring(convert(helpers.drawing("poi/60973.vsdx"), helpers.TOOLS, LIMITS))
    markers = list(root.iter(f"{{{SVG_NS}}}marker"))
    assert markers
    assert all(marker.get("markerUnits") == "userSpaceOnUse" for marker in markers)
    assert root.find(f".//{{{SVG_NS}}}polyline[@fill='solid']") is None


def test_an_emf_image_becomes_svg(tmp_path: Path) -> None:
    emf = base64.b64encode(helpers.emf_rectangle()).decode()
    element = f'<svg:image width="10" height="6" xlink:href="data:image/emf;base64,{emf}"/>'
    converter = script(tmp_path, "cat <<'EOF'\n" + page_xhtml(element) + "\nEOF")
    root = ET.fromstring(convert(b"drawing", Tools(converter, emf=helpers.TOOLS.emf), LIMITS))
    [image] = root.iter(f"{{{SVG_NS}}}image")
    href = image.get("{http://www.w3.org/1999/xlink}href") or ""
    assert href.startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(href.split(",", 1)[1])
    # emf2svg draws the rectangle as a rect or as a path, by its version
    assert b"<rect" in svg or b"<path" in svg


def test_a_drawing_of_several_pages_gives_its_first() -> None:
    svg = convert(helpers.drawing("poi/60973.vsdx"), helpers.TOOLS, LIMITS)
    root = ET.fromstring(svg)
    assert sum(1 for element in root.iter(f"{{{SVG_NS}}}svg")) == 1


def test_a_binary_vsd_converts_too() -> None:
    svg = convert(helpers.drawing("libvisio/dwg.vsd"), helpers.TOOLS, LIMITS)
    assert ET.fromstring(svg).tag == f"{{{SVG_NS}}}svg"


def test_a_drawing_the_converter_rejects() -> None:
    drawing = helpers.drawing("libvisio/tab-short-prefix.vsdx")
    with pytest.raises(ConversionError, match=r"vsd2xhtml failed with exit code"):
        convert(drawing, helpers.TOOLS, LIMITS)


def test_a_crash_of_the_converter_stays_in_its_process() -> None:
    # libvisio 0.1.7 recurses until the stack runs out on this test of its own, a segmentation fault
    drawing = helpers.drawing("libvisio/recursion-cycle.vsdx")
    with pytest.raises(ConversionError, match=r"vsd2xhtml failed with exit code"):
        convert(drawing, helpers.TOOLS, LIMITS)


def test_vsd2raw_stops_when_vsd2xhtml_fails(tmp_path: Path) -> None:
    marker = tmp_path / "raw-finished"
    tools = Tools(script(tmp_path, "exit 3"), raw=script(tmp_path, f"sleep 5; touch {marker}", "fake-vsd2raw"))
    start = time.monotonic()
    with pytest.raises(ConversionError, match=r"exit code 3"):
        convert(b"x", tools, LIMITS)
    assert time.monotonic() - start < 4
    time.sleep(0.2)
    assert not marker.exists()


def test_the_text_stays_when_vsd2raw_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    tools = Tools(helpers.CONVERTER, raw=script(tmp_path, "echo broken >&2; exit 2", "fake-vsd2raw"))
    with caplog.at_level(logging.WARNING, logger="weasyvsdx"):
        root = ET.fromstring(convert(helpers.drawing("poi/test.vsdx"), tools, LIMITS))
    assert root.find(f".//{{{SVG_NS}}}text") is not None
    assert "fake-vsd2raw failed with exit code 2: broken" in caplog.text


def test_the_text_stays_when_the_tools_count_other_objects(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    tools = Tools(helpers.CONVERTER, raw=script(tmp_path, "printf 'startPage()\\n  setStyle(draw:marker-end-path: m0 0)\\nendPage\\n'", "fake-vsd2raw"))
    with caplog.at_level(logging.WARNING, logger="weasyvsdx"):
        root = ET.fromstring(convert(helpers.drawing("poi/test.vsdx"), tools, LIMITS))
    assert root.find(f".//{{{SVG_NS}}}text") is not None
    assert "count other text objects" in caplog.text
    assert "count other paths" in caplog.text
    assert "count other markers" in caplog.text


def test_a_drawing_past_the_input_limit_never_reaches_the_converter(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    tools = Tools(script(tmp_path, f"touch {marker}"))
    with pytest.raises(ConversionError, match=r"more than 10 bytes"):
        convert(b"x" * 11, tools, Limits(max_input=10))
    assert not marker.exists()


def test_a_slow_converter_stops_at_the_timeout(tmp_path: Path) -> None:
    start = time.monotonic()
    tools = Tools(script(tmp_path, "sleep 10"))
    with pytest.raises(ConversionError, match=r"took more than 0.5 s"):
        convert(b"x", tools, Limits(timeout=0.5))
    assert time.monotonic() - start < 5


def test_the_converter_is_killed_past_the_output_limit(tmp_path: Path) -> None:
    # ulimit -f: the process gets SIGXFSZ when its output passes the limit
    tools = Tools(script(tmp_path, "head -c 100000 /dev/zero"))
    with pytest.raises(ConversionError, match=r"exit code"):
        convert(b"x", tools, Limits(max_output=4096))


def test_output_past_the_limit_fails_where_ulimit_does_not_hold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # As on macOS, where ulimit -f fails and the limit is checked after the run
    monkeypatch.setattr(convert_module, "LIMITED", 'shift 2; exec "$@"')
    tools = Tools(script(tmp_path, "head -c 100000 /dev/zero"))
    with pytest.raises(ConversionError, match=r"wrote more than 4096 bytes"):
        convert(b"x", tools, Limits(max_output=4096))


def test_the_converter_runs_with_the_memory_limit() -> None:
    # Too little address space to load libvisio at all
    drawing = helpers.drawing("poi/test.vsdx")
    with pytest.raises(ConversionError, match=r"exit code"):
        convert(drawing, PLAIN, Limits(max_memory=1024 * 1024))


def test_the_converter_reads_the_drawing_from_a_file_of_its_own(tmp_path: Path) -> None:
    converter = script(tmp_path, f'test "$(cat "$1")" = drawing-bytes && test "$(dirname "$1")" = "$(pwd)" && echo \'{page_xhtml("")}\'')
    assert ET.fromstring(convert(b"drawing-bytes", Tools(converter), LIMITS)).get("width") == "1in"


def test_run_returns_the_output(tmp_path: Path) -> None:
    assert run(["/bin/echo", "out"], tmp_path, LIMITS) == b"out\n"


def test_an_element_of_another_namespace_keeps_it() -> None:
    xhtml = page_xhtml('<svg:g/><x:meta xmlns:x="urn:x"/>').encode()
    root = ET.fromstring(serialize(first_page(xhtml)))
    assert [element.tag for element in root] == [f"{{{SVG_NS}}}g", "{urn:x}meta"]


def test_xhtml_that_is_not_well_formed() -> None:
    with pytest.raises(ConversionError, match=r"no well-formed XHTML"):
        first_page(b"<html><body>")


def test_xhtml_without_a_page() -> None:
    with pytest.raises(ConversionError, match=r"no page"):
        first_page(b'<html xmlns="http://www.w3.org/1999/xhtml"><body/></html>')


def test_a_missing_converter() -> None:
    assert find_converter("no-such-vsd2xhtml") is None
    assert find_converter() == helpers.CONVERTER
