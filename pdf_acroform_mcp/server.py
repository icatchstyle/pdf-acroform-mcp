"""
PDF AcroForm MCP server.

Entrypoint: python -m pdf_acroform_mcp.server

Wraps the pure operations in ``pdf_ops`` as MCP tools and formats their result as
markdown, so an agent gets a readable answer instead of a raw object dump.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from pdf_acroform_mcp import pdf_ops
from pdf_acroform_mcp.pdf_ops import PdfOpsError

mcp = FastMCP(
    name="pdf-acroform",
    instructions=(
        "PDF AcroForm tools: inspect, fill, diff and check form fields. Written for "
        "template/fill pipelines where one library builds the form and another fills "
        "it later — that seam breaks silently. Remember the three-place rule: the "
        "on-state name must match in /V, /AS and the /AP/N key. Paths are absolute "
        "paths on the host filesystem."
    ),
)


def _bullets(items: list[str], empty: str) -> str:
    if not items:
        return empty
    return "\n".join(f"- {i}" for i in items)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True})
def pdf_inspect_fields(path: str) -> str:
    """
    Dump all AcroForm fields of a PDF with their type and value/appearance state.

    Flags values that name no declared appearance state, /V vs /AS disagreement,
    and widgets that render as checked while the field value is unset.

    Args:
        path: Absolute path to the PDF, e.g. `/srv/forms/contract.pdf`
    """
    try:
        r = pdf_ops.inspect_fields(path)
    except PdfOpsError as e:
        return f"❌ {e}"

    if not r["has_acroform"]:
        return f"❌ No AcroForm fields found in `{path}`."

    lines = [f"✅ {r['count']} fields in `{path}`", ""]
    for f in r["fields"]:
        ft = f["ft"]
        if ft == "/Btn":
            # Radio groups carry one /AS per widget; showing all of them is the
            # difference between a usable diagnosis and a riddle.
            states = f["as_states"]
            as_col = f"AS={f['as']}" + (f" (widgets: {states})" if len(states) > 1 else "")
            lines.append(f"- [BTN] `{f['name']}`  V={f['v']}  {as_col}  DV={f['dv']}")
        elif ft == "/Tx":
            lines.append(f"- [TX]  `{f['name']}`  V={f['v'][:60]}")
        elif ft == "/Ch":
            lines.append(f"- [CH]  `{f['name']}`  V={f['v']}")
        else:
            lines.append(f"- [{ft}] `{f['name']}`  V={f['v']}")

    lines.append("")
    if r["issues"]:
        lines.append(f"🔴 {len(r['issues'])} potential issue(s):")
        lines.append(_bullets(r["issues"], ""))
    else:
        lines.append("✅ No state-name problems detected.")
    return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True})
def pdf_check_acroform(path: str) -> str:
    """
    Structural AcroForm checks beyond a plain field dump.

    Detects inline-stream `/AP/N` entries (strict parsers throw
    `endstream is not a name`) and three-place state-name inconsistencies,
    checked per widget so radio groups are covered.

    Args:
        path: Absolute path to the PDF to check.
    """
    try:
        r = pdf_ops.check_acroform(path)
    except PdfOpsError as e:
        return f"❌ {e}"

    if not r["has_acroform"]:
        return f"❌ No AcroForm in `{path}`."

    lines = [f"Checked {r['checked_fields']} terminal field(s) in `{path}`.", ""]

    lines.append("**Inline-stream check (/AP/N):**")
    if r["inline_stream_issues"]:
        lines.append(f"🔴 {len(r['inline_stream_issues'])} issue(s):")
        lines.append(_bullets(r["inline_stream_issues"], ""))
    else:
        lines.append("✅ /AP/N uses indirect references (no inline streams).")

    lines.append("")
    lines.append("**State-name consistency (/V vs /AS vs /AP/N keys):**")
    if r["consistency_issues"]:
        lines.append(f"🔴 {len(r['consistency_issues'])} issue(s):")
        lines.append(_bullets(r["consistency_issues"], ""))
    else:
        lines.append("✅ No state-name inconsistencies detected.")
    return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True})
def pdf_diff_fields(before_path: str, after_path: str) -> str:
    """
    Compare form fields of two PDFs (typically before/after a fill).

    Args:
        before_path: Absolute path to the PDF before filling.
        after_path: Absolute path to the PDF after filling.
    """
    try:
        r = pdf_ops.diff_fields(before_path, after_path)
    except PdfOpsError as e:
        return f"❌ {e}"

    if r["total"] == 0:
        return "⚠️ No field changes between the two PDFs — was the PDF actually filled?"

    lines = [f"{r['total']} field(s) changed:", ""]
    for c in r["changes"]:
        mark = "✅" if c["filled"] else "⬜"
        lines.append(f"- {mark} `{c['name']}`  {' | '.join(c['changed'])}")
    return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": True})
def pdf_fill(
    path: str,
    field_values: dict[str, str],
    out_path: str,
    need_appearances: bool = True,
    overwrite: bool = False,
) -> str:
    """
    Fill AcroForm fields and write the result to a new PDF.

    For checkboxes/radios pass the on-state name as declared in `/AP/N` (often
    `/Yes` or `/checked`); both `/V` and `/AS` are set. An existing `out_path` is
    never replaced unless `overwrite` is true.

    Args:
        path: Absolute path to the source PDF.
        field_values: Mapping of field name -> value,
            e.g. `{"first_name": "Ada", "consent": "/checked"}`.
        out_path: Absolute path for the filled output PDF.
        need_appearances: Set the /NeedAppearances flag (default: true).
        overwrite: Allow replacing an existing file at out_path (default: false).
    """
    try:
        r = pdf_ops.fill(path, field_values, out_path, need_appearances, overwrite)
    except PdfOpsError as e:
        return f"❌ {e}"

    lines = [
        f"✅ Wrote `{r['out_path']}` (NeedAppearances={r['need_appearances']}).",
        "",
        f"Updated {len(r['updated'])} field(s): "
        + (", ".join(f"`{n}`" for n in r["updated"]) or "—"),
    ]
    if r["unknown"]:
        lines.append("")
        lines.append(
            f"⚠️ {len(r['unknown'])} requested field(s) not found in the AcroForm: "
            + ", ".join(f"`{n}`" for n in r["unknown"])
        )
    return "\n".join(lines)


def main() -> None:
    """Run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
