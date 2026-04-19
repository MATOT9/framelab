# Testing

Use this file as the validation entry point. Prefer the smallest test set that covers the changed behavior, then widen only when risk justifies it.

## Quick Commands

List available suites:

```bash
python scripts/tests.py --list-suites
```

Run the default fast suite:

```bash
python scripts/tests.py
```

Run a named suite:

```bash
python scripts/tests.py --suite fast
python scripts/tests.py --suite changed
python scripts/tests.py --suite data
python scripts/tests.py --suite ui
python scripts/tests.py --suite analysis
python scripts/tests.py --suite core
```

Run explicit files or patterns:

```bash
python scripts/tests.py tests/test_workspace_document.py
python scripts/tests.py --pattern 'test_analysis_*.py'
python scripts/tests.py --show-files --suite changed
```

## Suite Meaning

- `fast`: default local regression set with light Qt coverage.
- `changed`: changed tests plus mapped source tests and a smoke set.
- `data`: dataset loading, metadata, session, workspace, image I/O, and eBUS flows.
- `ui`: Qt-heavy page, dock, density, and dialog coverage.
- `analysis`: analysis context, math, and analysis-page behavior.
- `core`: everything except the UI-focused suite.
- `all`: every test module under `tests/`.

The exact mapping lives in `scripts/tests.py`.

## Docs Validation

For docs-only changes:

```bash
git diff --check
python scripts/docs/build.py --strict --no-copy
python scripts/docs/check.py
```

When bundled help should be refreshed:

```bash
python scripts/docs/build.py --strict
```

Do not hand-edit `framelab/assets/help/`.

## Native Validation

Build the native backend:

```bash
python tools/build_native_backend.py
```

Native-facing changes should also run relevant tests such as:

```bash
python scripts/tests.py tests/test_native_backend.py tests/test_raw_decode.py
```

Use `tools/profile_metrics_backend.py` and the native benchmark notes when measuring performance work.

## Packaging Validation

For standalone packaging changes:

```bash
python tools/build_nuitka_app.py --check
python tools/build_nuitka_app.py --smoke
```

Use the smoke build as a toolchain check, not as proof that the full app package is release-ready.

## Qt Notes

- `scripts/tests.py` sets `QT_QPA_PLATFORM=offscreen` by default.
- UI tests can still be slower or more fragile than pure state tests.
- Prefer state/controller tests for behavior that does not need real widget interaction.

## Choosing A Validation Set

- Docs-only: `git diff --check`, targeted `rg`, docs build/check.
- Plugin registry or selection: `tests/test_plugin_registry.py`, `tests/test_app_startup.py`, and affected UI tests.
- Workspace persistence: `tests/test_workspace_document.py`, `tests/test_window_workflow_state.py`, `tests/test_ui_settings.py`.
- eBUS: `tests/test_ebus_metadata_resolution.py`, plugin/startup tests if menu or discovery changes.
- Metadata/datacards: metadata, datacard authoring, session manager, and relevant workflow-state tests.
- Native/decode: raw decode, image I/O, native backend, and worker tests.
