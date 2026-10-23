"""Write corpus/COMPARISON.md and corpus/comparison.html: each corpus drawing in LibreOffice, libvisio and weasyvsdx.

Usage: comparison.py

Run it through make comparison: the bench writes the PDFs of weasyvsdx and of the SVG of vsd2xhtml as it
is (--plain) first. This script exports the PDFs of LibreOffice when tools/visual/out/libreoffice lacks
them, and rasterizes all three at SCALE times 96 dpi.

Only the drawings of the repository go on the page. The Azure diagrams stay in the cache: their icons may
not be redistributed, nor may renderings of them.

Every panel is cropped to the same box, the ink of all three renderings, so they line up pixel for pixel.
The panels go into corpus/render as lossless WebP. COMPARISON.md shows them in the repository, and
comparison.html, the template next to this script with the data put in, on GitHub Pages.
"""

from __future__ import annotations

import hashlib
import html
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from drawings import CORPUS, ROOT, Drawing, drawings
from imaging import METRIC_DPI, ink_box, raster
from make_references import export_all
from PIL import Image

PAGE = CORPUS / "COMPARISON.md"
HTML_PAGE = CORPUS / "comparison.html"
HTML_TEMPLATE = Path(__file__).with_name("comparison.html")
PAGES_URL = "https://grigoriev.github.io/weasyvsdx/corpus/comparison.html"
WIDTH = 240  # px of each panel in COMPARISON.md; a click opens the full image
SCALE = 2  # the panels have this many pixels per CSS px
PAD = 8  # px around the ink, at SCALE
GROUPS = {"libreoffice": "LibreOffice tests", "libvisio": "libvisio tests", "poi": "Apache POI tests"}
VISUAL = ROOT / "tools" / "visual" / "out"
# The PDFs of each rendering: the bench writes libvisio (--plain) and weasyvsdx, this script LibreOffice
PDFS = {"libreoffice": VISUAL / "libreoffice", "libvisio": VISUAL / "libvisio" / "pdf", "weasyvsdx": VISUAL / "weasyvsdx" / "pdf"}
RENDERERS = {"libreoffice": "LibreOffice", "libvisio": "libvisio", "weasyvsdx": "weasyvsdx"}
ROWS = {"libvisio": VISUAL / "libvisio" / "rows.json", "weasyvsdx": VISUAL / "weasyvsdx" / "rows.json"}
Box = tuple[int, int, int, int]


def corpus() -> list[Drawing]:
    """The drawings of the repository, without the Azure diagrams of the cache."""
    return [drawing for drawing in drawings() if drawing.group != "azure"]


def digest(drawing: Drawing) -> str:
    return hashlib.sha256(drawing.path.read_bytes()).hexdigest()


def export_libreoffice(items: list[Drawing]) -> None:
    """The PDF of LibreOffice for each drawing that lacks one: the same page as its PNG reference, in vector.

    Next to each PDF lies the SHA-256 of its drawing: a drawing that changed gets its PDF anew.
    """
    target = PDFS["libreoffice"]
    missing = [drawing for drawing in items if not (target / f"{drawing.name}.pdf").exists() or not (target / f"{drawing.name}.sha256").exists() or (target / f"{drawing.name}.sha256").read_text() != digest(drawing)]
    for drawing in missing:
        (target / f"{drawing.name}.pdf").unlink(missing_ok=True)
    if not missing:
        return
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        inputs = []
        for drawing in missing:
            path = folder / f"{drawing.name}{drawing.path.suffix}"
            shutil.copyfile(drawing.path, path)
            inputs.append(path)
        export_all(folder, inputs, "pdf")
        for drawing in missing:
            pdf = folder / "pdf" / f"{drawing.name}.pdf"
            if pdf.exists():
                shutil.copyfile(pdf, target / f"{drawing.name}.pdf")
                (target / f"{drawing.name}.sha256").write_text(digest(drawing))


def save(image: Image.Image, key: str, name: str) -> None:
    # Lossless: a lossy panel would show artifacts no renderer drew; method 6 packs it tightest
    image.save(CORPUS / "render" / key / f"{name}.webp", "WEBP", lossless=True, quality=100, method=6)


def panels(drawing: Drawing) -> tuple[int, int] | None:
    """Write the panels of the drawing, all cropped to the ink of the three; their size, or None without any."""
    rendered = {key: raster(pdfs / f"{drawing.name}.pdf", METRIC_DPI * SCALE) for key, pdfs in PDFS.items()}
    for key in PDFS:
        (CORPUS / "render" / key / f"{drawing.name}.webp").unlink(missing_ok=True)
    images = {key: image for key, image in rendered.items() if image is not None}
    if not images:
        return None
    # The pages differ by rounding: points against pixels. All share the size of the smallest.
    size = (min(image.width for image in images.values()), min(image.height for image in images.values()))
    images = {key: image.crop((0, 0, *size)) for key, image in images.items()}
    box: Box | None = ink_box(list(images.values()))
    if box is None:
        return None
    box = (max(box[0] - PAD, 0), max(box[1] - PAD, 0), min(box[2] + PAD, size[0]), min(box[3] + PAD, size[1]))
    for key, image in images.items():
        save(image.crop(box), key, drawing.name)
    return (box[2] - box[0], box[3] - box[1])


def mismatches() -> dict[str, dict[str, float | None]]:
    """The mismatch of each drawing against the LibreOffice reference, per rendering, from the bench."""
    result: dict[str, dict[str, float | None]] = {}
    for key, path in ROWS.items():
        if path.exists():
            for row in json.loads(path.read_text()):
                result.setdefault(row["name"], {})[key] = row["mismatch"]
    return result


def cell(name: str, key: str) -> str:
    path = f"render/{key}/{name}.webp"
    if not (CORPUS / path).exists():
        return "n/a"
    return f'<a href="{path}"><img src="{path}" width="{WIDTH}" alt="{name} in {RENDERERS[key]}"></a>'


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:g} %"


def markdown(items: list[Drawing], measured: dict[str, dict[str, float | None]], version: str) -> str:
    sections = []
    for group, title in GROUPS.items():
        members = [drawing for drawing in items if drawing.group == group]
        if not members:
            continue
        sections.append(f"## {title}\n")
        for drawing in members:
            numbers = measured.get(drawing.name, {})
            source = drawing.path.relative_to(CORPUS).as_posix()
            header = "| " + " | ".join(RENDERERS.values()) + " |"
            row = "| " + " | ".join(cell(drawing.name, key) for key in RENDERERS) + " |"
            sections.append(f"### {drawing.name}\n\n[`{source}`]({source}) · mismatch with LibreOffice: libvisio {percent(numbers.get('libvisio'))}, weasyvsdx {percent(numbers.get('weasyvsdx'))}\n\n{header}\n|---|---|---|\n{row}\n")
    intro = (
        "# Corpus comparison\n\n"
        "<!-- Written by make comparison (tools/visual/comparison.py). Do not edit by hand. -->\n\n"
        f"Each drawing of the corpus in three renderings: LibreOffice, its PDF export; libvisio, the SVG of `vsd2xhtml` as it "
        f"is in WeasyPrint {version}; and weasyvsdx in WeasyPrint {version}. All are PDFium rasterizations at {METRIC_DPI * SCALE} dpi, "
        f"{SCALE}x the CSS px, cropped to the ink of the three, so they line up pixel for pixel. The mismatch comes from the bench, "
        "against the PNG export of LibreOffice, which is no exact reference for text. The Azure diagrams of the bench are "
        f"not here: their icons may not be redistributed. Click a panel for its full size. The interactive page: <{PAGES_URL}>.\n\n"
    )
    return intro + "\n".join(sections)


def html_page(items: list[Drawing], sizes: dict[str, tuple[int, int]], measured: dict[str, dict[str, float | None]], version: str) -> str:
    """The interactive page: the template with the panels and the mismatch of every drawing as JSON."""
    entries: list[dict[str, Any]] = []
    for drawing in items:
        size = sizes.get(drawing.name, (0, 0))
        entries.append(
            {
                "name": drawing.name,
                "group": drawing.group,
                "source": drawing.path.relative_to(CORPUS).as_posix(),
                # The page lays the panels out in CSS px, SCALE pixels each
                "width": size[0] // SCALE,
                "height": size[1] // SCALE,
                "panels": {key: f"render/{key}/{drawing.name}.webp" if (CORPUS / "render" / key / f"{drawing.name}.webp").exists() else None for key in RENDERERS},
                "mismatch": measured.get(drawing.name, {}),
            }
        )
    data = {
        "intro": (
            f"Each drawing of the corpus in LibreOffice, its PDF export; libvisio, the SVG of vsd2xhtml as it is in WeasyPrint {version}; "
            f"and weasyvsdx in WeasyPrint {version}. The panels are PDFium rasterizations, cropped to the ink of the three, so they line "
            "up pixel for pixel. The mismatch against LibreOffice comes from the bench; LibreOffice is no exact reference for text. "
            "The Azure diagrams of the bench are not here: their icons may not be redistributed. Click a panel to swipe between "
            "two renderers at full size."
        ),
        "renderers": RENDERERS,
        "groups": GROUPS,
        "items": entries,
    }
    # "</" inside the JSON would end the script element
    return HTML_TEMPLATE.read_text().replace("/*DATA*/", json.dumps(data).replace("</", "<\\/"))


def main() -> int:
    for key in RENDERERS:
        (CORPUS / "render" / key).mkdir(parents=True, exist_ok=True)
    items = corpus()
    export_libreoffice(items)
    sizes = {}
    failed = False
    for drawing in items:
        size = panels(drawing)
        if size is not None:
            sizes[drawing.name] = size
        # A drawing with a reference converts in LibreOffice, so it must have all its panels; one without is
        # broken on purpose, such as recursion-cycle.vsdx, and has none
        drawn = [key for key in RENDERERS if (CORPUS / "render" / key / f"{drawing.name}.webp").exists()]
        if drawing.reference.exists() and len(drawn) != len(RENDERERS):
            failed = True
            print(f"{drawing.name}: no panel for {', '.join(key for key in RENDERERS if key not in drawn)}")
    baseline = CORPUS / "baseline.json"
    version = json.loads(baseline.read_text()).get("weasyprint", "") if baseline.exists() else ""
    measured = mismatches()
    PAGE.write_text(markdown(items, measured, html.escape(version)))
    HTML_PAGE.write_text(html_page(items, sizes, measured, version))
    print(f"wrote {PAGE.relative_to(ROOT)} and {HTML_PAGE.relative_to(ROOT)}")
    # A missing panel would leave the page incomplete
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
