# Contributing

Bug reports with a PDF that reproduces the problem are the most valuable thing you
can send. If the file is confidential, a hand-built minimal reproduction using
`tests/factories.py` as a starting point is just as good — better, actually, since
it can become a test.

## Ground rules

- **Logic goes in `pdf_ops.py`, not in `server.py`.** The MCP layer formats output
  and nothing else. A change that needs a running MCP client to test belongs on the
  other side of that line.
- **Every fault detector needs a negative test.** A check that only ever ran against
  a healthy file is not known to work. `tests/factories.py` builds broken AcroForms
  from raw pypdf objects for exactly this reason.
- **No new runtime dependencies** without a strong reason. The server is `pypdf` plus
  the MCP SDK, and that is a feature.

## Before opening a pull request

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

CI runs the tests on Python 3.10–3.13 and against both `pypdf` 5.x and 6.x. If your
change relies on behaviour from one of those, say so in the PR.

## Commit messages

Present tense, explaining why rather than what: the diff already shows what.
