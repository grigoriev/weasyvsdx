# Corpus sources and licenses

The corpus is test data for the tests and the visual regression bench. It is not part of the weasyvsdx
package. Each file keeps the license of its source, listed below. The MIT license of this repository does
not cover these files.

The reference PNGs in `reference/libreoffice/` are renderings of the drawing of the same name by
LibreOffice Draw 25.2. A rendering carries the license and the attribution of its drawing.
`make references` exports them again in the visual image.

| Path | Files | Source | License |
|---|---|---|---|
| `visio/libvisio/` | 34 | the test drawings of [libvisio](https://github.com/LibreOffice/libvisio), `src/test/data/`, commit `81bf0a4` | MPL-2.0, see [licenses/MPL-2.0.txt](licenses/MPL-2.0.txt) |
| `visio/poi/` | 6 | the test drawings of [Apache POI](https://github.com/apache/poi), `test-data/diagram/`, commit `daab552` | Apache-2.0, see [licenses/Apache-2.0-poi.txt](licenses/Apache-2.0-poi.txt) and [licenses/NOTICE-poi.txt](licenses/NOTICE-poi.txt) |
| `visio/libreoffice/` | 1 | `Visio2013drawing.vsdx` of [LibreOffice](https://github.com/LibreOffice/core), `writerperfect/qa/unit/data/draw/libvisio/pass/`, commit `529dfc7` | MPL-2.0, see [licenses/MPL-2.0.txt](licenses/MPL-2.0.txt) |

`libvisio/recursion-cycle.vsdx` and `libvisio/tab-short-prefix.vsdx` are broken on purpose: libvisio
crashes on the first and refuses the second. They test that a drawing which does not convert renders as a
broken image.

## Azure diagrams, outside the repository

`azure.json` lists the 250 Visio diagrams that the documentation of the
[Azure Architecture Center](https://github.com/MicrosoftDocs/architecture-center) links on
`arch-center.azureedge.net`, from commit `d28611d`, each with its SHA-256. The repository holds the list
only, not the files:

- The diagrams are not in the repository of the documentation, so its CC-BY-4.0 license does not clearly
  cover them.
- The Azure icons inside them may be copied for architecture diagrams, training and documentation only,
  see the [terms of the icons](https://learn.microsoft.com/en-us/azure/architecture/icons/).

`make azure` downloads the diagrams into the cache (`WEASYVSDX_CACHE`, by default `~/.cache/weasyvsdx`),
and `make references` writes their references there too. Neither leaves the machine.
