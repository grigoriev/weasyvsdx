"""Hands WeasyPrint each Visio drawing as the SVG of its first page.

Touches: ``document.original_get_image_from_uri``, the name under which ``Document`` binds the image loader
of each rendering: an ``<img>``, ``<object>`` or ``<embed>``, a CSS image, an ``<image>`` inside an SVG. The
wrapper puts a fetcher in front of the fetcher of the caller. A response that holds a Visio drawing comes
back as SVG; any other response passes unchanged. WeasyPrint then builds an SVGImage from it, as from any
SVG, and every URL inside the SVG still goes through the fetcher of the caller.
"""

from __future__ import annotations

from posixpath import splitext
from typing import Any
from urllib.parse import urlsplit

from weasyprint import document as wp_document
from weasyprint.urls import URLFetcherResponse

from .convert import Limits, Tools, convert

# The media types of Visio drawings, templates and stencils, binary (.vsd) and Open XML (.vsdx). They match
# lowercase: the headers of a response give the type lowercase.
VISIO_TYPES = frozenset(
    {
        "application/vnd.visio",
        "application/vnd.ms-visio.drawing",
        "application/vnd.ms-visio.drawing.main+xml",
        "application/vnd.ms-visio.drawing.macroenabled.12",
        "application/vnd.ms-visio.drawing.macroenabled.main+xml",
        "application/vnd.ms-visio.template",
        "application/vnd.ms-visio.template.main+xml",
        "application/vnd.ms-visio.template.macroenabled.12",
        "application/vnd.ms-visio.stencil",
        "application/vnd.ms-visio.stencil.macroenabled.12",
    }
)
VISIO_SUFFIXES = frozenset({".vsd", ".vsdx", ".vsdm", ".vst", ".vstx", ".vstm", ".vss", ".vssx", ".vssm"})
# The types that say nothing of the content. A file URL of an unknown suffix gets text/plain from urllib.
UNTYPED = frozenset({"", "application/octet-stream", "text/plain"})
SVG_TYPE = "image/svg+xml"

_ORIGINAL_GET_IMAGE_FROM_URI = wp_document.original_get_image_from_uri


def is_visio(content_type: str, url: str) -> bool:
    """A Visio drawing by its media type, or by the suffix of its path where the type says nothing."""
    if content_type in VISIO_TYPES:
        return True
    return content_type in UNTYPED and not url.startswith("data:") and splitext(urlsplit(url).path)[1].lower() in VISIO_SUFFIXES


class VisioFetcher:
    """The fetcher of the caller, with each Visio drawing turned into SVG."""

    def __init__(self, inner: Any, tools: Tools, limits: Limits) -> None:
        self._inner = inner
        self._tools = tools
        self._limits = limits

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __call__(self, url: str) -> Any:
        response = self._inner(url)
        if not is_visio(response.content_type, url):
            return response
        try:
            # One byte past the limit is enough to know that the drawing is too large
            data = response.read(self._limits.max_input + 1)
        finally:
            response.close()
        # A ConversionError fails the fetch: WeasyPrint logs it and leaves the image out, as any broken image
        svg = convert(data, self._tools, self._limits)
        return URLFetcherResponse(response.url, svg, {"Content-Type": SVG_TYPE}, response.status)


_SETTINGS: dict[str, Any] = {}


def _get_image_from_uri(
    cache: Any,
    url_fetcher: Any,
    options: Any,
    url: str,
    forced_mime_type: str | None = None,
    context: Any = None,
    orientation: str = "from-image",
) -> Any:
    if url_fetcher is not None and not isinstance(url_fetcher, VisioFetcher):
        url_fetcher = VisioFetcher(url_fetcher, _SETTINGS["tools"], _SETTINGS["limits"])
    return _ORIGINAL_GET_IMAGE_FROM_URI(cache, url_fetcher, options, url, forced_mime_type=forced_mime_type, context=context, orientation=orientation)


def install(tools: Tools, limits: Limits) -> None:
    """Hook the image loader of WeasyPrint. A second call changes the tools and the limits."""
    _SETTINGS["tools"] = tools
    _SETTINGS["limits"] = limits
    wp_document.original_get_image_from_uri = _get_image_from_uri
