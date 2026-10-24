"""Visio drawings in WeasyPrint: each place an image loads from, and the responses left alone."""

from __future__ import annotations

import base64
import inspect
import logging
from pathlib import Path

import helpers
import pytest
from weasyprint import document as wp_document
from weasyprint import images as wp_images
from weasyprint.urls import URLFetcher, URLFetcherResponse

from weasyvsdx import fetch
from weasyvsdx.convert import Limits
from weasyvsdx.fetch import VisioFetcher, is_visio

# A white PNG of 1 x 1 pixel
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC")


def test_an_img_with_a_vsdx_data_url_renders_its_drawing() -> None:
    pdf = helpers.render(f'<img src="{helpers.data_url(helpers.drawing("poi/test.vsdx"))}">')
    assert "This is a test." in helpers.text_of(pdf)
    assert "Nothing fancy." in helpers.text_of(pdf)


def test_a_binary_vsd_renders_by_its_media_type() -> None:
    pdf = helpers.render(f'<img src="{helpers.data_url(helpers.drawing("libvisio/Visio11TextFieldsWithUnits.vsd"), "application/vnd.visio")}">')
    assert helpers.objects_of(pdf) > 0


def test_a_file_url_renders_by_its_suffix(tmp_path: Path) -> None:
    (tmp_path / "diagram.vsdx").write_bytes(helpers.drawing("poi/test.vsdx"))
    pdf = helpers.render('<img src="diagram.vsdx">', base_url=str(tmp_path) + "/")
    assert "This is a test." in helpers.text_of(pdf)


def test_a_css_background_renders_the_drawing() -> None:
    url = helpers.data_url(helpers.drawing("poi/test.vsdx"))
    pdf = helpers.render(f'<div style="width:1100px;height:800px;background:url({url}) no-repeat;background-size:contain"></div>')
    assert "This is a test." in helpers.text_of(pdf)


def test_an_image_inside_an_svg_renders_the_drawing() -> None:
    # WeasyPrint loads it with the media type forced to image/*: the SVG comes through its last chance
    url = helpers.data_url(helpers.drawing("poi/test.vsdx"))
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1100" height="800"><image width="1100" height="800" xlink:href="{url}"/></svg>'
    pdf = helpers.render(svg)
    assert "This is a test." in helpers.text_of(pdf)


def test_a_broken_drawing_is_left_out_as_a_broken_image(caplog: pytest.LogCaptureFixture) -> None:
    broken = helpers.data_url(helpers.drawing("libvisio/tab-short-prefix.vsdx"))
    good = helpers.data_url(helpers.drawing("poi/test.vsdx"))
    with caplog.at_level(logging.ERROR, logger="weasyprint"):
        pdf = helpers.render(f'<img src="{broken}"><img src="{good}">')
    assert "This is a test." in helpers.text_of(pdf)
    assert any("ConversionError" in record.getMessage() and "exit code" in record.getMessage() for record in caplog.records)


def test_other_images_pass_unchanged() -> None:
    pdf = helpers.render(f'<img src="data:image/png;base64,{base64.b64encode(PNG).decode()}">')
    assert helpers.objects_of(pdf) == 1


@pytest.mark.parametrize(
    ("content_type", "url", "expected"),
    [
        ("application/vnd.ms-visio.drawing", "data:application/vnd.ms-visio.drawing;base64,", True),
        ("application/vnd.visio", "https://example.org/a", True),
        ("application/vnd.ms-visio.drawing.macroenabled.12", "https://example.org/a", True),
        ("application/octet-stream", "https://example.org/files/Plan.VSDX?version=2", True),
        ("text/plain", "file:///tmp/plan.vsd", True),
        ("", "https://example.org/plan.vsdm#page", True),
        # A suffix never wins over a type that says what the content is
        ("image/png", "https://example.org/plan.vsdx", False),
        # A data URL has no path: its type alone counts
        ("text/plain", "data:,plan.vsdx", False),
        ("application/octet-stream", "https://example.org/plan.pdf", False),
    ],
)
def test_what_counts_as_a_visio_drawing(content_type: str, url: str, expected: bool) -> None:
    assert is_visio(content_type, url) is expected


def test_the_fetcher_passes_the_attributes_of_the_inner_one() -> None:
    # weasyprint.urls.fetch reads _fail_on_errors of the fetcher it calls
    inner = URLFetcher(fail_on_errors=True)
    assert VisioFetcher(inner, helpers.TOOLS, Limits())._fail_on_errors is True


def test_a_wrapped_fetcher_is_not_wrapped_again(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []
    monkeypatch.setattr(fetch, "_ORIGINAL_GET_IMAGE_FROM_URI", lambda cache, url_fetcher, *args, **kwargs: seen.append(url_fetcher))
    wrapped = VisioFetcher(URLFetcher(), helpers.TOOLS, Limits())
    fetch._get_image_from_uri({}, wrapped, None, "data:,")
    fetch._get_image_from_uri({}, None, None, "data:,")
    assert seen == [wrapped, None]


def test_the_hooked_loader_keeps_its_shape() -> None:
    # Document binds the loader under this name, with these parameters, in WeasyPrint 70
    assert wp_document.original_get_image_from_uri is fetch._get_image_from_uri
    assert fetch._ORIGINAL_GET_IMAGE_FROM_URI is wp_images.get_image_from_uri
    parameters = list(inspect.signature(wp_images.get_image_from_uri).parameters)
    assert parameters == list(inspect.signature(fetch._get_image_from_uri).parameters)


@pytest.mark.parametrize(("requested", "final"), [("https://example.org/download", "https://example.org/plan.vsdx"), ("https://example.org/plan.vsdx", "https://example.org/download")])
def test_a_redirect_to_or_from_a_visio_suffix_converts(requested: str, final: str) -> None:
    def inner(url: str) -> URLFetcherResponse:
        return URLFetcherResponse(final, helpers.drawing("poi/test.vsdx"), {"Content-Type": "application/octet-stream"})

    response = VisioFetcher(inner, helpers.TOOLS, Limits())(requested)
    assert response.content_type == fetch.SVG_TYPE
