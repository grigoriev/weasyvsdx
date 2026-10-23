"""Rasterize with PDFium and measure how much two renderings differ.

Never judge with poppler: Splash drops WeasyPrint gradients, and cairo drops soft masks that PDFium
and Quartz apply. PDFium is the PDF engine of Chrome. Check disputed cases in Quartz (macOS Preview).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageFilter

METRIC_DPI = 96
PAD = 4  # px around the ink box


def raster(pdf: Path, dpi: int = METRIC_DPI) -> Image.Image | None:
    """Page 1 through PDFium, on white."""
    if not pdf.exists():
        return None
    document = pdfium.PdfDocument(str(pdf))
    page = document[0]
    bitmap = page.render(scale=dpi / 72, fill_color=(255, 255, 255, 255))
    try:
        image: Image.Image = bitmap.to_pil().convert("RGB")
        return image
    finally:
        # Children first: on PyPy a page finalized after its document fails an assertion
        for item in (bitmap, page, document):
            item.close()


def ink_box(images: list[Image.Image]) -> tuple[int, int, int, int] | None:
    """The union of the boxes that hold a pixel darker than 250 in any channel."""
    boxes = []
    for image in images:
        mask = (np.asarray(image).min(axis=2) < 250).astype(np.uint8) * 255
        box = Image.fromarray(mask).getbbox()
        if box:
            boxes.append(box)
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def padded(box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """The box plus a margin, inside the image: a crop past the edge fills with black, which reads as ink."""
    return max(box[0] - PAD, 0), max(box[1] - PAD, 0), min(box[2] + PAD, size[0]), min(box[3] + PAD, size[1])


def mismatch(a: Image.Image, b: Image.Image) -> float:
    """How much of the drawing differs, in percent, after a small blur that forgives antialiasing and raster versus vector.

    The larger of two measures: the share of ink pixels that differ visibly, and the difference in ink
    weighted by its strength. The second catches pale fills that are lost: light grey on white is a small
    difference per pixel, over the whole drawing.
    """
    first = np.asarray(a.filter(ImageFilter.BoxBlur(1)), dtype=np.int16)
    second = np.asarray(b.filter(ImageFilter.BoxBlur(1)), dtype=np.int16)
    ink = (first.min(axis=2) < 250) | (second.min(axis=2) < 250)
    if not ink.any():
        return 0.0
    delta = np.abs(first - second).max(axis=2)
    share = float((delta[ink] > 32).sum()) / float(ink.sum())
    strength = 255 - np.minimum(first.min(axis=2), second.min(axis=2))
    weighted = float(delta[ink].sum()) / max(float(strength[ink].sum()), 1.0)
    return float(min(max(share, weighted), 1.0) * 100)
