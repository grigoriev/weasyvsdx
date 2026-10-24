"""A Visio drawing to the SVG of its first page, through the tools of libvisio.

libvisio is the importer of LibreOffice. Its tool vsd2xhtml writes each page of a drawing as an SVG inside
one XHTML document. The first page is the image, as LibreOffice exports it. Its text and its arrowheads are
drawn anew from the output of vsd2raw (text.py, markers.py), and its EMF images become SVG through
emf2svg-conv (images.py). A path that starts without a moveto gets one (paths.py). Both tools are optional: without them the page stays as vsd2xhtml writes it.

The tools parse untrusted input in C, and a broken file can crash them: ``recursion-cycle.vsdx`` of the
libvisio tests ends in a segmentation fault. So each runs in a process of its own, in a temporary
directory, with a time limit, and on Linux with a limit on its memory and on the size of its output.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from . import hatch, hidden, hidden_text, images, markers, paths, raw, text
from .errors import ConversionError

SVG_NS = "http://www.w3.org/2000/svg"
CONVERTER = "vsd2xhtml"
RAW_CONVERTER = "vsd2raw"
EMF_CONVERTER = "emf2svg-conv"
MIB = 1024 * 1024
# The part of the error output of a tool that an error message quotes
STDERR_CHARS = 300
LOGGER = logging.getLogger("weasyvsdx")

# The limits run through the shell: subprocess has no parameter for them, and its preexec_fn is not safe
# in a process with threads, such as a service that renders in a thread pool. ulimit -v and -f fail on
# macOS, where the limits are then left out; the time limit holds everywhere.
LIMITED = 'ulimit -v "$1" 2>/dev/null; ulimit -f "$2" 2>/dev/null; shift 2; exec "$@"'


@dataclass(frozen=True)
class Limits:
    """What one run of a tool may take: seconds, and bytes of input, output and memory."""

    timeout: float = 30.0
    max_input: int = 64 * MIB
    max_output: int = 256 * MIB
    max_memory: int = 2048 * MIB

    def with_timeout(self, timeout: float) -> Limits:
        """The same limits with another timeout."""
        return Limits(timeout=timeout, max_input=self.max_input, max_output=self.max_output, max_memory=self.max_memory)


@dataclass(frozen=True)
class Tools:
    """The paths of the tools: vsd2xhtml, and vsd2raw and emf2svg-conv where found."""

    converter: str
    raw: str | None = None
    emf: str | None = None


def find_converter(name: str = CONVERTER) -> str | None:
    """The path of vsd2xhtml, or None when it is not on the PATH."""
    return shutil.which(name)


def find_tools(converter: str) -> Tools:
    """vsd2xhtml with the vsd2raw next to it, both of libvisio-tools, and emf2svg-conv on the PATH."""
    return Tools(converter, shutil.which(str(Path(converter).with_name(RAW_CONVERTER))), shutil.which(EMF_CONVERTER))


class Job:
    """A tool running in a process of its own, in folder, with the limits. result() waits for its output."""

    def __init__(self, command: list[str], folder: Path, limits: Limits) -> None:
        self.name = Path(command[0]).name
        self._limits = limits
        self._started = time.monotonic()
        self._output, self._errors = folder / f"{self.name}.out", folder / f"{self.name}.err"
        # ulimit -v counts KiB, ulimit -f blocks of 512 bytes
        limited = ["/bin/sh", "-c", LIMITED, "sh", str(limits.max_memory // 1024), str(limits.max_output // 512), *command]
        # Fixed tools on a file of the temporary directory: no shell reads the drawing
        with self._output.open("wb") as stdout, self._errors.open("wb") as stderr:
            self._process = subprocess.Popen(limited, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, cwd=folder)

    def result(self) -> bytes:
        """What the tool wrote to its output. Raises ConversionError."""
        try:
            returncode = self._process.wait(timeout=max(self._limits.timeout - (time.monotonic() - self._started), 0))
        except subprocess.TimeoutExpired as e:
            self.cancel()
            raise ConversionError(f"{self.name} took more than {self._limits.timeout} s") from e
        if returncode != 0:
            message = self._errors.read_text(errors="replace")[:STDERR_CHARS].strip()
            raise ConversionError(f"{self.name} failed with exit code {returncode}{': ' + message if message else ''}")
        if self._output.stat().st_size > self._limits.max_output:
            raise ConversionError(f"{self.name} wrote more than {self._limits.max_output} bytes")
        return self._output.read_bytes()

    def cancel(self) -> None:
        """Stop the tool, if it still runs."""
        if self._process.poll() is None:
            self._process.kill()
            self._process.wait()


def run(command: list[str], folder: Path, limits: Limits) -> bytes:
    """What the command writes to its output, run in folder. Raises ConversionError."""
    return Job(command, folder, limits).result()


def convert(data: bytes, tools: Tools, limits: Limits) -> bytes:
    """The SVG of the first page of the drawing, as bytes. Raises ConversionError."""
    if len(data) > limits.max_input:
        raise ConversionError(f"the drawing has more than {limits.max_input} bytes")
    with tempfile.TemporaryDirectory(prefix="weasyvsdx-") as directory:
        folder = Path(directory)
        source = folder / "drawing"
        source.write_bytes(data)
        # vsd2raw parses the drawing as long as vsd2xhtml: both run at once, which halves the time
        raw_job = Job([tools.raw, str(source)], folder, limits) if tools.raw is not None else None
        try:
            page = first_page(run([tools.converter, str(source)], folder, limits))
            paths.start_with_moveto(page)
            if raw_job is not None:
                redraw(page, raw_job, data)
        finally:
            if raw_job is not None:
                raw_job.cancel()
        if tools.emf is not None:
            images.replace_emf(page, emf_converter(tools.emf, folder, limits), folder)
    return serialize(page)


def emf_converter(emf: str, folder: Path, limits: Limits) -> images.Converter:
    """emf2svg-conv for each EMF of a page. All of them share one timeout: a page may hold thousands."""
    deadline = time.monotonic() + limits.timeout

    def to_svg(path: Path) -> bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ConversionError(f"the EMF images took more than {limits.timeout} s")
        return run([emf, "-i", str(path), "-o", "/dev/stdout"], folder, limits.with_timeout(remaining))

    return to_svg


def redraw(page: ET.Element, job: Job, document: bytes) -> None:
    """Draw the text, arrowheads and hatches of the page anew from what vsd2raw prints, and drop its hidden shapes."""
    try:
        calls = raw.first_page(job.result().decode("utf-8", errors="replace"))
    except ConversionError as e:
        LOGGER.warning("The text and arrowheads of a Visio drawing stay as vsd2xhtml writes them: %s", e)
        return
    # Before hidden shapes go: both pair the paths of the page with the drawPath calls
    if not hatch.fill_hatches(page, calls):
        LOGGER.warning("Hatched shapes of a Visio drawing may fill black: vsd2raw and vsd2xhtml count other paths")
    if not hidden.remove_hidden(page, calls):
        LOGGER.warning("Hidden shapes of a Visio drawing may show: vsd2raw and vsd2xhtml count other paths")
    objects = text.text_objects(calls)
    # The text that the shapes of a VSDX hide, which libvisio writes
    shapes = hidden_text.shape_texts(document)
    hidden_texts = hidden_text.hidden_indexes(shapes, [text.plain(item) for item in objects]) if shapes else frozenset()
    if not text.replace_text(page, objects, hidden_texts):
        LOGGER.warning("The text of a Visio drawing stays as vsd2xhtml writes it: vsd2raw and vsd2xhtml count other text objects")
    if not markers.replace_markers(page, calls):
        LOGGER.warning("Some arrowheads of a Visio drawing stay as vsd2xhtml writes them: vsd2raw and vsd2xhtml count other markers")


def first_page(document: bytes) -> ET.Element:
    """The first SVG of the XHTML of vsd2xhtml."""
    try:
        # The output of libvisio, which escapes the text of the drawing and declares no entities
        root = ET.fromstring(document)
    except ET.ParseError as e:
        raise ConversionError(f"{CONVERTER} wrote no well-formed XHTML: {e}") from e
    page = root.find(f".//{{{SVG_NS}}}svg")
    if page is None:
        raise ConversionError(f"the drawing has no page that {CONVERTER} draws")
    return page


def serialize(page: ET.Element) -> bytes:
    """The page as an SVG document of its own."""
    # The SVG namespace as the default one, without the prefix of the XHTML. The default_namespace of
    # tostring() cannot do it: it refuses attributes without a namespace, which is nearly all of them.
    prefix = f"{{{SVG_NS}}}"
    for element in page.iter():
        if isinstance(element.tag, str) and element.tag.startswith(prefix):
            element.tag = element.tag[len(prefix) :]
    page.set("xmlns", SVG_NS)
    svg: bytes = ET.tostring(page, encoding="utf-8")
    return svg
