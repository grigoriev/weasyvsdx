"""Export the first page of each drawing with LibreOffice Draw, as the reference of the bench.

Usage: make_references.py [--only TEXT]

LibreOffice imports Visio through libvisio too, and it is what weasyprint-service converted Visio drawings
with before. Its PNG export draws the whole first page at 96 dpi, at most 2048 px on its long side. Run it
through make references: the visual image has LibreOffice and the fonts of the service.

All drawings go through one LibreOffice, which is fast. A drawing that crashes it ends the run for those
after it, so each drawing without a PNG then gets a LibreOffice of its own.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from drawings import Drawing, drawings

TIMEOUT = 120  # seconds per drawing


def export(folder: Path, inputs: list[Path], kind: str = "png") -> None:
    """Each input as kind, png or pdf, into folder/kind, by one LibreOffice."""
    command = ["soffice", f"-env:UserInstallation=file://{folder}/profile", "--headless", "--convert-to", kind, "--outdir", str(folder / kind), *map(str, inputs)]
    try:
        subprocess.run(command, check=False, timeout=TIMEOUT * len(inputs), capture_output=True)
    except subprocess.TimeoutExpired:
        print(f"LibreOffice took more than {TIMEOUT} s per drawing, for {len(inputs)} drawings")


def export_all(folder: Path, inputs: list[Path], kind: str = "png") -> None:
    """Each input as kind into folder/kind: all in one LibreOffice, then one each for those it left out."""
    export(folder, inputs, kind)
    for path in inputs:
        if not (folder / kind / f"{path.stem}.{kind}").exists():
            export(folder, [path], kind)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="", help="export only the names that contain this text")
    args = parser.parse_args()
    items = drawings(args.only)
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        # Each drawing under its corpus name: two sources may share a file name (dwg.vsd, dwg.vsdx)
        inputs: dict[str, tuple[Drawing, Path]] = {}
        for drawing in items:
            path = folder / f"{drawing.name}{drawing.path.suffix}"
            shutil.copyfile(drawing.path, path)
            inputs[drawing.name] = (drawing, path)
        export_all(folder, [path for _, path in inputs.values()])
        missing = lost = 0
        for name, (drawing, _) in inputs.items():
            png = folder / "png" / f"{name}.png"
            if not png.exists():
                print(f"{name}: LibreOffice exported nothing")
                lost += drawing.reference.exists()
                # A reference of an earlier LibreOffice would compare with a drawing this one cannot read
                drawing.reference.unlink(missing_ok=True)
                missing += 1
                continue
            drawing.reference.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(png, drawing.reference)
    print(f"{len(items) - missing} of {len(items)} references written")
    # The broken drawings of the corpus never had a reference: only a reference that goes fails the run
    if lost:
        print(f"{lost} references removed")
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
