# pdf-acroform-mcp

[![CI](https://github.com/icatchstyle/pdf-acroform-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/icatchstyle/pdf-acroform-mcp/actions/workflows/ci.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

> An MCP server for the unglamorous part of PDF work: finding out why a form field
> that looks filled is, to the next tool in the chain, empty.

Four tools over [pypdf](https://pypdf.readthedocs.io/), written while debugging a
pipeline where one library builds the form template and another fills it later.
That seam is where AcroForms break, and the breakage is silent: no exception, no
warning, just a checkbox that renders blank.

**Contents** — [Tools](#tools) · [The two traps](#the-two-traps-this-exists-for) ·
[Install](#install) · [Register it](#register-it) · [Safety](#safety) ·
[Limitations](#limitations) · [Development](#development)

## Tools

| Tool | What it does |
|---|---|
| `pdf_inspect_fields(path)` | Dump every field with `/FT`, `/V`, `/AS`, `/DV` — and for multi-widget fields the state of each widget — plus the state-name faults found |
| `pdf_fill(path, field_values, out_path, need_appearances=True, overwrite=False)` | Write values (sets `/V` **and** `/AS`, plus `/NeedAppearances`); reports which requested fields do not exist |
| `pdf_diff_fields(before_path, after_path)` | Compare the form fields of two PDFs — the quickest answer to "did the fill actually do anything?" |
| `pdf_check_acroform(path)` | Structural checks `get_fields()` cannot surface: inline-stream `/AP/N` entries and per-widget state-name consistency |

## The two traps this exists for

**1. The three-place rule.** A checkbox's on-state name must be *identical* in three
places. Miss one and the field silently stays empty:

```
Field:  /V   /checked
Widget: /AS  /checked
        /AP << /N << /checked <XObject ref>   /Off <XObject ref> >> >>
```

The name itself is a template convention, not a standard: some generators write
`/Yes`, others `/checked`. A template using one and a filler expecting the other
produces a form that looks correct in every viewer and arrives empty at the
consumer. `pdf_inspect_fields` therefore does not assume a convention — it checks
`/V` against the states the PDF itself declares in `/AP/N`.

**2. Inline streams in `/AP/N`.** Appearance streams must be **indirect** references
to Form XObjects. A generator that inlines them produces a PDF most viewers still
render — while a strict parser aborts with `endstream is not a name`.
`pdf_check_acroform` finds these before the other side of the pipeline does.

### Why the checks are per widget

A field is not always one thing. A radio group is one field with several widget
annotations, and only the selected widget carries the on-state — every other one
holds `/Off`. Tools that read "the" `/AS` of such a field pick an arbitrary widget
and report a mismatch on a perfectly consistent form. Both tools here resolve the
widget that matches `/V`, and `pdf_check_acroform` validates each widget against
its own `/AP/N` keys. `pdf_inspect_fields` also reads `/AS` from the raw AcroForm
tree rather than from `get_fields()`, which drops it for merged field/widget
dictionaries.

## Install

```bash
git clone https://github.com/icatchstyle/pdf-acroform-mcp.git
cd pdf-acroform-mcp
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Register it

The server speaks **stdio** — no daemon, no ports, direct access to local files.

Claude Code (`~/.claude.json`, or `claude mcp add`):

```json
"pdf-acroform": {
  "type": "stdio",
  "command": "/absolute/path/to/pdf-acroform-mcp/.venv/bin/python",
  "args": ["-m", "pdf_acroform_mcp.server"],
  "cwd": "/absolute/path/to/pdf-acroform-mcp"
}
```

Tool output is markdown with status glyphs (`✅ ❌ 🔴 ⚠️`), meant to be read by a
model and a human in the same pane. Clients that do not render emoji show the
codepoints; nothing else changes.

## Safety

All tool paths are absolute paths on the host filesystem, and the server sees
whatever the account running it can see. Three guards:

- `pdf_fill` is the only tool that writes, and it **never writes in place** — an
  `out_path` equal to the source is refused outright.
- An existing file at `out_path` is **not** replaced unless `overwrite=true` is
  passed explicitly. An agent reusing a path cannot quietly destroy earlier output.
- Set `PDF_ACROFORM_MCP_ROOT=/some/dir` to confine every path — reads included — to
  that directory. Paths resolving outside it are refused, symlinks included.

Password-protected PDFs are reported as such rather than surfacing as a parser
error; empty-password encryption, which most viewers open transparently, is handled
transparently here too. Every pypdf failure is translated into a readable message,
so a malformed PDF gets an answer instead of a traceback.

## Limitations

- Field values are written through pypdf's `update_page_form_field_values`; complex
  appearance regeneration is left to the viewer via `/NeedAppearances`.
- Nested field hierarchies are walked and reported with dotted qualified names, the
  same way `get_fields()` names them. Fields whose parents carry no `/T` are
  reported under the name pypdf gives them.
- `pypdf` 5.x and 6.x are both exercised in CI. 7.x is fenced off until it is.

## Development

```bash
.venv/bin/pytest          # 26 tests, no network, no fixtures on disk
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The layout keeps the testable part free of the protocol:

```
pdf_acroform_mcp/
  pdf_ops.py    pure functions over pypdf, returning plain dicts
  server.py     the MCP layer: tool registration and markdown formatting
tests/
  factories.py      hand-assembled faulty AcroForms (no well-behaved generator makes these)
  test_pdf_ops.py   round-trip, fault-detection and failure-mode tests
```

Everything that could be wrong about a PDF is testable without an MCP client, and
`server.py` holds no logic worth testing.

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).
