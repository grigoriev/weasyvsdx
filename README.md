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

Install the tools of libvisio, and emf2svg for the EMF images that many drawings hold. On Debian 13 and
Ubuntu 24.04, which have the libvisio weasyvsdx needs (see "libvisio version"):

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

### libvisio version

Use libvisio 0.1.7. The tests and the bench run with it, and `install()` warns on any other release.
libvisio 0.1.8 to 0.1.11, the latest, fill the shapes of a VSDX with the colors of its theme over their own
colors: on the Azure diagrams of the bench, icons turn into olive disks and subnets into olive boxes.

| Distribution | libvisio |
|---|---|
| Debian 13 (trixie) | 0.1.7 |
| Ubuntu 24.04 | 0.1.7 |
| Debian testing, unstable | 0.1.11 |
| Ubuntu 26.04 | 0.1.10 |
| Alpine 3.22, 3.23 | 0.1.8 |
| Wolfi | none |

To keep it, pin the release of the base image, for example `python:3.14-slim-trixie`, and check it at
build time:

```sh
test "$(vsd2xhtml --version)" = "vsd2xhtml 0.1.7"
```

libvisio 0.1.9 and later also read the text background of a VSD, which 0.1.7 reads as black. weasyvsdx
draws black behind dark text as white, the most common background, so the labels show. A colored
background draws white as well.

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

## Fonts

Visio drawings ask for fonts of Microsoft, Segoe UI and Calibri most. weasyvsdx names a free replacement
after each, so an installed original still wins:

| Font | Replacement | Debian package |
|---|---|---|
| Calibri | Carlito, same metrics | `fonts-crosextra-carlito` |
| Cambria | Caladea, same metrics | `fonts-crosextra-caladea` |
| Segoe UI, Light, Semilight, Semibold | Selawik, close, not equal | none: the [release of microsoft/Selawik](https://github.com/microsoft/Selawik/releases) |

Without them, text falls back to the sans-serif font of the system, which breaks lines elsewhere than Visio.
Where the license allows it, install the original fonts instead.

## How it works

1. `vsd2xhtml` of libvisio writes each page of the drawing as SVG. weasyvsdx takes the first page, as
   LibreOffice does.
2. The generic SVG generator behind `vsd2xhtml` drops part of what libvisio reads. `vsd2raw` prints the
   same calls with all their properties, and weasyvsdx takes the rest from there:
   - **Text**: each text block becomes a `<foreignObject>` of its size, with its padding, vertical
     alignment and rotation, and its paragraphs and spans as HTML: alignment, line spacing, indents, bullets,
     font, size, scale, weight, style, color, underline, highlight, super- and subscript. WeasyPrint lays it out,
     so labels wrap inside their shapes as in Visio. The generator wrote each text as one line at the left
     edge of its block.
   - **Arrowheads**: each marker gets the shape and size of its line end. The generator drew one stock
     arrow for all of them, sized by the width of the line.
   - **Hidden shapes**: a shape on a hidden or non-printing layer goes. The generator drew it.
   - **Hidden text**: the text a shape of a VSDX hides (HideText, or a text cleared on the shape) goes. The
     generator wrote the name of each Azure icon under it.
   - **Hatches**: a fill pattern of Visio draws as the lines of its hatch. The generator filled it black.
   - **Gradients**: a shape of a VSDX that fills with a gradient of Visio 2013 or later gets it, linear or
     radial, from the XML of the page, its masters and styles. libvisio reads none, and filled it black.
   - **Line ends**: a line under an arrowhead ends at its base, as in Visio, not at its tip.
3. EMF images become SVG through `emf2svg-conv`, and so does the EMF that Office puts inside a WMF image,
   and the picture an embedded OLE object shows.
   WeasyPrint reads neither, and left them out.
4. A path that starts without a moveto loses its first segment, whose start libvisio does not give. Drawn as
   it was, it ran from the corner of the page.

The tools parse untrusted input in C, and a broken file can crash them. Each runs in a process of its own,
in a temporary directory, with a time limit and, on Linux, limits on its memory and its output.
`vsd2xhtml` and `vsd2raw` run at the same time. The SVG then goes through WeasyPrint like any other SVG,
and every URL inside it through the URL fetcher of the caller.

## How it compares to LibreOffice and Visio

The bench in [`tools/visual`](https://github.com/grigoriev/weasyvsdx/tree/main/tools/visual) renders 291
drawings and compares each with its PNG export by LibreOffice 25.2:

- the 41 test drawings of libvisio, Apache POI and LibreOffice in [`corpus/visio`](https://github.com/grigoriev/weasyvsdx/tree/main/corpus/visio);
- the 250 Visio diagrams of the Azure Architecture Center, which the bench downloads into a cache: their
  icons may not be copied into this repository, see [`corpus/SOURCES.md`](https://github.com/grigoriev/weasyvsdx/blob/main/corpus/SOURCES.md).

The [comparison page](https://grigoriev.github.io/weasyvsdx/corpus/comparison.html) shows each drawing of the
corpus in LibreOffice, as libvisio writes it, and in weasyvsdx, side by side, with a swipe between any two;
[`corpus/COMPARISON.md`](https://github.com/grigoriev/weasyvsdx/blob/main/corpus/COMPARISON.md) holds the same in the repository. The Azure
diagrams are not on it: their icons may not be redistributed.

All but two convert: libvisio crashes on `recursion-cycle.vsdx` and refuses `tab-short-prefix.vsdx`, two
of its tests that are broken on purpose. LibreOffice fails on the same two. Geometry, fills, gradients,
dashes, arrowheads and images match. The text differs most, and LibreOffice is no exact reference for it:
it lays text out with fonts of its own choice, and breaks words in narrow blocks where Visio does not. On
some drawings LibreOffice is wrong where weasyvsdx is right, for example it fills the whole of
`netapp-files-moodle-zonal` blue.

LibreOffice reads the drawings through libvisio, as weasyvsdx does, and shares its errors. So the bench
also compares 206 Azure diagrams with the SVG that Visio exported for their article. The median mismatch
is 26.3% against Visio, 48.3% against LibreOffice: weasyvsdx draws the gradients of the Azure icons, which
LibreOffice fills black. Much of the rest is the icons of Azure, see "Known gaps".

The median Azure diagram converts in 0.08 s, and 9 in 10 in less than 0.5 s. Drawings that embed bitmaps
of tens of MB take seconds, 17 of the 250 more than one: libvisio writes the bitmaps out as base64. One,
`adaptive-apps`, takes 46 s, more than the default timeout of 30 s: it converts only with a larger `timeout`.

## Known gaps

- Some parts of Azure icons are missing. libvisio 0.1.7 does not take the geometry of a part of a master
  group from the master. LibreOffice leaves them out too. A gradient of a shape whose ID another shape that
  libvisio draws shares stays black, as do the gradients of a VSD and the rarer kinds, FillGradientDir 8 to 13.
- Only the first page renders. LibreOffice and the converters before it did the same.
- Visio drawings ask for Calibri and Segoe UI most, fonts of Microsoft. A font the system lacks falls back
  to its free replacement, else to sans-serif: Calibri to Carlito and Cambria to Caladea, which share their
  metrics, so text breaks where Visio breaks it; Segoe UI to Selawik, the open fallback of Microsoft, close
  to it but not equal. Install them, see "Fonts".
- Character scaling (the "Scale" of a Visio font) applies where all text of a block shares one scale; a block
  of mixed scales draws unscaled. Fields show the value libvisio formats.
- A WMF image without an EMF inside is left out, and so is an embedded OLE object whose picture is no EMF.
  Office writes the EMF into each WMF it saves, and into the picture of each OLE object.
- Text that a VSD hides stays: only a VSDX holds HideText where weasyvsdx reads it.
- A shape on a hidden or non-printing layer goes, but its text would stay: libvisio marks the path of
  such a shape as hidden, not its text.
- An EMF draws its GDI records only. Part of an icon that Office drew in EMF+ alone, the newer records an EMF
  can carry in its comments, stays out: `emf2svg-conv` does not read EMF+, LibreOffice does.

## Development

Tests and the bench run in Docker, since WeasyPrint needs Pango and weasyvsdx the tools of libvisio. See
[CONTRIBUTING.md](https://github.com/grigoriev/weasyvsdx/blob/main/CONTRIBUTING.md).

```sh
make lint     # ruff and mypy, on the host
make test     # pytest with coverage, in Docker
make visual   # the visual bench, report in tools/visual/out/report.html
make comparison # corpus/COMPARISON.md and corpus/comparison.html, the panels in corpus/render
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
