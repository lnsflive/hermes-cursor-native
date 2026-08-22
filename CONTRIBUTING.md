# Contributing

Thank you for improving Hermes Cursor Native.

## Development

```text
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
python -m pytest
ruff check .
python -m build
```

Use `.venv/Scripts/python.exe` on Windows.

## Requirements

- Test-first behavior changes.
- No credentials, auth stores, sessions, private logs, or user-specific paths.
- Preserve patch authorship.
- Add compatibility evidence for Hermes/Cursor changes.
- Keep installation fail-closed and reversible.
- Run bootstrap syntax checks on Windows and POSIX changes.
- Explain security and update-survival impact in the PR.

## Commit style

```text
feat(scope): concise summary
fix(scope): concise summary
docs(scope): concise summary
```

## Release bar

A release needs green Python tests/lint/build, Windows and POSIX bootstrap syntax checks, artifact hash validation, and a documented compatibility matrix.
