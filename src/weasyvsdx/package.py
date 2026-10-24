"""The XML of a VSDX: its first page, its masters and its styles.

libvisio drops part of what a VSDX holds, and hidden_text.py and gradients.py take that part from the XML
itself. A VSDX is a zip of XML parts; the parts are read within a budget of unpacked bytes, so a zip bomb
stops early.
"""

from __future__ import annotations

import io
import zipfile
import zlib
from collections.abc import Callable, Iterator
from typing import TypeVar
from xml.etree import ElementTree as ET

VISIO = "{http://schemas.microsoft.com/office/visio/2012/main}"
RELATIONSHIP = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PACKAGE = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
MAX_PART = 64 * 1024 * 1024  # bytes of one XML part, unpacked: a zip bomb stops here
MAX_TOTAL = 256 * 1024 * 1024  # bytes of all parts read, unpacked
# zipfile raises EOFError on a cut entry, zlib.error on a broken one, NotImplementedError on an unknown
# compression and RuntimeError on an encrypted one, both RuntimeError, as is RecursionError on shapes nested too deep
ERRORS = (KeyError, ValueError, OSError, EOFError, RuntimeError, zlib.error, zipfile.BadZipFile, ET.ParseError)

# A shape of the page or of a master; the shapes of each master by their ID
Shapes = dict[str, ET.Element]
Result = TypeVar("Result")


class Package:
    """The XML parts of a VSDX, within a budget of unpacked bytes for all of them; the shapes of a master part read once."""

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self.archive = archive
        self.budget = MAX_TOTAL
        self.shapes: dict[str, Shapes] = {}

    def part(self, name: str) -> ET.Element:
        """One part, parsed; KeyError when it is missing, ValueError when it or all parts are too large."""
        size = self.archive.getinfo(name).file_size
        if size > MAX_PART or size > self.budget:
            raise ValueError(f"{name} unpacks to more bytes than the budget allows")
        self.budget -= size
        return ET.fromstring(self.archive.read(name))

    def targets(self, folder: str, part: str) -> dict[str, str]:
        """The targets of the relationships of a part, by their ID."""
        relationships = self.part(f"{folder}/_rels/{part}.rels")
        return {item.get("Id", ""): item.get("Target", "") for item in relationships.iter(PACKAGE)}

    def masters(self) -> dict[str, Shapes]:
        """The shapes of each master by the ID of the master; masters that share a part share its shapes."""
        if "visio/masters/masters.xml" not in self.archive.namelist():
            return {}
        targets = self.targets("visio/masters", "masters.xml")
        masters = {}
        for master in self.part("visio/masters/masters.xml").iter(f"{VISIO}Master"):
            link = master.find(f"{VISIO}Rel")
            target = targets.get(link.get(RELATIONSHIP, "") if link is not None else "")
            if target:
                if target not in self.shapes:
                    self.shapes[target] = {shape.get("ID", ""): shape for shape in self.part(f"visio/masters/{target}").iter(f"{VISIO}Shape")}
                masters[master.get("ID", "")] = self.shapes[target]
        return masters

    def styles(self) -> dict[str, ET.Element]:
        """The style sheets of the document by their ID."""
        if "visio/document.xml" not in self.archive.namelist():
            return {}
        return {style.get("ID", ""): style for style in self.part("visio/document.xml").iter(f"{VISIO}StyleSheet")}

    def colors(self) -> dict[str, str]:
        """The colors the document adds to the palette of Visio, by their index."""
        if "visio/document.xml" not in self.archive.namelist():
            return {}
        return {color.get("IX", ""): color.get("RGB", "") for color in self.part("visio/document.xml").iter(f"{VISIO}ColorEntry")}

    def first_page(self) -> ET.Element:
        """The first page that is no background page, the page libvisio writes first."""
        return self._content(self._first_entry())

    def background_ids(self) -> set[str]:
        """The IDs of the shapes of the background pages of the first page, which libvisio draws before it."""
        entries = {page.get("ID", ""): page for page in self.part("visio/pages/pages.xml").iter(f"{VISIO}Page")}
        ids: set[str] = set()
        seen = set()
        back = self._first_entry().get("BackPage")
        while back in entries and back not in seen:
            seen.add(back)
            ids.update(shape.get("ID", "") for shape in self._content(entries[back]).iter(f"{VISIO}Shape"))
            back = entries[back].get("BackPage")
        return ids

    def _first_entry(self) -> ET.Element:
        for page in self.part("visio/pages/pages.xml").iter(f"{VISIO}Page"):
            if page.get("Background") != "1" and page.find(f"{VISIO}Rel") is not None:
                return page
        raise KeyError("no foreground page")

    def _content(self, entry: ET.Element) -> ET.Element:
        """The part of a page of pages.xml."""
        link = entry.find(f"{VISIO}Rel")
        targets = self.targets("visio/pages", "pages.xml")
        return self.part(f"visio/pages/{targets[link.get(RELATIONSHIP, '') if link is not None else '']}")


def read(document: bytes, reader: Callable[[Package], Result]) -> Result | None:
    """What reader takes from the package of a VSDX; None for another drawing or one that does not read."""
    if not zipfile.is_zipfile(io.BytesIO(document)):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(document)) as archive:
            return reader(Package(archive))
    except ERRORS:
        return None


def master_shape(shape: ET.Element, master: Shapes | None) -> ET.Element | None:
    """The shape of the master that a shape of the page inherits from: the one it names, else the first."""
    if not master:
        return None
    if shape.get("MasterShape"):
        return master.get(shape.get("MasterShape", ""))
    return next(iter(master.values())) if shape.get("Master") else None


def page_shapes(package: Package) -> Iterator[tuple[ET.Element, ET.Element | None]]:
    """Each shape of the first page in document order, with the shape of a master it inherits from.

    A group of a master whose shapes the page does not list stands for the shapes of the master, which
    libvisio draws: each comes as its own master shape.
    """
    masters = package.masters()
    shapes = package.first_page().find(f"{VISIO}Shapes")

    def walk(shapes: ET.Element, master: Shapes | None, inherited: bool = False) -> Iterator[tuple[ET.Element, ET.Element | None]]:
        for shape in shapes.findall(f"{VISIO}Shape"):
            own_master = masters.get(shape.get("Master", "")) if shape.get("Master") else master
            # A shape of a master that the page does not list is its own master shape
            inherits = shape if inherited else master_shape(shape, own_master)
            yield shape, inherits
            children = shape.find(f"{VISIO}Shapes")
            if children is not None:
                yield from walk(children, own_master)
                continue
            master_children = inherits.find(f"{VISIO}Shapes") if inherits is not None and inherits is not shape else None
            if master_children is not None:
                yield from walk(master_children, own_master, inherited=True)

    if shapes is not None:
        yield from walk(shapes, None)
