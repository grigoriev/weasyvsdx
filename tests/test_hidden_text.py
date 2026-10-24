"""Text that Visio hides."""

from __future__ import annotations

import io
import zipfile
import zlib

import pytest
from helpers import vsdx

from weasyvsdx import package
from weasyvsdx.hidden_text import hidden_indexes, normalized, shape_texts

HIDE = "<Cell N='HideText' V='1'/>"
SHOW = "<Cell N='HideText' V='0'/>"


def test_the_texts_of_the_shapes_and_whether_they_hide() -> None:
    page = (
        f"<Shape ID='1'><Text>Label one</Text></Shape><Shape ID='2'>{HIDE}<Text>Hidden</Text></Shape><Shape ID='3'><Shapes><Shape ID='4'><Text>In a group</Text></Shape></Shapes></Shape><Shape ID='5'/><Shape ID='6'><Text>  </Text></Shape>"
    )
    assert shape_texts(vsdx(page)) == [("Labelone", False), ("Hidden", True), ("Inagroup", False)]


def test_the_text_and_hide_text_of_a_master() -> None:
    master = f"<Shape ID='5'>{HIDE}<Text>Virtual Machine</Text><Shapes><Shape ID='6'><Text>Inner</Text></Shape></Shapes></Shape>"
    page = (
        # The text of the master, hidden by it
        "<Shape ID='1' Master='2'/>"
        # Shown by the shape itself
        f"<Shape ID='2' Master='2'>{SHOW}</Shape>"
        # Cleared by an empty text of its own, which libvisio fills from the master
        f"<Shape ID='3' Master='2'>{SHOW}<Text/></Shape>"
        # Its own text, and a shape of the master it lists
        f"<Shape ID='4' Master='2'>{SHOW}<Text>VM 1</Text><Shapes><Shape ID='7' MasterShape='6'/></Shapes></Shape>"
        # A master that is missing
        "<Shape ID='8' Master='9'><Text>Own</Text></Shape>"
    )
    assert shape_texts(vsdx(page, master)) == [
        # HideText hides the text of its own shape only
        ("VirtualMachine", True),
        ("Inner", False),
        ("VirtualMachine", False),
        ("Inner", False),
        ("VirtualMachine", True),
        ("Inner", False),
        ("VM1", False),
        ("Inner", False),
        ("Own", False),
    ]


def test_a_drawing_that_does_not_read_keeps_its_text() -> None:
    assert shape_texts(b"\xd0\xcf\x11\xe0 a VSD") is None
    broken = io.BytesIO()
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("visio/pages/pages.xml", "<not xml")
    assert shape_texts(broken.getvalue()) is None
    # A package with only background pages, and a page with no shapes
    assert shape_texts(vsdx("", foreground=False)) is None
    assert shape_texts(vsdx(None)) == []


def test_shapes_nested_past_the_stack_keep_the_text() -> None:
    depth = 5000
    nested = "<Shape ID='1'><Shapes>" * depth + "<Shape ID='2'><Text>deep</Text></Shape>" + "</Shapes></Shape>" * depth
    assert shape_texts(vsdx(nested)) is None


def test_masters_that_share_a_part_read_it_once(monkeypatch: pytest.MonkeyPatch) -> None:
    master = f"<Shape ID='5'>{HIDE}<Text>Icon</Text></Shape>"
    many = vsdx("<Shape ID='1' Master='2'/>", master, copies=50)
    # Room for each part once: a second read of the master would pass the budget
    with zipfile.ZipFile(io.BytesIO(many)) as archive:
        total = sum(item.file_size for item in archive.infolist())
    monkeypatch.setattr(package, "MAX_TOTAL", total)
    assert shape_texts(many) == [("Icon", True)]


@pytest.mark.parametrize("error", [EOFError("cut"), zlib.error("broken"), NotImplementedError("method"), RuntimeError("encrypted")])
def test_an_entry_that_does_not_unpack_keeps_the_text(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def fail(self: zipfile.ZipFile, name: str) -> bytes:
        raise error

    document = vsdx("<Shape ID='1'><Text>a</Text></Shape>")
    monkeypatch.setattr(zipfile.ZipFile, "read", fail)
    assert shape_texts(document) is None


def test_a_part_too_large_to_unpack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(package, "MAX_PART", 10)
    assert shape_texts(vsdx("<Shape ID='1'><Text>a</Text></Shape>")) is None


def test_only_matching_hidden_texts_go() -> None:
    shapes = [("User", True), ("APIManagement", True), ("Appenvironment", False), ("User", False), ("Order", True)]
    # libvisio writes the hidden User, leaves out API Management, and writes a text the XML lacks
    texts = ["User", "App environment", "User", "Field 1", "Shipment"]
    assert hidden_indexes(shapes, texts) == frozenset({0})
    assert hidden_indexes([], texts) == frozenset()


def test_lists_that_agree_pair_by_position() -> None:
    assert hidden_indexes([("a", False), ("a", True)], ["a", " a "]) == frozenset({1})
    assert hidden_indexes([("a", False)], ["a"]) == frozenset()


def test_an_alignment_past_its_budget_keeps_all_text() -> None:
    # Many equal texts would cost the product of both lengths
    shapes = [("a", True)] * 1001
    texts = ["a"] * 1000 + ["b"]
    assert hidden_indexes(shapes, texts) == frozenset()


def test_normalized_drops_white_space() -> None:
    assert normalized(" a b\n\tc ") == "abc"
