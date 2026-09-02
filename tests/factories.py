"""
Hand-built AcroForm fixtures.

The interesting faults (inline appearance streams, a /V nothing displays, radio
groups) cannot be produced by a well-behaved generator — that is the point of
them. So they are assembled from raw pypdf objects here, and the healthy
reference form comes from reportlab in the tests that need one.
"""

from __future__ import annotations

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

RADIO_FLAG = 1 << 15  # /Ff bit 16: Radio


def _appearance(writer: PdfWriter, inline: bool = False):
    """An empty Form XObject, either registered (correct) or inlined (the fault)."""
    stream = DecodedStreamObject()
    stream.set_data(b"")
    stream[NameObject("/Type")] = NameObject("/XObject")
    stream[NameObject("/Subtype")] = NameObject("/Form")
    stream[NameObject("/BBox")] = ArrayObject([NumberObject(n) for n in (0, 0, 12, 12)])
    return stream if inline else writer._add_object(stream)


def _widget(writer: PdfWriter, parent, states: list[str], as_state: str, inline: bool = False):
    ap_n = DictionaryObject()
    for state in states:
        ap_n[NameObject(state)] = _appearance(writer, inline=inline)
    widget = DictionaryObject()
    widget.update(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject([NumberObject(n) for n in (10, 10, 22, 22)]),
            NameObject("/Parent"): parent,
            NameObject("/AS"): NameObject(as_state),
            NameObject("/AP"): DictionaryObject({NameObject("/N"): ap_n}),
        }
    )
    return writer._add_object(widget)


def _finish(writer: PdfWriter, path: str, fields: ArrayObject, annots: ArrayObject) -> str:
    writer.pages[0][NameObject("/Annots")] = annots
    writer._root_object[NameObject("/AcroForm")] = writer._add_object(
        DictionaryObject({NameObject("/Fields"): fields})
    )
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def radio_group(path: str, value: str = "/pro", selected: str | None = None) -> str:
    """
    A radio group with two widgets, /basic and /pro.

    ``selected`` is the widget whose /AS is on; it defaults to ``value``, which is
    the consistent case. Passing a different one produces the real three-place
    fault: the value names a state no widget displays.
    """
    selected = value if selected is None else selected
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    parent = DictionaryObject()
    parent.update(
        {
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject("plan"),
            NameObject("/Ff"): NumberObject(RADIO_FLAG),
            NameObject("/V"): NameObject(value),
        }
    )
    parent_ref = writer._add_object(parent)
    kids = ArrayObject(
        [
            _widget(writer, parent_ref, [state, "/Off"], state if state == selected else "/Off")
            for state in ("/basic", "/pro")
        ]
    )
    parent[NameObject("/Kids")] = kids
    return _finish(writer, path, ArrayObject([parent_ref]), kids)


def inline_stream_checkbox(path: str) -> str:
    """A checkbox whose /AP/N holds inline streams instead of indirect references."""
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    field = DictionaryObject()
    field.update(
        {
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject("consent"),
            NameObject("/V"): NameObject("/checked"),
        }
    )
    field_ref = writer._add_object(field)
    kids = ArrayObject([_widget(writer, field_ref, ["/checked", "/Off"], "/checked", inline=True)])
    field[NameObject("/Kids")] = kids
    return _finish(writer, path, ArrayObject([field_ref]), kids)


def undeclared_state_checkbox(path: str) -> str:
    """A checkbox whose /V names a state that /AP/N does not declare at all."""
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    field = DictionaryObject()
    field.update(
        {
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject("consent"),
            NameObject("/V"): NameObject("/Yes"),
            NameObject("/AS"): NameObject("/Off"),
        }
    )
    field_ref = writer._add_object(field)
    kids = ArrayObject([_widget(writer, field_ref, ["/checked", "/Off"], "/Off")])
    field[NameObject("/Kids")] = kids
    return _finish(writer, path, ArrayObject([field_ref]), kids)


def nested_field(path: str) -> str:
    """A non-terminal parent (`address`) holding one terminal child (`city`)."""
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    parent = DictionaryObject()
    parent.update({NameObject("/T"): TextStringObject("address")})
    parent_ref = writer._add_object(parent)

    child = DictionaryObject()
    child.update(
        {
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject("city"),
            NameObject("/V"): TextStringObject("Cambridge"),
            NameObject("/Parent"): parent_ref,
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject([NumberObject(n) for n in (10, 10, 90, 30)]),
        }
    )
    child_ref = writer._add_object(child)
    parent[NameObject("/Kids")] = ArrayObject([child_ref])
    return _finish(writer, path, ArrayObject([parent_ref]), ArrayObject([child_ref]))
