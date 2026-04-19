# AGENTS

These rules apply inside the `framelab/` application package.

## Package Boundaries

- Keep startup behavior in `app.py` lightweight.
- Keep long-lived workflow, dataset, metadata, metrics, and analysis state on controllers or the host window.
- Keep UI composition in `window.py` and `main_window/` mixins rather than spreading shell behavior across helpers.
- Keep plugin discovery and selection in `framelab/plugins/`.
- Keep eBUS parsing, catalog, effective config, and dialogs in `framelab/ebus/`.
- Keep datacard semantics in `framelab/datacard_authoring/` and runtime resolution in `metadata.py`.

## State Rules

- Preferences persist through `config/preferences.ini`.
- Reopenable session state persists through `.framelab` workspace documents.
- Do not reintroduce launch-time restoration of session-like state from legacy UI-state config.
- Worker threads should emit results; host/UI code applies them after job validation.

## Validation

- Choose targeted tests from root `TESTING.md`.
- For workspace or preference changes, include workspace document and UI settings tests.
- For package path or asset changes, include runtime asset and packaging checks when relevant.
