# weasyvsdx

[![CI](https://github.com/grigoriev/weasyvsdx/actions/workflows/ci.yml/badge.svg)](https://github.com/grigoriev/weasyvsdx/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/grigoriev/weasyvsdx/badge)](https://scorecard.dev/viewer/?uri=github.com/grigoriev/weasyvsdx)
[![Release](https://img.shields.io/github/v/release/grigoriev/weasyvsdx)](https://github.com/grigoriev/weasyvsdx/releases)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/grigoriev/weasyvsdx/blob/main/LICENSE)

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=grigoriev_weasyvsdx&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=grigoriev_weasyvsdx)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=grigoriev_weasyvsdx&metric=coverage)](https://sonarcloud.io/summary/new_code?id=grigoriev_weasyvsdx)

A plugin for [WeasyPrint](https://weasyprint.org) 70.x that draws Microsoft Visio drawings (VSDX, VSD) as
vector SVG, through [libvisio](https://github.com/LibreOffice/libvisio).

## Why?

WeasyPrint cannot read Visio drawings. Services that turn HTML into PDF convert them with LibreOffice
first, to a PNG. LibreOffice adds some 730 MB to an image and hundreds of findings to its scans, and the
drawing ends up as pixels.

weasyvsdx hands each drawing to the tools of libvisio, the library LibreOffice itself imports Visio with,
and draws the result as SVG inside WeasyPrint. The drawing stays vector and its text stays selectable. The
tools take some 41 MB on Debian.

## Installation

weasyvsdx runs on CPython 3.11 to 3.14.

Install the tools of libvisio, and emf2svg for the EMF images that many drawings hold. On Debian and
Ubuntu:

```sh
apt-get install libvisio-tools emf2svg
```

Then install weasyvsdx from PyPI:

```sh
pip install weasyvsdx
```

weasyvsdx depends on WeasyPrint and on [weasysvg](https://github.com/grigoriev/weasysvg), which draws the
text of the drawings. WeasyPrint needs Pango, see its
[installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).

### Verify

The build of each release has signed provenance on GitHub, and the GitHub release carries its bundle.
PyPI and the GitHub release hold the same files, so verify a file from either with
`gh attestation verify <file> --repo grigoriev/weasyvsdx`. On PyPI each file also has a publish
attestation (PEP 740): it ties the upload to `release.yml` of this repository.

## Usage

Call `install()` once, before the first rendering:

```python
import weasyprint
import weasyvsdx

weasyvsdx.install()
weasyprint.HTML(string='<img src="plan.vsdx">', base_url=".").write_pdf("plan.pdf")
```

An image renders as a Visio drawing when its media type says so, `application/vnd.ms-visio.drawing` for
VSDX or `application/vnd.visio` for VSD, or when a file or URL without a type ends in `.vsdx`, `.vsd` or
another Visio suffix. A data URL counts by its type alone. This works for `<img>`, `<object>`, `<embed>`,
CSS images and `<image>` inside an SVG.

`install()` patches WeasyPrint in place, for the whole process, and returns the path of `vsd2xhtml`. It
raises `ConverterNotFoundError` when `vsd2xhtml` is not on the PATH. A later call changes the settings.

| Argument | Default | Effect |
|---|---|---|
| `converter` | `"vsd2xhtml"` | the `vsd2xhtml` to run, a name on the PATH or a path |
| `text` | `True` | lay the text out anew from `vsd2raw`, next to `vsd2xhtml`; installs weasysvg with its defaults unless its `foreign_object` is installed |
| `emf` | `True` | turn EMF images into SVG through `emf2svg-conv`, where it is on the PATH |
| `timeout` | `30.0` | seconds one run of a tool may take |
| `max_input_mb` | `64` | the largest drawing, in MB |
| `max_output_mb` | `256` | the most a tool may write, in MB (Linux) |
| `max_memory_mb` | `2048` | the address space of each tool, in MB (Linux) |

A drawing that does not convert, or that passes a limit, renders as a broken image: WeasyPrint logs the
error and leaves it out, and the rest of the document renders.

## How it works

1. `vsd2xhtml` of libvisio writes each page of the drawing as SVG. weasyvsdx takes the first page, as
   LibreOffice does.
2. The generic SVG generator behind `vsd2xhtml` drops part of what libvisio reads. `vsd2raw` prints the
   same calls with all their properties, and weasyvsdx takes the rest from there:
   - **Text**: each text block becomes a `<foreignObject>` of its size, with its padding, vertical
     alignment and rotation, and its paragraphs and spans as HTML: alignment, line spacing, indents, bullets,
     font, size, weight, style, color, underline, highlight, super- and subscript. WeasyPrint lays it out,
     so labels wrap inside their shapes as in Visio. The generator wrote each text as one line at the left
     edge of its block.
   - **Arrowheads**: each marker gets the shape and size of its line end. The generator drew one stock
     arrow for all of them, sized by the width of the line.
3. EMF images become SVG through `emf2svg-conv`. WeasyPrint cannot read EMF, and left them out.

The tools parse untrusted input in C, and a broken file can crash them. Each runs in a process of its own,
in a temporary directory, with a time limit and, on Linux, limits on its memory and its output.
`vsd2xhtml` and `vsd2raw` run at the same time. The SVG then goes through WeasyPrint like any other SVG,
and every URL inside it through the URL fetcher of the caller.

## How it compares to LibreOffice

The bench in [`tools/visual`](https://github.com/grigoriev/weasyvsdx/tree/main/tools/visual) renders 291
drawings and compares each with its PNG export by LibreOffice 25.2:

- the 41 test drawings of libvisio, Apache POI and LibreOffice in [`corpus/visio`](https://github.com/grigoriev/weasyvsdx/tree/main/corpus/visio);
- the 250 Visio diagrams of the Azure Architecture Center, which the bench downloads into a cache: their
  icons may not be copied into this repository, see [`corpus/SOURCES.md`](https://github.com/grigoriev/weasyvsdx/blob/main/corpus/SOURCES.md).

All but two convert: libvisio crashes on `recursion-cycle.vsdx` and refuses `tab-short-prefix.vsdx`, two
of its tests that are broken on purpose. LibreOffice fails on the same two. Geometry, fills, gradients,
dashes, arrowheads and images match. The text differs most, and LibreOffice is no exact reference for it:
it lays text out with fonts of its own choice, and breaks words in narrow blocks where Visio does not. On
some drawings LibreOffice is wrong where weasyvsdx is right, for example it fills the whole of
`netapp-files-moodle-zonal` blue.

The median Azure diagram converts in 0.08 s, and 9 in 10 in less than 0.5 s. Drawings that embed bitmaps
of tens of MB take seconds, 17 of the 250 more than one: libvisio writes the bitmaps out as base64. One,
`adaptive-apps`, takes 46 s and passes the default timeout of 30 s.

## Known gaps

- Only the first page renders. LibreOffice and the converters before it did the same.
- A font the system lacks falls back to the sans-serif font. Visio drawings ask for Calibri and Segoe UI
  most: install Carlito, the metric-compatible replacement of Calibri, for text that breaks where Visio
  breaks it. Segoe UI has none.
- Character scaling (the "Scale" of a Visio font) and numbered lists draw as plain text. Fields show the
  value libvisio formats.
- WMF images and embedded OLE objects are left out: neither WeasyPrint nor emf2svg reads them.
- A line under a hollow arrowhead shows through it, where LibreOffice shortens the line.

## Development

Tests and the bench run in Docker, since WeasyPrint needs Pango and weasyvsdx the tools of libvisio. See
[CONTRIBUTING.md](https://github.com/grigoriev/weasyvsdx/blob/main/CONTRIBUTING.md).

```sh
make lint     # ruff and mypy, on the host
make test     # pytest with coverage, in Docker
make visual   # the visual bench, report in tools/visual/out/report.html
```

## Contributing

See [CONTRIBUTING.md](https://github.com/grigoriev/weasyvsdx/blob/main/CONTRIBUTING.md). Report vulnerabilities privately, see [SECURITY.md](https://github.com/grigoriev/weasyvsdx/blob/main/SECURITY.md).

## Disclaimer

This software is provided "as is", without warranty of any kind, as the LICENSE states. Use
it at your own risk. Sergey Grigoriev is not liable for damage from its use, as far as the law
allows. It is published free of charge, outside of any commercial offering, with no
obligation to support it. Security reports are welcome, see [SECURITY.md](https://github.com/grigoriev/weasyvsdx/blob/main/SECURITY.md).

## License

MIT, see [LICENSE](https://github.com/grigoriev/weasyvsdx/blob/main/LICENSE). The test corpus keeps the licenses of its sources, see
[corpus/SOURCES.md](https://github.com/grigoriev/weasyvsdx/blob/main/corpus/SOURCES.md).
