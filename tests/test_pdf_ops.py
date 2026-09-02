"""
Tests for pdf_acroform_mcp.pdf_ops.

Two kinds of fixture: a healthy form generated with reportlab (round-trip and
fill behaviour) and hand-assembled AcroForms from ``factories`` for the faults a
well-behaved generator cannot produce.
"""

from __future__ import annotations

import os

import pytest

from pdf_acroform_mcp import pdf_ops

from . import factories

reportlab = pytest.importorskip("reportlab")

from reportlab.pdfgen import canvas  # noqa: E402


@pytest.fixture()
def form_pdf(tmp_path):
    path = os.path.join(str(tmp_path), "form.pdf")
    c = canvas.Canvas(path)
    form = c.acroForm
    c.drawString(50, 750, "Test form")
    form.textfield(name="first_name", x=50, y=700, width=200, height=20, borderStyle="solid")
    form.checkbox(name="consent", x=50, y=650, buttonStyle="check", checked=False)
    c.save()
    return path


# --- inspect ---------------------------------------------------------------


def test_inspect_lists_fields(form_pdf):
    r = pdf_ops.inspect_fields(form_pdf)
    assert r["has_acroform"] is True
    names = {f["name"] for f in r["fields"]}
    assert {"first_name", "consent"} <= names
    assert r["count"] >= 2


def test_inspect_reads_real_as_after_fill(form_pdf, tmp_path):
    # reportlab's checkbox on-state is /Yes; a consistent fill must not raise a
    # bogus "V != AS" (regression: get_fields() drops /AS -> false positive).
    out = os.path.join(str(tmp_path), "cb.pdf")
    pdf_ops.fill(form_pdf, {"consent": "/Yes"}, out)
    r = pdf_ops.inspect_fields(out)
    cb = next(f for f in r["fields"] if f["name"] == "consent")
    assert cb["v"] == "/Yes"
    assert cb["as"] == "/Yes"
    assert not any("!= AS" in i for i in r["issues"])


def test_inspect_consistent_radio_group_is_silent(tmp_path):
    # A correct radio group has exactly one widget on and the rest /Off. Reading
    # the first widget instead of the selected one used to report a false V != AS.
    path = factories.radio_group(os.path.join(str(tmp_path), "radio.pdf"), value="/pro")
    r = pdf_ops.inspect_fields(path)
    field = next(f for f in r["fields"] if f["name"] == "plan")
    assert field["v"] == "/pro"
    assert field["as"] == "/pro"
    assert sorted(field["as_states"]) == ["/Off", "/pro"]
    assert r["issues"] == []


def test_inspect_flags_value_no_widget_displays(tmp_path):
    path = factories.radio_group(
        os.path.join(str(tmp_path), "radio_bad.pdf"), value="/pro", selected="/basic"
    )
    r = pdf_ops.inspect_fields(path)
    assert any("!= AS" in i for i in r["issues"]), r["issues"]


def test_inspect_flags_undeclared_state(tmp_path):
    path = factories.undeclared_state_checkbox(os.path.join(str(tmp_path), "undeclared.pdf"))
    r = pdf_ops.inspect_fields(path)
    assert any("not one of the appearance states" in i for i in r["issues"]), r["issues"]


def test_inspect_resolves_nested_field_names(tmp_path):
    path = factories.nested_field(os.path.join(str(tmp_path), "nested.pdf"))
    r = pdf_ops.inspect_fields(path)
    names = {f["name"] for f in r["fields"]}
    assert any(n.endswith("city") for n in names), names


# --- check -----------------------------------------------------------------


def test_check_clean_form_has_no_issues(form_pdf):
    r = pdf_ops.check_acroform(form_pdf)
    assert r["has_acroform"] is True
    assert r["inline_stream_issues"] == []
    assert r["consistency_issues"] == []


def test_check_detects_inline_appearance_streams(tmp_path):
    path = factories.inline_stream_checkbox(os.path.join(str(tmp_path), "inline.pdf"))
    r = pdf_ops.check_acroform(path)
    assert r["inline_stream_issues"], "inline /AP/N stream was not detected"
    assert "endstream is not a name" in r["inline_stream_issues"][0]


def test_check_detects_value_without_matching_widget(tmp_path):
    path = factories.radio_group(
        os.path.join(str(tmp_path), "radio_bad.pdf"), value="/pro", selected="/basic"
    )
    r = pdf_ops.check_acroform(path)
    assert any("not reflected by any widget" in i for i in r["consistency_issues"]), r[
        "consistency_issues"
    ]


def test_check_detects_undeclared_value(tmp_path):
    path = factories.undeclared_state_checkbox(os.path.join(str(tmp_path), "undeclared.pdf"))
    r = pdf_ops.check_acroform(path)
    assert any("not among /AP/N states" in i for i in r["consistency_issues"]), r[
        "consistency_issues"
    ]


def test_check_consistent_radio_group_is_silent(tmp_path):
    path = factories.radio_group(os.path.join(str(tmp_path), "radio.pdf"), value="/pro")
    r = pdf_ops.check_acroform(path)
    assert r["consistency_issues"] == []
    assert r["inline_stream_issues"] == []


def test_check_reports_no_acroform(tmp_path):
    from pypdf import PdfWriter

    path = os.path.join(str(tmp_path), "plain.pdf")
    w = PdfWriter()
    w.add_blank_page(200, 200)
    with open(path, "wb") as fh:
        w.write(fh)
    r = pdf_ops.check_acroform(path)
    assert r["has_acroform"] is False
    assert r["checked_fields"] == 0


# --- fill ------------------------------------------------------------------


def test_fill_writes_values(form_pdf, tmp_path):
    out = os.path.join(str(tmp_path), "filled.pdf")
    r = pdf_ops.fill(form_pdf, {"first_name": "Ada Lovelace"}, out)
    assert "first_name" in r["updated"]
    assert os.path.isfile(out)

    after = pdf_ops.inspect_fields(out)
    first_name = next(f for f in after["fields"] if f["name"] == "first_name")
    assert "Ada Lovelace" in first_name["v"]


def test_fill_reports_unknown_field(form_pdf, tmp_path):
    out = os.path.join(str(tmp_path), "filled2.pdf")
    r = pdf_ops.fill(form_pdf, {"does_not_exist": "x"}, out)
    assert "does_not_exist" in r["unknown"]
    assert r["updated"] == []


def test_fill_refuses_to_overwrite_by_default(form_pdf, tmp_path):
    out = os.path.join(str(tmp_path), "filled.pdf")
    pdf_ops.fill(form_pdf, {"first_name": "Ada"}, out)
    with pytest.raises(pdf_ops.PdfOpsError, match="Refusing to overwrite"):
        pdf_ops.fill(form_pdf, {"first_name": "Grace"}, out)


def test_fill_overwrites_when_asked(form_pdf, tmp_path):
    out = os.path.join(str(tmp_path), "filled.pdf")
    pdf_ops.fill(form_pdf, {"first_name": "Ada"}, out)
    pdf_ops.fill(form_pdf, {"first_name": "Grace"}, out, overwrite=True)
    after = pdf_ops.inspect_fields(out)
    first_name = next(f for f in after["fields"] if f["name"] == "first_name")
    assert "Grace" in first_name["v"]


def test_fill_refuses_to_write_in_place(form_pdf):
    with pytest.raises(pdf_ops.PdfOpsError, match="never writes in place"):
        pdf_ops.fill(form_pdf, {"first_name": "Ada"}, form_pdf)


def test_fill_empty_values_raises(form_pdf, tmp_path):
    out = os.path.join(str(tmp_path), "x.pdf")
    with pytest.raises(pdf_ops.PdfOpsError):
        pdf_ops.fill(form_pdf, {}, out)


# --- diff ------------------------------------------------------------------


def test_diff_detects_change(form_pdf, tmp_path):
    out = os.path.join(str(tmp_path), "filled3.pdf")
    pdf_ops.fill(form_pdf, {"first_name": "Grace"}, out)
    d = pdf_ops.diff_fields(form_pdf, out)
    assert d["total"] >= 1
    assert "first_name" in {c["name"] for c in d["changes"]}


def test_diff_of_identical_files_is_empty(form_pdf):
    assert pdf_ops.diff_fields(form_pdf, form_pdf)["total"] == 0


# --- failure modes ---------------------------------------------------------


def test_missing_file_raises():
    with pytest.raises(pdf_ops.PdfOpsError, match="File not found"):
        pdf_ops.inspect_fields("/no/such/file.pdf")


def test_malformed_pdf_raises_ops_error(tmp_path):
    # A parser error must arrive as PdfOpsError, not as a raw pypdf traceback:
    # the MCP layer only translates PdfOpsError into a readable answer.
    path = os.path.join(str(tmp_path), "broken.pdf")
    with open(path, "wb") as fh:
        fh.write(b"not a pdf at all")
    with pytest.raises(pdf_ops.PdfOpsError):
        pdf_ops.inspect_fields(path)


def test_empty_password_encryption_is_transparent(form_pdf, tmp_path):
    from pypdf import PdfReader, PdfWriter

    path = os.path.join(str(tmp_path), "enc_empty.pdf")
    w = PdfWriter()
    w.append(PdfReader(form_pdf))
    w.encrypt("")
    with open(path, "wb") as fh:
        w.write(fh)

    r = pdf_ops.inspect_fields(path)
    assert r["has_acroform"] is True


def test_password_protected_pdf_raises_clear_error(form_pdf, tmp_path):
    from pypdf import PdfReader, PdfWriter

    path = os.path.join(str(tmp_path), "enc_pw.pdf")
    w = PdfWriter()
    w.append(PdfReader(form_pdf))
    w.encrypt("s3cret")
    with open(path, "wb") as fh:
        w.write(fh)

    with pytest.raises(pdf_ops.PdfOpsError, match="password-protected"):
        pdf_ops.inspect_fields(path)


def test_sandbox_root_blocks_outside_paths(form_pdf, tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_ACROFORM_MCP_ROOT", str(tmp_path / "allowed"))
    (tmp_path / "allowed").mkdir()
    with pytest.raises(pdf_ops.PdfOpsError, match="sandbox"):
        pdf_ops.inspect_fields(form_pdf)


def test_sandbox_root_allows_inside_paths(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    path = factories.radio_group(str(allowed / "radio.pdf"))
    monkeypatch.setenv("PDF_ACROFORM_MCP_ROOT", str(allowed))
    assert pdf_ops.inspect_fields(path)["has_acroform"] is True
