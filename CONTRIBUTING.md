# Contributing

Issues and pull requests are welcome.

## Build and test

WeasyPrint needs Pango and weasyvsdx the tools of libvisio. macOS has neither, so the tests and the bench
run in Docker (`Dockerfile.test`). Lint and type checks run on the host.

```sh
uv sync --all-extras                # install the dependencies
make lint                           # ruff check, ruff format --check, mypy
make test                           # pytest with coverage, in Docker
make test BASE=python:3.11-slim-trixie  # the same on the lowest supported Python
make visual                         # the visual bench, in Docker
make visual-check                   # the bench against corpus/baseline.json
make comparison                     # corpus/COMPARISON.md, corpus/comparison.html, panels in corpus/render
uv build                            # wheel and sdist
```

On Linux with Pango, `libvisio-tools` 0.1.7 or 0.1.11 and `emf2svg` installed, `uv run pytest --cov` works without Docker.
See "libvisio version" in the README.

CI runs actionlint, zizmor, ruff, mypy, the tests on Python 3.11 to 3.14 in `Dockerfile.test`, and SonarCloud
for every pull request.

## Visual regression bench

The unit tests check the SVG and the PDF. The bench checks what it looks like:

1. `make azure` downloads the Azure diagrams of `corpus/azure.json` and their SVGs of Visio into the cache.
2. `make visual` renders every drawing of the corpus and of the cache through WeasyPrint and weasyvsdx.
3. It rasterizes each PDF with PDFium at 96 dpi and compares it with the LibreOffice reference. The
   mismatch is the share of the drawing that differs, in percent.
4. An Azure diagram with an SVG of Visio of the size of its first page is compared with it too, through
   `rsvg-convert`. LibreOffice reads the drawing through libvisio and shares its errors; Visio does not.
5. It writes `tools/visual/out/report.html`: LibreOffice, weasyvsdx and Visio side by side, worst first.

`tools/corpus/azure.py visio CHECKOUT` takes the SVG of Visio of each diagram from a checkout of
MicrosoftDocs/architecture-center: the image above the link to the diagram in its article, at the commit
of the checkout.

`make visual ARGS="--only azure"` renders the names that contain `azure`. The bench is a dev tool, not a
CI gate, and LibreOffice no exact reference: it picks its own fonts and breaks words in narrow text
blocks. Judge a change by looking at the drawings it moves, zoomed in. A change that alters renderings
runs `make visual-baseline` and commits `corpus/baseline.json`; `make visual-check` fails when a drawing got
worse than its baseline, or when its SVG of Visio is not in the cache.

A change that alters a rendering also runs `make comparison` and commits `corpus/COMPARISON.md`,
`corpus/comparison.html` and `corpus/render`. GitHub Pages serves the page from the default branch. Edit the
template `tools/visual/comparison.html`, never the page it writes.

Never judge a rendering with poppler (`pdftoppm`, Evince, Okular). Its Splash backend drops WeasyPrint
gradients, and its cairo backend drops soft masks that PDFium and Quartz apply. Use PDFium, which is the
PDF engine of Chrome, and check a disputed case in Quartz (macOS Preview).

A new corpus file needs a license that allows redistribution, and an entry in `corpus/SOURCES.md`.
`make references` exports the LibreOffice references again: run it after adding a drawing, and after a
LibreOffice upgrade of the visual image. Drawings whose license does not allow redistribution go into
`corpus/azure.json` style lists and the cache, never into the repository.

## Pull requests

1. Branch from the default branch as `type/description`, for example `fix/empty-title`.
2. Keep one change per pull request. New behavior comes with tests; a bug fix adds a test that
   fails without it.
3. Write commit messages as [Conventional Commits](https://www.conventionalcommits.org/) without a
   scope: `feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`, `test: ...`, `build: ...`,
   `ci: ...`, `chore: ...`.
4. Sign your commits. The default branch accepts verified signatures only.
5. Add an entry under `## [Unreleased]` in `CHANGELOG.md`, written for users: the release notes
   quote it. Update the README when behavior or configuration changes.

Pull requests are squash-merged once all required checks are green.

## Releases

A maintainer runs the Bump Version workflow. It moves the Unreleased entries into a versioned
section, tags the release, and the Release workflow attests the build and publishes it:
first to PyPI, through Trusted Publishing in the `pypi` environment, then as a GitHub release. If a
publishing job fails, use "Re-run failed jobs": the jobs take the files built once, and PyPI accepts a
file again only with the same content.
