"""The drawings of the bench: the corpus files of the repository, then the Azure diagrams of the cache.

corpus/index.json lists the corpus files, corpus/azure.json the Azure diagrams, which make azure downloads
into WEASYVSDX_CACHE. Each drawing has a LibreOffice reference: in corpus/reference/libreoffice for a corpus
file, in the cache for an Azure diagram, whose icons may not be copied into the repository.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
# The media type of the data URL of a drawing, by its suffix
MEDIA_TYPES = {".vsdx": "application/vnd.ms-visio.drawing", ".vsdm": "application/vnd.ms-visio.drawing.macroEnabled.12", ".vsd": "application/vnd.visio"}


@dataclass(frozen=True)
class Drawing:
    name: str
    group: str
    path: Path
    reference: Path

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES[self.path.suffix.lower()]


def cache() -> Path:
    return Path(os.environ.get("WEASYVSDX_CACHE") or Path.home() / ".cache" / "weasyvsdx")


def drawings(only: str = "") -> list[Drawing]:
    """Every drawing whose name contains only. An Azure diagram missing from the cache is left out."""
    items = [Drawing(item["name"], item["group"], CORPUS / "visio" / item["source"], CORPUS / "reference" / "libreoffice" / f"{item['name']}.png") for item in json.loads((CORPUS / "index.json").read_text())]
    azure = cache() / "azure"
    items += [
        Drawing(item["name"], "azure", azure / f"{item['name']}.vsdx", cache() / "reference" / "libreoffice" / f"{item['name']}.png") for item in json.loads((CORPUS / "azure.json").read_text()) if (azure / f"{item['name']}.vsdx").exists()
    ]
    return [drawing for drawing in items if only in drawing.name]
