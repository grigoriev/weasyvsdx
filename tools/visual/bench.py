"""The visual regression bench: render each drawing with WeasyPrint and weasyvsdx, compare with LibreOffice.

Usage: bench.py [--only TEXT] [--out DIR] [--against FILE | --write-baseline FILE]

1. Each drawing is an <img> with a data URL, on a page of the size of its LibreOffice reference. LibreOffice
   Draw has one page size for a whole document, the largest of its pages, and draws the first page at
   the top left of it, at 96 dpi, shrunk to 2048 px on its long side at most. The <img> sits there too.
2. The PDF is rasterized with PDFium at 96 dpi and compared with the reference (imaging.mismatch).
3. DIR/report.html shows LibreOffice and weasyvsdx side by side, worst mismatch first.

A dev tool, not a CI gate: the numbers guide the eye. LibreOffice is no exact reference either: it lays
out text with its own engine, and two versions of it render some drawings differently.

--write-baseline stores the mismatch of each drawing in FILE; --against compares with it and fails when a
drawing got worse. The Azure diagrams count only where the cache holds them (make azure).
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import weasyprint
from drawings import ROOT, Drawing, drawings
from imaging import METRIC_DPI, ink_box, mismatch, padded, raster
from PIL import Image

import weasyvsdx
from weasyvsdx.convert import Limits
from weasyvsdx.convert import run as run_tool
from weasyvsdx.errors import ConversionError
from weasyvsdx.raw import CALL, points, properties

PANEL = 560  # max panel width in the report, px
LIBREOFFICE_MAX_PX = 2048  # the long side of a PNG export of LibreOffice, at most
# A change of the mismatch below this many points is noise: antialiasing, font hinting
TOLERANCE = 1.0


def page_sizes(drawing: Drawing) -> list[tuple[float, float]]:
    """The width and height of each page of the drawing, in inches, as vsd2raw gives them."""
    tool = str(Path(weasyvsdx.installed() or "vsd2xhtml").with_name("vsd2raw"))
    try:
        with tempfile.TemporaryDirectory() as directory:
            output = run_tool([tool, str(drawing.path)], Path(directory), Limits(timeout=120)).decode(errors="replace")
    except ConversionError:
        return []
    sizes = []
    for line in output.splitlines():
        match = CALL.match(line)
        if match and match.group(1) == "startPage":
            page = properties(match.group(2) or "")
            sizes.append((points(page.get("svg:width")) / 72, points(page.get("svg:height")) / 72))
    return sizes


def width(drawing: Drawing, reference: tuple[int, int]) -> float:
    """The width of the first page in the reference, in px: at 96 dpi, shrunk as LibreOffice shrinks the largest page."""
    sizes = page_sizes(drawing)
    if not sizes:
        return reference[0]
    largest = max(max(size) for size in sizes) * METRIC_DPI
    return sizes[0][0] * METRIC_DPI * min(1.0, LIBREOFFICE_MAX_PX / largest)


def page(drawing: Drawing, size: tuple[int, int], image_width: float) -> str:
    """One page of the size of the reference, the drawing at its top left."""
    data = base64.b64encode(drawing.path.read_bytes()).decode()
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>@page{{size:{size[0]}px {size[1]}px;margin:0}} body{{margin:0}} "
        f'img{{display:block;width:{image_width:.3f}px}}</style></head><body><img src="data:{drawing.media_type};base64,{data}"></body></html>'
    )


class Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage()[:200])


def panel(image: Image.Image, target: Path) -> str:
    if image.width > PANEL:
        image = image.resize((PANEL, max(1, round(image.height * PANEL / image.width))), Image.Resampling.LANCZOS)
    image.save(target, "WEBP", quality=85)
    return f"img/{target.name}"


def run(drawing: Drawing, out: Path, handler: Warnings) -> dict[str, Any]:
    handler.messages = []
    row: dict[str, Any] = {"name": drawing.name, "group": drawing.group, "ms": None, "error": None, "warnings": [], "mismatch": None}
    if not drawing.reference.exists():
        row["error"] = "no reference: LibreOffice exports nothing, or make references has not run"
        return row
    ref = Image.open(drawing.reference).convert("RGB")
    pdf = out / "pdf" / f"{drawing.name}.pdf"
    pdf.unlink(missing_ok=True)
    start = time.perf_counter()
    try:
        pdf.write_bytes(weasyprint.HTML(string=page(drawing, ref.size, width(drawing, ref.size))).write_pdf())
    except Exception as e:  # noqa: BLE001  one broken drawing must not stop the bench
        row["error"] = repr(e)[:300]
    row["ms"] = round((time.perf_counter() - start) * 1000, 1)
    row["warnings"] = handler.messages[:5]
    ours = raster(pdf) if row["error"] is None else None
    if ours is None:
        return row
    # The page of WeasyPrint rounds to whole points, the reference to whole pixels
    ours = ours.crop((0, 0, *ref.size))
    box = ink_box([ours, ref])
    if box is None:
        row["mismatch"] = 0.0
        return row
    box = padded(box, ref.size)
    row["mismatch"] = round(mismatch(ref.crop(box), ours.crop(box)), 1)
    row["panels"] = [panel(ref.crop(box), out / "img" / f"{drawing.name}.libreoffice.webp"), panel(ours.crop(box), out / "img" / f"{drawing.name}.weasyvsdx.webp")]
    return row


STYLE = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#666;--line:#ddd;--bad:#c62828}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#eee;--muted:#aaa;--line:#333;--bad:#ef5350}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif}
h1{font-size:20px}section{border-top:1px solid var(--line);padding:12px 0}
.meta{color:var(--muted)}.bad{color:var(--bad)}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start}
figure{margin:0}figcaption{color:var(--muted);font-size:12px}img{background:#fff;max-width:100%;border:1px solid var(--line)}
"""


def report(rows: list[dict[str, Any]], out: Path) -> None:
    rows = sorted(rows, key=lambda row: -(row["mismatch"] if row["mismatch"] is not None else 101))
    labels = ("LibreOffice", "weasyvsdx")
    sections = []
    for row in rows:
        figures = "".join(f'<figure><img src="{src}" alt=""><figcaption>{label}</figcaption></figure>' for src, label in zip(row.get("panels", []), labels, strict=False))
        value = "n/a" if row["mismatch"] is None else f"{row['mismatch']}%"
        error = f'<span class="bad">{html.escape(row["error"])}</span>' if row["error"] else ""
        warnings = html.escape("; ".join(row["warnings"]))
        sections.append(f'<section><h2>{html.escape(row["name"])}</h2><p class="meta">mismatch {value} · {row["ms"]} ms {error} {warnings}</p><div class="row">{figures}</div></section>')
    measured = sorted(row["mismatch"] for row in rows if row["mismatch"] is not None)
    summary = f"{len(rows)} drawings, {sum(1 for row in rows if row['error'])} errors, median mismatch {measured[len(measured) // 2] if measured else 'n/a'}%"
    head = f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>weasyvsdx bench</title><style>{STYLE}</style></head>'
    body = f'<body><h1>weasyvsdx against LibreOffice</h1><p class="meta">{summary}. Rasterized with PDFium at {METRIC_DPI} dpi.</p>{"".join(sections)}</body></html>'
    (out / "report.html").write_text(head + body)


def inside(path: Path) -> Path:
    """The path, resolved, if it lies inside the repository; the bench writes nowhere else."""
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise SystemExit(f"{path} lies outside {ROOT}")
    return resolved


def write_baseline(path: Path, rows: list[dict[str, Any]]) -> None:
    baseline = {"weasyprint": weasyprint.__version__, "mismatch": {row["name"]: row["mismatch"] for row in rows}}
    path.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n")


def compare(path: Path, rows: list[dict[str, Any]]) -> list[str]:
    """The drawings whose mismatch moved past TOLERANCE since the baseline, worse first; the regressions."""
    baseline = json.loads(path.read_text())
    before: dict[str, float | None] = baseline["mismatch"]
    worse: list[str] = []
    better: list[str] = []
    for row in rows:
        if row["name"] not in before:
            continue
        old, new = before[row["name"]], row["mismatch"]
        if old is None or new is None:
            if old != new:
                (better if new is not None else worse).append(f"{row['name']}: {old} -> {new}")
            continue
        if new - old > TOLERANCE:
            worse.append(f"{row['name']}: {old} -> {new}")
        elif old - new > TOLERANCE:
            better.append(f"{row['name']}: {old} -> {new}")
    print(f"against {path.name} (WeasyPrint {baseline.get('weasyprint')} -> {weasyprint.__version__}):")
    for title, lines in (("worse", worse), ("better", better)):
        print(f"  {title}: {len(lines)}")
        for line in lines:
            print(f"    {line}")
    return worse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="", help="render only the names that contain this text")
    parser.add_argument("--out", type=Path, default=ROOT / "tools" / "visual" / "out")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--against", type=Path, help="compare the mismatch with this baseline")
    group.add_argument("--write-baseline", type=Path, help="store the mismatch in this baseline")
    args = parser.parse_args()
    out = inside(args.out)
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    (out / "img").mkdir(parents=True, exist_ok=True)
    # Time to spare: the bench measures the rendering, not the limits of a service
    print(f"WeasyPrint {weasyprint.__version__}, converter {weasyvsdx.install(timeout=120)}", flush=True)
    handler = Warnings()
    for logger in ("weasyprint", "weasyvsdx"):
        logging.getLogger(logger).addHandler(handler)
    rows = []
    for drawing in drawings(args.only):
        row = run(drawing, out, handler)
        rows.append(row)
        print(f"{row['name']}: mismatch {row['mismatch']} in {row['ms']} ms {row['error'] or ''}", flush=True)
    (out / "rows.json").write_text(json.dumps(rows, indent=1) + "\n")
    report(rows, out)
    print(f"{len(rows)} drawings, report at {out / 'report.html'}")
    if args.write_baseline:
        write_baseline(inside(args.write_baseline), rows)
    if args.against:
        return 1 if compare(inside(args.against), rows) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
