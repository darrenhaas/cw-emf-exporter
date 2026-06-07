# Release Process

Use this checklist before publishing a new PyPI version.

1. Confirm `pyproject.toml` and `src/opentelemetry_exporter_cloudwatch_emf/__init__.py`
   use the same version.
2. Run the full local validation:

   ```bash
   uv sync --extra dev
   uv run pytest
   uv run mypy src
   uv run flake8 src tests
   uv run black --check src tests
   uv build
   uv run twine check dist/*
   ```

3. Commit the release candidate and open a PR.
4. Wait for CI to pass.
5. Tag the reviewed commit. Replace `0.2.4` with the version being released:

   ```bash
   VERSION=0.2.4
   git tag -a "v${VERSION}" -m "v${VERSION}"
   git push origin main
   git push origin "v${VERSION}"
   ```

6. Publish to PyPI:

   ```bash
   VERSION=0.2.4
   uv run twine upload "dist/opentelemetry_exporter_cloudwatch_emf-${VERSION}"*
   ```

7. Only after the PyPI package is verified, update downstream consumers in a
   separate reviewed PR.
