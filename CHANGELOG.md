# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Visio drawings (VSDX, VSDM, VSD and the templates and stencils of Visio) render in WeasyPrint as vector
  SVG: an `<img>`, `<object>` or `<embed>`, a CSS image, an `<image>` inside an SVG. `vsd2xhtml` of
  libvisio draws the first page.
- The text of a drawing wraps and aligns as in Visio: each text block is HTML in a `<foreignObject>`, from
  the output of `vsd2raw`, with its padding, vertical alignment, rotation, paragraphs, bullets and fonts,
  and the character scale of Visio, which widens the glyphs.
- Arrowheads take their own shape and size. A hollow one hides the line under it, as in Visio.
- EMF images become SVG through `emf2svg-conv`, and so does the EMF that Office puts inside a WMF image,
  and the picture an embedded OLE object shows.
- The tools run in processes of their own, with a timeout and, on Linux, limits on memory and output.
  A drawing that does not convert renders as a broken image.
- A font of Microsoft that the system lacks falls back to its free replacement: Calibri to Carlito, Cambria to
  Caladea, Segoe UI to Selawik.
- A comparison page on GitHub Pages shows each drawing of the corpus in LibreOffice, as libvisio writes it,
  and in weasyvsdx.
