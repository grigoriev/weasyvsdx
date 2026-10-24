"""install(): the converter it finds, the limits it passes, the version it warns about."""

from __future__ import annotations

from pathlib import Path

import helpers
import pytest
import weasyprint
import weasysvg

import weasyvsdx
from weasyvsdx import convert, fetch
from weasyvsdx.convert import LIBVISIO, MIB, Limits, Tools, libvisio_version


@pytest.fixture(autouse=True)
def default_install() -> object:
    yield
    weasyvsdx.install()


def test_install_returns_the_converter_it_found() -> None:
    assert weasyvsdx.install() == helpers.CONVERTER
    assert weasyvsdx.installed() == helpers.CONVERTER


def test_install_takes_a_converter_by_name_or_path() -> None:
    assert weasyvsdx.install(converter=helpers.CONVERTER) == helpers.CONVERTER
    assert fetch._SETTINGS["tools"] == helpers.TOOLS


def test_install_leaves_out_the_text_or_the_emf_tool() -> None:
    weasyvsdx.install(text=False)
    assert fetch._SETTINGS["tools"] == Tools(helpers.CONVERTER, None, helpers.TOOLS.emf)
    weasyvsdx.install(emf=False)
    assert fetch._SETTINGS["tools"] == Tools(helpers.CONVERTER, helpers.TOOLS.raw, None)


def test_install_installs_weasysvg_for_the_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(weasysvg, "installed", lambda: frozenset())
    monkeypatch.setattr(weasysvg, "install", lambda: calls.append("install"))
    weasyvsdx.install(text=False)
    assert calls == []
    weasyvsdx.install()
    assert calls == ["install"]


def test_install_fails_without_a_converter() -> None:
    with pytest.raises(weasyvsdx.ConverterNotFoundError, match=r"no-such-vsd2xhtml not found: install libvisio-tools"):
        weasyvsdx.install(converter="no-such-vsd2xhtml")


def test_install_passes_the_limits() -> None:
    weasyvsdx.install(timeout=5, max_input_mb=1, max_output_mb=2, max_memory_mb=3)
    assert fetch._SETTINGS["limits"] == Limits(timeout=5, max_input=MIB, max_output=2 * MIB, max_memory=3 * MIB)


def test_a_drawing_past_the_input_limit_renders_as_a_broken_image() -> None:
    weasyvsdx.install(max_input_mb=0)
    pdf = helpers.render(f'<img src="{helpers.data_url(helpers.drawing("poi/test.vsdx"))}">')
    assert "This is a test." not in helpers.text_of(pdf)


def test_install_warns_on_another_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weasyprint, "__version__", "71.0")
    with pytest.warns(RuntimeWarning, match=r"targets WeasyPrint 70.x, found 71.0"):
        weasyvsdx.install()


def test_the_tests_run_on_a_libvisio_weasyvsdx_is_tested_with() -> None:
    # The image pins it, 0.1.7 by default and 0.1.11 in the job that tests it
    assert libvisio_version(helpers.CONVERTER) in LIBVISIO == ("0.1.7", "0.1.11")


@pytest.mark.parametrize(
    ("body", "found"),
    [("echo 'vsd2xhtml 0.1.9'", "found 0.1.9"), ("exit 1", "found unknown"), ("echo 'Usage: vsd2xhtml'", "found unknown"), ("sleep 5", "found unknown")],
)
def test_install_warns_on_another_libvisio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, found: str) -> None:
    monkeypatch.setattr(convert, "VERSION_TIMEOUT", 0.5)
    converter = tmp_path / "vsd2xhtml"
    converter.write_text(f"#!/bin/sh\n{body}\n")
    converter.chmod(0o755)
    with pytest.warns(RuntimeWarning, match=rf"tested with libvisio 0.1.7 and 0.1.11, {found}: other releases"):
        weasyvsdx.install(converter=str(converter))


def test_a_converter_that_cannot_run_has_no_version(tmp_path: Path) -> None:
    converter = tmp_path / "vsd2xhtml"
    converter.write_text("not a program")
    assert libvisio_version(str(converter)) is None
