# Tooling Map

Use this page to find repo-owned helper scripts and understand their expected role.

## Test Helper

- Entry point: `scripts/tests.py`
- Purpose: wraps common pytest suite selections and changed-file heuristics.
- Canonical usage: see root `TESTING.md`.
- Maintenance note: update `TESTING.md` when suite names, patterns, or defaults change.

## Documentation Helpers

- Build: `scripts/docs/build.py`
- Check: `scripts/docs/check.py`
- Purpose: build MkDocs, stage MathJax assets, optionally copy bundled help, and validate key docs outputs.
- Maintenance note: update `mkdocs.yml` and `scripts/docs/check.py` together when promoted docs pages change.

## Native Backend Helper

- Entry point: `tools/build_native_backend.py`
- Purpose: configure/build the C backend and write the Python extension into `framelab/native/`.
- Related docs: `native/README.md`, `native/PYTHON_EXTENSION_BUILD.md`.

## Standalone Packaging Helper

- Entry point: `tools/build_nuitka_app.py`
- Config: `tools/nuitka_build.toml`
- Purpose: validate and build folder-based standalone packages from `launcher.py`.
- Related docs: `docs/developer-guide/packaging.md`.

## Profiling And Diagnostics

- `tools/profile_metrics_backend.py`: compare or profile metric backend behavior.
- `tools/trace_datacard_wizard_transients.py`: inspect datacard wizard transient behavior.
- `native/benchmarks/README.md`: native benchmark notes.

## Local Config Inputs

- `config/preferences.ini`: local app preferences.
- `config/plugin_selection.json`: startup plugin selection.
- `config/acquisition_field_mapping.json`: editable acquisition mapping.
- `config/ebus_parameter_catalog.json`: editable eBUS parameter catalog.

Treat `config/` as local mutable state unless a task explicitly targets config defaults or migration behavior.
