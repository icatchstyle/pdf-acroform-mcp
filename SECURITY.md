# Security policy

## Reporting a vulnerability

Please report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/icatchstyle/pdf-acroform-mcp/security/advisories/new)
rather than in a public issue.

## Threat model

This server takes file paths from an MCP client — in practice, from a language
model — and reads and writes local files with the privileges of the account running
it. Treat that as the boundary it is:

- Run it as a user that can only reach the documents it is meant to touch.
- Set `PDF_ACROFORM_MCP_ROOT` to confine every path to one directory. Paths are
  resolved (symlinks included) before the check, and anything outside is refused.
- `pdf_fill` never writes in place and refuses to replace an existing file unless
  `overwrite=true` is passed.

Parsing untrusted PDFs means running `pypdf` over untrusted input. Keep `pypdf`
current; a parser failure is caught and reported, but a parser vulnerability is not
something this layer can contain.
