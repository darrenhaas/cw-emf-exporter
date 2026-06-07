# Contributing

Contributions are welcome. Please keep changes focused and include tests for
behavior changes.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run mypy src
uv run flake8 src tests
uv run black --check src tests
uv build
uv run twine check dist/*
```

## Pull Requests

- Describe the behavior being changed and why.
- Add or update tests for exporter behavior changes.
- Do not include credentials, account identifiers, or production log data in
  issues, pull requests, or tests.

## Release Changes

Before publishing a release, follow [docs/RELEASE.md](docs/RELEASE.md).
