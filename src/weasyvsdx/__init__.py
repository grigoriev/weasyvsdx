"""Visio drawings for WeasyPrint, drawn as vector SVG through libvisio.

Call ``install()`` once, before the first rendering. It patches WeasyPrint in place, for the process: an
image with a Visio media type renders as the SVG of its first page. The package targets WeasyPrint 70.x and
warns on any other version.
"""

from __future__ import annotations

import warnings

import weasyprint
import weasysvg

from . import fetch as _fetch
from .convert import CONVERTER, LIBVISIO, MIB, Limits, Tools, find_converter, find_tools, libvisio_version
from .errors import ConversionError

__all__ = ["LIBVISIO", "SUPPORTED_MAJOR", "ConversionError", "ConverterNotFoundError", "install", "installed"]

SUPPORTED_MAJOR = 70
_INSTALLED: dict[str, str] = {}


class ConverterNotFoundError(FileNotFoundError):
    """vsd2xhtml is not on the PATH: install libvisio-tools."""


def _check_version() -> None:
    version = getattr(weasyprint, "__version__", "")
    if version.split(".", 1)[0] != str(SUPPORTED_MAJOR):
        warnings.warn(
            f"weasyvsdx targets WeasyPrint {SUPPORTED_MAJOR}.x, found {version or 'unknown'}: the patch may not apply",
            RuntimeWarning,
            stacklevel=3,
        )


def _check_libvisio(converter: str) -> None:
    version = libvisio_version(converter)
    if version != LIBVISIO:
        warnings.warn(
            f"weasyvsdx is tested with libvisio {LIBVISIO}, found {version or 'unknown'}: libvisio 0.1.8 to 0.1.11 fill the shapes of a VSDX with theme colors",
            RuntimeWarning,
            stacklevel=3,
        )


def install(
    *,
    converter: str | None = None,
    text: bool = True,
    emf: bool = True,
    timeout: float = 30.0,
    max_input_mb: int = 64,
    max_output_mb: int = 256,
    max_memory_mb: int = 2048,
) -> str:
    """Render Visio drawings in WeasyPrint, and return the path of the converter.

    ``converter`` is the vsd2xhtml to run, found on the PATH by default. ``text`` lays the text out anew
    from vsd2raw, next to it, as HTML in a foreignObject: it wraps and aligns as in Visio. weasysvg draws the
    foreignObject, so install() installs weasysvg with its defaults unless its foreign_object is already
    installed. Without vsd2raw the text stays as vsd2xhtml writes it. ``emf`` turns EMF images into SVG
    through emf2svg-conv, where it is on the PATH; WeasyPrint cannot read EMF. One run of a tool may take
    ``timeout`` seconds, read ``max_input_mb`` of drawing and, on Linux, write ``max_output_mb`` of SVG and
    use ``max_memory_mb`` of memory. A drawing past a limit renders as a broken image. A later call
    changes the converter and the limits. Raises ConverterNotFoundError when there is no converter, and
    warns when it reports another libvisio than ``LIBVISIO``.
    """
    _check_version()
    path = find_converter(converter or CONVERTER)
    if path is None:
        raise ConverterNotFoundError(f"{converter or CONVERTER} not found: install libvisio-tools")
    _check_libvisio(path)
    found = find_tools(path)
    tools = Tools(path, found.raw if text else None, found.emf if emf else None)
    if tools.raw is not None and "foreign_object" not in weasysvg.installed():
        weasysvg.install()
    limits = Limits(timeout=timeout, max_input=max_input_mb * MIB, max_output=max_output_mb * MIB, max_memory=max_memory_mb * MIB)
    _fetch.install(tools, limits)
    _INSTALLED["converter"] = path
    return path


def installed() -> str | None:
    """The path of the converter of the last install(), or None before the first."""
    return _INSTALLED.get("converter")
