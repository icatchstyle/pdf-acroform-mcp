# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-09-02

First release.

### Tools
- `pdf_inspect_fields` — field dump with state-name diagnostics. Reads `/AS` from
  the raw AcroForm tree, because `get_fields()` drops it for merged field/widget
  dictionaries, and resolves the widget matching `/V` so a consistent radio group
  is not reported as a mismatch.
- `pdf_fill` — writes `/V` and `/AS` together, reports requested fields the form
  does not have, never writes in place, and refuses to replace an existing file
  unless asked.
- `pdf_diff_fields` — field-level comparison of two PDFs, including added and
  removed fields.
- `pdf_check_acroform` — inline-stream `/AP/N` detection and three-place state-name
  validation, checked per widget so radio groups are covered.

### Notes
- Values are validated against the appearance states the PDF declares rather than
  against an assumed `/Yes`-or-`/checked` convention.
- Password-protected PDFs and malformed input produce readable errors instead of a
  pypdf traceback. Empty-password encryption is handled transparently.
- `PDF_ACROFORM_MCP_ROOT` confines every path to one directory when set.
