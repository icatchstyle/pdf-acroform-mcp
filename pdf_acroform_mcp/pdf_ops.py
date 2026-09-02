"""
Pure PDF AcroForm operations built on pypdf.

These functions return plain Python data structures (dicts/lists) so they can be
unit-tested without an MCP client. The MCP layer in ``server.py`` wraps them and
formats the result as human-readable markdown.

Background — the template/fill pipeline these checks were written for: one library
builds the form template (pdf-lib, in a browser), another fills it later
(iText7, server-side). AcroForms break silently at that seam, and the two faults
worth tooling are the three-place state-name rule and inline appearance streams.
Both are documented in the README.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # only for type hints, never imported at runtime
    from pypdf import PdfReader

#: Values that mean "no meaningful state" when comparing /V and /AS.
_EMPTY = ("", "—", "/Off")

#: Optional sandbox: when set, every path must resolve inside this directory.
#: An MCP server takes paths from an agent, so a deployment that wants to bound
#: that blast radius can do it without patching the code.
_ROOT_ENV = "PDF_ACROFORM_MCP_ROOT"


class PdfOpsError(Exception):
    """Raised for expected, user-facing failures (missing file, no AcroForm, ...)."""


def _resolve(path: str) -> str:
    """Absolute path, checked against the optional sandbox root."""
    resolved = os.path.realpath(os.path.abspath(path))
    root = os.environ.get(_ROOT_ENV)
    if root:
        root_resolved = os.path.realpath(os.path.abspath(root))
        if os.path.commonpath([resolved, root_resolved]) != root_resolved:
            raise PdfOpsError(f"Path is outside the configured {_ROOT_ENV} sandbox: {path}")
    return resolved


def _require_file(path: str) -> str:
    resolved = _resolve(path)
    if not os.path.isfile(resolved):
        raise PdfOpsError(f"File not found: {path}")
    return resolved


def _as_str(value: Any) -> str:
    """Render a pypdf value as a plain string without surrounding noise."""
    if value is None:
        return "—"
    return str(value)


def _open_reader(path: str) -> PdfReader:
    """
    Open a PDF, turning every pypdf failure into a PdfOpsError.

    Empty-password encryption is transparent in most viewers but makes pypdf raise
    on access, so it is decrypted here rather than surfacing as a parser error.
    """
    from pypdf import PdfReader

    resolved = _require_file(path)
    try:
        reader = PdfReader(resolved)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise PdfOpsError(f"PDF is password-protected, cannot be read: {path}")
        return reader
    except PdfOpsError:
        raise
    except Exception as exc:  # pypdf raises a wide range on malformed input
        raise PdfOpsError(f"Cannot read PDF {path}: {type(exc).__name__}: {exc}") from exc


def _acroform(reader: PdfReader) -> Any | None:
    root = reader.trailer.get("/Root")
    if root is None:
        raise PdfOpsError("PDF has no /Root")
    acroform = root.get_object().get("/AcroForm")
    return acroform.get_object() if acroform else None


def _iter_terminal_fields(acroform: Any) -> Iterator[tuple[str, Any]]:
    """
    Yield ``(qualified_name, field)`` for every terminal field.

    Names are dotted like ``get_fields()`` reports them, so lookups from the two
    sources line up; a ``/Kids`` entry carrying its own ``/T`` is a nested field,
    one without is a widget annotation of the field itself.
    """

    def walk(entries: Any, prefix: str) -> Iterator[tuple[str, Any]]:
        for ref in entries or []:
            field = ref.get_object()
            t = field.get("/T")
            if t is None:
                name = prefix
            else:
                name = f"{prefix}.{t}" if prefix else str(t)
            kids = field.get("/Kids")
            nested = [k for k in (kids or []) if k.get_object().get("/T") is not None]
            if nested:
                yield from walk(nested, name)
            else:
                yield name, field

    yield from walk(acroform.get("/Fields"), "")


def _widgets(field: Any) -> list[dict[str, Any]]:
    """
    Describe every widget annotation belonging to a field.

    A field can be merged with its single widget (attributes sit on the field
    itself) or own several ``/Kids`` widgets — radio groups always do. Each entry
    reports that widget's own ``/AS``, its ``/AP/N`` state names, and any state
    whose appearance is an inline stream instead of an indirect reference.
    """
    from pypdf.generic import IndirectObject, StreamObject

    def describe(obj: Any) -> dict[str, Any]:
        states: set[str] = set()
        inline: list[str] = []
        ap = obj.get("/AP")
        if ap is not None:
            ap_n = ap.get_object().get("/N")
            if ap_n is not None:
                ap_n_obj = ap_n.get_object()
                if hasattr(ap_n_obj, "items"):
                    for state_name, state_val in ap_n_obj.items():
                        states.add(str(state_name))
                        # The raw value must be an indirect reference; a StreamObject
                        # sitting here directly is the inline case iText7 rejects.
                        raw = (
                            ap_n_obj.raw_get(state_name)
                            if hasattr(ap_n_obj, "raw_get")
                            else state_val
                        )
                        if isinstance(raw, StreamObject) and not isinstance(raw, IndirectObject):
                            inline.append(str(state_name))
        return {"as": _as_str(obj.get("/AS")), "ap_states": states, "inline": inline}

    kids = [k.get_object() for k in (field.get("/Kids") or [])]
    widget_kids = [k for k in kids if k.get("/T") is None]
    if widget_kids:
        return [describe(k) for k in widget_kids]
    return [describe(field)]


def _appearance_state(field: Any, value: str) -> tuple[str, list[str]]:
    """
    Resolve the field's effective ``/AS`` and the per-widget states behind it.

    For a multi-widget field only the widget matching ``/V`` is "on"; picking the
    first one instead reports ``/Off`` for a perfectly consistent radio group.
    """
    states = [w["as"] for w in _widgets(field)]
    if not states:
        return "—", []
    if value in states:
        return value, states
    if len(states) == 1:
        return states[0], states
    on = [s for s in states if s not in _EMPTY]
    return (on[0] if on else "/Off"), states


def inspect_fields(path: str) -> dict[str, Any]:
    """
    Dump every AcroForm field with its type and value/appearance state.

    Returns ``count``, a ``fields`` list (name, ft, v, as, as_states, dv) and an
    ``issues`` list flagging state-name faults.
    """
    reader = _open_reader(path)
    try:
        fields = reader.get_fields()
    except Exception as exc:
        raise PdfOpsError(f"Cannot read the AcroForm of {path}: {exc}") from exc
    if not fields:
        return {"count": 0, "fields": [], "issues": [], "has_acroform": False}

    acroform = _acroform(reader)
    raw = dict(_iter_terminal_fields(acroform)) if acroform else {}

    out_fields: list[dict[str, Any]] = []
    issues: list[str] = []

    for name, f in sorted(fields.items()):
        ft = _as_str(f.get("/FT"))
        v = _as_str(f.get("/V"))
        dv = _as_str(f.get("/DV"))
        raw_field = raw.get(name)

        if raw_field is not None:
            as_, as_states = _appearance_state(raw_field, v)
        else:
            # get_fields() drops /AS for merged field/widget dicts, so this is a
            # fallback only: a name the raw walk did not reach (unusual nesting).
            as_, as_states = _as_str(f.get("/AS")), []

        out_fields.append(
            {"name": name, "ft": ft, "v": v, "as": as_, "as_states": as_states, "dv": dv}
        )

        if ft != "/Btn" or raw_field is None:
            continue

        declared = sorted({s for w in _widgets(raw_field) for s in w["ap_states"]})
        if v not in _EMPTY and declared and v not in declared:
            issues.append(
                f"{name}: V={v} is not one of the appearance states {declared} — "
                f"the filler will not find it in /AP/N and the field stays empty."
            )
        if v not in _EMPTY and as_ not in _EMPTY and v != as_:
            issues.append(f"{name}: V={v} != AS={as_} — field value and appearance state disagree.")
        if v in _EMPTY and any(s not in _EMPTY for s in as_states):
            issues.append(
                f"{name}: V={v} but a widget shows {as_states} — "
                f"the form renders as checked while its value is unset."
            )

    return {
        "count": len(out_fields),
        "fields": out_fields,
        "issues": issues,
        "has_acroform": True,
    }


def _field_snapshot(path: str) -> dict[str, dict[str, str]]:
    reader = _open_reader(path)
    fields = reader.get_fields() or {}
    acroform = _acroform(reader)
    raw = dict(_iter_terminal_fields(acroform)) if acroform else {}
    snapshot: dict[str, dict[str, str]] = {}
    for name, f in fields.items():
        v = _as_str(f.get("/V"))
        raw_field = raw.get(name)
        if raw_field is not None:
            as_ = _appearance_state(raw_field, v)[0]
        else:
            as_ = _as_str(f.get("/AS"))
        snapshot[name] = {
            "FT": _as_str(f.get("/FT")),
            "V": v,
            "AS": as_,
            "DV": _as_str(f.get("/DV")),
        }
    return snapshot


def diff_fields(before_path: str, after_path: str) -> dict[str, Any]:
    """
    Compare form fields of two PDFs (typically pre/post fill).

    Returns ``changes`` (list of {name, changed: [..], filled: bool}) and ``total``.
    """
    before = _field_snapshot(before_path)
    after = _field_snapshot(after_path)

    changes: list[dict[str, Any]] = []
    for name in sorted(set(before) | set(after)):
        b = before.get(name, {})
        a = after.get(name, {})
        if b == a:
            continue
        changed_parts: list[str] = []
        if b.get("V") != a.get("V"):
            changed_parts.append(f"V: {b.get('V', '—')} -> {a.get('V', '—')}")
        if b.get("AS") != a.get("AS"):
            changed_parts.append(f"AS: {b.get('AS', '—')} -> {a.get('AS', '—')}")
        if not changed_parts:
            changed_parts.append("field added" if not b else "field removed")
        a_v = a.get("V")
        changes.append(
            {"name": name, "changed": changed_parts, "filled": bool(a_v) and a_v not in _EMPTY}
        )

    return {"changes": changes, "total": len(changes)}


def check_acroform(path: str) -> dict[str, Any]:
    """
    Structural AcroForm checks that ``get_fields()`` cannot surface:

    - inline-stream ``/AP/N`` entries (a strict parser throws
      ``endstream is not a name``); correct entries are indirect references.
    - three-place state-name consistency, checked per widget: ``/V`` against the
      widget's own ``/AS`` and against that widget's ``/AP/N`` keys.

    Returns ``inline_stream_issues``, ``consistency_issues`` and ``checked_fields``.
    """
    reader = _open_reader(path)
    acroform = _acroform(reader)
    if acroform is None:
        return {
            "has_acroform": False,
            "inline_stream_issues": [],
            "consistency_issues": [],
            "checked_fields": 0,
        }

    inline_issues: list[str] = []
    consistency_issues: list[str] = []
    checked = 0

    for name, field in _iter_terminal_fields(acroform):
        checked += 1
        ft = _as_str(field.get("/FT"))
        widgets = _widgets(field)
        v = _as_str(field.get("/V"))

        for idx, w in enumerate(widgets):
            label = name if len(widgets) == 1 else f"{name}[widget {idx}]"
            for state in w["inline"]:
                inline_issues.append(
                    f"{label}: /AP/N/{state} is an INLINE stream — a strict parser "
                    f"throws 'endstream is not a name'. Fix: register the appearance "
                    f"as a Form XObject so /AP/N holds an indirect reference."
                )
            if ft != "/Btn" or not w["ap_states"]:
                continue
            if w["as"] not in ("—", "") and w["as"] not in w["ap_states"]:
                consistency_issues.append(
                    f"{label}: /AS {w['as']} is not among this widget's /AP/N states "
                    f"{sorted(w['ap_states'])}."
                )

        if ft != "/Btn":
            continue

        declared = sorted({s for w in widgets for s in w["ap_states"]})
        if not declared:
            continue
        if v not in _EMPTY and v not in declared:
            consistency_issues.append(f"{name}: /V {v} is not among /AP/N states {declared}.")
        elif v not in _EMPTY and not any(w["as"] == v for w in widgets):
            # The value names a real state, but no widget displays it — the
            # three-place rule broken at the /AS corner.
            consistency_issues.append(
                f"{name}: /V {v} is not reflected by any widget's /AS "
                f"(widget states: {[w['as'] for w in widgets]})."
            )
        elif v in _EMPTY and any(w["as"] not in _EMPTY for w in widgets):
            consistency_issues.append(
                f"{name}: /V is {v} but a widget shows "
                f"{[w['as'] for w in widgets if w['as'] not in _EMPTY]}."
            )

    return {
        "has_acroform": True,
        "inline_stream_issues": inline_issues,
        "consistency_issues": consistency_issues,
        "checked_fields": checked,
    }


def fill(
    path: str,
    field_values: dict[str, str],
    out_path: str,
    need_appearances: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Write ``field_values`` into the AcroForm of ``path`` and save to ``out_path``.

    For checkboxes/radios pass the on-state name as declared in ``/AP/N`` (often
    ``/Yes`` or ``/checked``); pypdf sets both ``/V`` and ``/AS``.
    ``need_appearances`` sets ``/NeedAppearances`` so viewers regenerate
    appearances. ``overwrite`` must be set explicitly to replace an existing file.

    Returns ``updated`` (requested fields present in the PDF), ``unknown``
    (requested names not in the AcroForm) and the resolved ``out_path``.
    """
    from pypdf import PdfWriter

    if not isinstance(field_values, dict) or not field_values:
        raise PdfOpsError("field_values must be a non-empty object of {field: value}.")

    reader = _open_reader(path)
    out_resolved = _resolve(out_path)
    # Checked before the overwrite guard, and not waivable by it: destroying the
    # source is never what the caller meant.
    if out_resolved == _resolve(path):
        raise PdfOpsError("out_path is the source PDF; filling never writes in place.")
    if os.path.exists(out_resolved) and not overwrite:
        raise PdfOpsError(
            f"Refusing to overwrite an existing file: {out_path} "
            f"(pass overwrite=true to replace it)."
        )

    try:
        known = set((reader.get_fields() or {}).keys())
        requested = set(field_values.keys())

        writer = PdfWriter()
        writer.append(reader)

        # update_page_form_field_values only touches fields whose widgets are on the
        # given page, so every page has to be visited.
        for page in writer.pages:
            writer.update_page_form_field_values(page, field_values, auto_regenerate=False)

        if need_appearances:
            writer.set_need_appearances_writer(True)

        out_dir = os.path.dirname(out_resolved)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_resolved, "wb") as fh:
            writer.write(fh)
    except PdfOpsError:
        raise
    except Exception as exc:
        raise PdfOpsError(f"Filling failed: {type(exc).__name__}: {exc}") from exc

    return {
        "updated": sorted(requested & known),
        "unknown": sorted(requested - known),
        "out_path": out_resolved,
        "need_appearances": need_appearances,
    }
