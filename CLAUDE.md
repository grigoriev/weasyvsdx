# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/claude-code) when working with this repository.

## Project Overview

weasyvsdx is a plugin for WeasyPrint 70.x that draws Microsoft Visio drawings (VSDX, VSD) as vector SVG.
One `weasyvsdx.install()` call hooks the image loader of WeasyPrint for the whole process. The tools of
libvisio (`vsd2xhtml`, `vsd2raw`, Debian package `libvisio-tools`) and `emf2svg-conv` (package `emf2svg`)
do the parsing, each in a process of its own. weasysvg draws the text, which weasyvsdx writes as HTML in a
`<foreignObject>`.

## Tech Stack

- **Python**: 3.11+, CPython only (the target services run 3.14)
- **Package Manager**: uv
- **Build Backend**: hatchling, `src/` layout
- **Linting/Formatting**: ruff, line length 240
- **Type Checking**: mypy (strict mode); WeasyPrint has no types, so its objects are `Any`
- **Testing**: pytest with pytest-cov, in Docker (WeasyPrint needs Pango, the tests the tools of libvisio)

## Common Commands

```bash
uv sync --all-extras    # install dependencies
make lint               # ruff check, ruff format --check, mypy src tests tools
make test               # pytest with coverage in Docker (Dockerfile.test, stage "test")
make azure              # download the Azure diagrams of corpus/azure.json into the cache
make visual             # visual bench in Docker (stage "visual"), report in tools/visual/out/report.html
make visual-baseline    # write corpus/baseline.json
make visual-check       # compare with corpus/baseline.json, fails when a drawing got worse or its SVG of Visio is missing
make references         # export the LibreOffice references again
make comparison         # write corpus/COMPARISON.md, corpus/comparison.html (GitHub Pages), panels in corpus/render
uv build                # wheel and sdist
```

## Architecture

`src/weasyvsdx/`:

- `__init__.py`: `install()` finds the tools, installs weasysvg for the text where needed, and hooks
  WeasyPrint through `fetch.install()`.
- `fetch.py`: replaces `weasyprint.document.original_get_image_from_uri`, the name `Document` binds the
  image loader under. The wrapper puts `VisioFetcher` in front of the URL fetcher of the caller: a response
  with a Visio media type, or a Visio suffix where the type says nothing, comes back as SVG.
- `convert.py`: runs the tools (`Job`: a process with `ulimit -v` and `-f` through `/bin/sh`, and a
  timeout), `vsd2xhtml` and `vsd2raw` at the same time, takes the first page of the XHTML and serializes it
  with the SVG namespace as the default one.
- `raw.py`: the output of `vsd2raw`, one call per line: the calls of the first page and their properties.
- `text.py`: each `<text>` of the page becomes a `<foreignObject>` of its text block, the n-th `<text>` in
  document order for the n-th `startTextObject`. Paragraphs and spans become HTML in a flex column.
- `markers.py`: the k-th `startMarker`/`endMarker` gets the path of the k-th style with that marker, scaled
  by the box of its path, as LibreOffice scales it.
- `images.py`: each `data:image/emf` image becomes SVG through `emf2svg-conv`, and the EMF a `data:image/wmf`
  holds in its MS-WMF comment records (`embedded_emf()`) too. A `data:object/ole` shows the EMF of its
  MS-OLEDS presentation stream (`ole_preview()`, read with olefile). `upright_bitmaps()` turns a bitmap drawn
  to a negative height upright first: emf2svg-conv mirrors it.
- `paths.py`: a path without a leading moveto loses its first segment, whose end becomes the start
  (`start_with_moveto()`); `shortened()` ends a line at the base of its arrowhead.
- `hatch.py`: a path whose style has `draw:fill: hatch` gets the lines of its hatch, clipped to it. They are
  `<line>` elements, so the path count that `hidden.py` pairs stays.
- `package.py`: reads the XML of a VSDX within a budget of unpacked bytes: the first page, its background
  pages, masters, styles and colors. `page_shapes()` walks the shapes of the first page as `Placed`: each with
  its master shape and the groups around it.
- `fills.py`: the fill colors of each shape of a VSDX (FillForegnd, FillBkgnd, through master and style chain;
  `Themed` draws white), and of its background pages. `recolor()` restores them on the paths, which libvisio
  0.1.8 and later fill with theme colors; its calls go to `hatch.py` only, as `markers.py` counts setStyle.
  The background ends at the first path of a shape or group the background pages lack.
- `gradients.py`: the gradient of each shape of a VSDX (FillGradientEnabled, the FillGradient stops,
  FillGradientDir and FillGradientAngle, through master and style chain), by its ID. A path gets it by the
  `draw:id` of its `drawPath`, or of the innermost named `startLayer` around it (`path_shapes()`). The gradient turns and flips with the shape
  and its groups (`Turn`), unless RotateGradientWithShape is 0. An ID that occurs twice, on a background page
  or as a shape of a master the page does not list, goes.
- `geometry.py`: a shape of a master group that the page lists without geometry, and libvisio leaves out,
  gets a path from the geometry rows of its master (merged row by row with its own, master values scaled to
  its size), placed through the pins, angles and flips of its groups. Arcs and NURBS become lines. Fill, line,
  `LinePattern` dashes (`DASHES`) and gradient come from its cells. The paths carry `MASTER_CLASS`, which
  `drawn_paths()` passes by, and go in first, after the last path of the shapes before them.
- `hidden_text.py`: reads HideText and cleared texts from the XML of a VSDX (first page and masters) and aligns
  those texts with the text objects of `vsd2raw` (difflib); a matched hidden one goes in `replace_text()`.
- `hidden.py`: the n-th drawn path goes when the n-th `drawPath` of `vsd2raw` has `draw:display: none`, a
  shape on a hidden or non-printing layer.
- `pathdata.py`: path data as tokens, read by hand: the numbers of SVG (`.5.5` is two) make a pattern backtrack.
- `errors.py`: `ConversionError`.

A count that differs between `vsd2xhtml` and `vsd2raw` leaves the page as `vsd2xhtml` wrote it, with a
warning: the mapping relies on both walking the drawing in one order.

## Testing

- `tests/helpers.py` installs weasyvsdx, renders HTML with WeasyPrint, reads text back with PDFium, and
  builds a minimal EMF (`emf_rectangle()`), a WMF that holds one (`wmf_holding()`), and an OLE object
  (`ole_holding()` of `presentation()` streams).
- Fake tools are shell scripts written into `tmp_path` (`script()` in `test_convert.py`).
- Coverage is 100% of lines and branches.

## Visual regression bench

`tools/visual/bench.py` renders the corpus and the cached Azure diagrams, compares with the LibreOffice
references and writes a report. LibreOffice Draw has one page size per document, the largest page: the
bench places the first page at its top left, at 96 dpi, shrunk as LibreOffice shrinks to 2048 px.

LibreOffice reads the drawings through libvisio 0.1.7, as weasyvsdx does, and shares its errors. The SVGs
that Visio exported for the Azure articles (`corpus/azure.json`, key `visio`) are the reference that counts:
the bench compares 206 diagrams with them. Overlay both renderings to see what differs.

**Never judge a rendering with poppler.** Use PDFium (`tools/visual/imaging.py`), and check a disputed
case in Quartz (macOS Preview). LibreOffice is no exact reference for text: it picks its own fonts.

Every corpus file needs a cleared license and an entry in `corpus/SOURCES.md`. The Azure diagrams and
their references stay in the cache (`WEASYVSDX_CACHE`, `~/.cache/weasyvsdx`), never in the repository:
their icons may not be redistributed.

## Code Style

- Strict mypy typing; WeasyPrint objects are `Any`.
- Comments say why, with the behavior of Visio or LibreOffice they follow.
- No em-dashes, American spelling.

## Review focus

- Untrusted drawings: every tool runs through `Job` with the limits, in the temporary directory. No tool
  reads anything but its input file. A failed tool must stop the other (`cancel()`), also on an exception.
- The SVG goes back through WeasyPrint and the URL fetcher of the caller: nothing may fetch on its own.
- WeasyPrint internals change between majors: `test_the_hooked_loader_keeps_its_shape` must fail when the
  hooked loader changes.
- A rendering change updates `corpus/baseline.json`, the comparison (`make comparison`) and, for a new gap or a
  fixed one, the README. The comparison holds the corpus of the repository only, never an Azure diagram.

## CI/CD

- **CI** (`ci.yml`): actionlint and zizmor; ruff and mypy on the runner; tests on Python 3.11 to 3.14
  through `make test`, in `Dockerfile.test`, with libvisio 0.1.7 of Debian 13; `test-libvisio` runs them once
  more with 0.1.11 of Debian testing (`make test LIBVISIO=0.1.11`); SonarCloud on the `coverage.xml` of
  `make test`; build. The runner would take the libvisio of its Ubuntu.
- **Scorecard** (`scorecard.yml`): OpenSSF Scorecard, weekly and on push to main.
- **Release** (`release.yml`): on `v*` tags, tests, one build with signed provenance, then PyPI
  through Trusted Publishing (`pypi` environment), then a GitHub release with the wheel, the sdist
  and the provenance bundle.
- Every action is pinned by SHA, `${{ }}` values reach `run:` through `env:`, checkouts use
  `persist-credentials: false`.

## Release Process

1. Add each change under `## [Unreleased]` in `CHANGELOG.md`, in the pull request that makes it.
2. Run the **Bump Version & Release** workflow with `patch`, `minor` or `major`. It writes the
   version to `pyproject.toml` and `uv.lock`, cuts the changelog, commits, tags `vX.Y.Z` and pushes.
3. The tag triggers `release.yml`, which publishes to PyPI and creates the GitHub release.
