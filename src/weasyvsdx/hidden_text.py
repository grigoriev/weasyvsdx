"""Text that Visio hides.

A shape hides its text with the HideText cell, and the icons of the Azure stencils all do: their name stays
out of the drawing. A shape that clears the text of its master hides that text too. libvisio reads neither,
and writes the name of each icon under it. A VSDX holds both in the XML of its first page and its masters.

The shapes of the XML and the text objects of vsd2raw come in nearly one order, but not quite: libvisio leaves
out some text of a master and writes some it should not. The two lists of texts are aligned as sequences, and
a text object goes only where it matches a shape of the same text that hides it. A VSD, or a VSDX that does
not read, keeps all its text.
"""

from __future__ import annotations

import difflib
import io
import re
import zipfile
from xml.etree import ElementTree as ET

VISIO = "{http://schemas.microsoft.com/office/visio/2012/main}"
RELATIONSHIP = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PACKAGE = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
MAX_PART = 64 * 1024 * 1024  # bytes of one XML part, unpacked: a zip bomb stops here
SPACE = re.compile(r"\s+")

# A shape of the page or of a master; the shapes of each master by their ID
Shapes = dict[str, ET.Element]


def normalized(text: str) -> str:
    """The text without its white space: libvisio and the XML break and pad text differently."""
    return SPACE.sub("", text)


def _part(archive: zipfile.ZipFile, name: str) -> ET.Element:
    """One XML part of the package, parsed; KeyError when it is missing, ValueError when it is too large."""
    if archive.getinfo(name).file_size > MAX_PART:
        raise ValueError(f"{name} unpacks to more than {MAX_PART} bytes")
    return ET.fromstring(archive.read(name))


def _targets(archive: zipfile.ZipFile, folder: str, part: str) -> dict[str, str]:
    """The targets of the relationships of a part, by their ID."""
    relationships = _part(archive, f"{folder}/_rels/{part}.rels")
    return {item.get("Id", ""): item.get("Target", "") for item in relationships.iter(PACKAGE)}


def _masters(archive: zipfile.ZipFile) -> dict[str, Shapes]:
    """The shapes of each master by the ID of the master."""
    if "visio/masters/masters.xml" not in archive.namelist():
        return {}
    targets = _targets(archive, "visio/masters", "masters.xml")
    masters = {}
    for master in _part(archive, "visio/masters/masters.xml").iter(f"{VISIO}Master"):
        link = master.find(f"{VISIO}Rel")
        target = targets.get(link.get(RELATIONSHIP, "") if link is not None else "")
        if target:
            masters[master.get("ID", "")] = {shape.get("ID", ""): shape for shape in _part(archive, f"visio/masters/{target}").iter(f"{VISIO}Shape")}
    return masters


def _first_page(archive: zipfile.ZipFile) -> ET.Element:
    """The first page that is no background page, the page libvisio writes first."""
    targets = _targets(archive, "visio/pages", "pages.xml")
    for page in _part(archive, "visio/pages/pages.xml").iter(f"{VISIO}Page"):
        link = page.find(f"{VISIO}Rel")
        if page.get("Background") != "1" and link is not None:
            return _part(archive, f"visio/pages/{targets[link.get(RELATIONSHIP, '')]}")
    raise KeyError("no foreground page")


def _text(shape: ET.Element | None) -> str | None:
    """The text of a shape, None when it has no text element."""
    element = shape.find(f"{VISIO}Text") if shape is not None else None
    return None if element is None else "".join(element.itertext())


def _hide(shape: ET.Element, master: ET.Element | None) -> bool:
    """Whether the HideText cell of the shape, else of its master, is set."""
    for source in (shape, master):
        if source is None:
            continue
        for cell in source.findall(f"{VISIO}Cell"):
            if cell.get("N") == "HideText":
                return cell.get("V") == "1"
    return False


class _Walker:
    """The texts of the shapes of a page in document order, each with whether Visio hides it."""

    def __init__(self, masters: dict[str, Shapes]) -> None:
        self.masters = masters
        self.texts: list[tuple[str, bool]] = []

    def walk(self, shapes: ET.Element, master: Shapes | None, inherited: bool = False) -> None:
        for shape in shapes.findall(f"{VISIO}Shape"):
            own_master = self.masters.get(shape.get("Master", "")) if shape.get("Master") else master
            # A shape of a master that the page does not list is its own master shape
            if inherited:
                master_shape: ET.Element | None = shape
            elif shape.get("MasterShape") and own_master is not None:
                master_shape = own_master.get(shape.get("MasterShape", ""))
            elif shape.get("Master") and own_master:
                master_shape = next(iter(own_master.values()))
            else:
                master_shape = None
            self.add(shape, master_shape)
            children = shape.find(f"{VISIO}Shapes")
            if children is not None:
                self.walk(children, own_master)
                continue
            # A group of a master whose shapes the page does not list: libvisio draws those of the master
            master_children = master_shape.find(f"{VISIO}Shapes") if master_shape is not None and master_shape is not shape else None
            if master_children is not None:
                self.walk(master_children, own_master, inherited=True)

    def add(self, shape: ET.Element, master_shape: ET.Element | None) -> None:
        own = _text(shape)
        inherited = _text(master_shape) if master_shape is not shape else None
        text = own if own and normalized(own) else inherited
        if text is None or not normalized(text):
            return
        # An empty text of its own clears the text of the master, which libvisio writes anyway
        cleared = own is not None and not normalized(own)
        self.texts.append((normalized(text), cleared or _hide(shape, master_shape)))


def shape_texts(document: bytes) -> list[tuple[str, bool]] | None:
    """The texts of the shapes of the first page of a VSDX, each with whether Visio hides it; None for another drawing."""
    if not zipfile.is_zipfile(io.BytesIO(document)):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(document)) as archive:
            walker = _Walker(_masters(archive))
            shapes = _first_page(archive).find(f"{VISIO}Shapes")
            if shapes is not None:
                walker.walk(shapes, None)
    # RecursionError: shapes nested deeper than the stack of the walk
    except (KeyError, ValueError, OSError, RecursionError, zipfile.BadZipFile, ET.ParseError):
        return None
    return walker.texts


def hidden_indexes(shapes: list[tuple[str, bool]], texts: list[str]) -> frozenset[int]:
    """The indexes of the texts that match, in an alignment of both lists, a shape that hides the same text."""
    matcher = difflib.SequenceMatcher(None, [text for text, _ in shapes], [normalized(text) for text in texts], autojunk=False)
    return frozenset(index + offset for start, index, size in matcher.get_matching_blocks() for offset in range(size) if shapes[start + offset][1])
