# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- weasyvsdx supports libvisio 0.1.11, the latest, besides 0.1.7. The tests run with both.
- Each shape of a VSDX fills with the colors of its XML: libvisio 0.1.8 and later fill them with the colors
  of the theme over their own. A pattern draws its lines in its foreground over its background, and a
  fill of the theme draws white, as Visio draws most of them.

### Changed

- `LIBVISIO` is the tuple of the releases weasyvsdx is tested with, `("0.1.7", "0.1.11")`, and `install()`
  warns on any other.

## [0.1.0] - 2026-10-24

### Added

- Visio drawings (VSDX, VSDM, VSD and the templates and stencils of Visio) render in WeasyPrint as vector
  SVG: an `<img>`, `<object>` or `<embed>`, a CSS image, an `<image>` inside an SVG. `vsd2xhtml` of
  libvisio draws the first page. An untyped response is a drawing by the suffix of its URL, before or after
  a redirect.
- The text of a drawing wraps and aligns as in Visio: each text block is HTML in a `<foreignObject>`, from
  the output of `vsd2raw`, with its padding, vertical alignment, rotation, paragraphs, bullets and fonts,
  and the character scale of Visio, which widens the glyphs.
- Arrowheads take their own shape and size, and a line under one ends at its base, as in Visio. A hollow
  one hides the line under it.
- A shape on a hidden or non-printing layer is left out, as in Visio.
- The text a shape of a VSDX hides is left out: the names of the Azure icons no longer show under them.
- Black behind dark text, which libvisio reads from a palette color, draws white: labels no longer show as
  black bars.
- A text with a line break of Visio (U+2028) shows, broken at it, instead of going missing.
- A bitmap inside an EMF that Office draws flipped no longer shows mirrored.
- A fill pattern draws as hatch lines, on the fill color where it has one, instead of black.
- A shape of a VSDX that fills with a gradient of Visio 2013 or later gets it, linear or radial, instead of
  black: the icons of Azure show in color.
- A shape of a VSDX that inherits its geometry from a master group draws, from the XML of the master:
  libvisio drew nothing for it, and parts of the Azure icons went missing.
- A text block of no width or height is as wide and as high as its text and never wraps, as in Visio.
- A path that libvisio writes without a leading moveto starts at the end of its first segment, not at the
  corner of the page.
- EMF images become SVG through `emf2svg-conv`, and so does the EMF that Office puts inside a WMF image,
  and the picture an embedded OLE object shows.
- The tools run in processes of their own, with a timeout and, on Linux, limits on memory and output.
  The EMF images of a page share one timeout.
  A drawing that does not convert renders as a broken image.
- A drawing that libvisio draws as a page of no size renders as a broken image.
- `install()` warns when `vsd2xhtml` reports another libvisio than 0.1.7, the release weasyvsdx is tested
  with: 0.1.8 to 0.1.11 fill the shapes of a VSDX with the colors of its theme over their own.
- A font of Microsoft that the system lacks falls back to its free replacement: Calibri to Carlito, Cambria to
  Caladea, Segoe UI to Selawik.
- A comparison page on GitHub Pages shows each drawing of the corpus in LibreOffice, as libvisio writes it,
  and in weasyvsdx.
- The bench also compares the Azure diagrams with the SVG that Visio exported for their article.
  LibreOffice reads them through libvisio and shares its errors.
