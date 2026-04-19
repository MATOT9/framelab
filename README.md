# FrameLab Imaging Analysis Workbench

FrameLab is a PySide6 desktop workbench for image-based acquisition review. It helps operators scan TIFF and RAW datasets, inspect hierarchical metadata, manage workflow structure, review eBUS configuration snapshots, compute image measurements, and hand prepared results to analysis plugins.

This README is intentionally short. Use it as the project landing page, then follow the linked docs for implementation, testing, build, and handoff context.

## What FrameLab Covers

- Workflow-scoped data intake for calibration-style image datasets.
- Metadata resolution from paths, workflow nodecards, acquisition/session/campaign datacards, and eBUS-managed fields.
- Session and acquisition structure tools, with some legacy Session Manager flows still available as a plugin.
- Measure-page workflows for thresholding, Top-K statistics, ROI metrics, normalization, and background correction.
- Analysis plugins that consume a prepared `AnalysisContext` instead of reaching into raw UI state.
- Offline help built from the Markdown source under `docs/`.

## Start Reading

- [START_HERE.md](START_HERE.md): first-read routing for future development sessions.
- [BUILD_AND_RUN.md](BUILD_AND_RUN.md): environment setup, local launch, docs build, native build, and package checks.
- [TESTING.md](TESTING.md): common validation commands and suite selection.
- [REPO_MAP.md](REPO_MAP.md): top-level repository map and ownership guide.
- [CURRENT_STATE.md](CURRENT_STATE.md): current implementation snapshot.
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md) and [ROADMAP.md](ROADMAP.md): grounded bug/backlog context.

User and developer documentation lives in [docs/](docs/). The existing `docs/developer-guide/*` pages remain the canonical architecture documentation.

## Quick Launch

Create an environment using the repo dependency files, then launch:

```bash
python launcher.py
```

or:

```bash
python -m framelab
```

The app stores persistent preferences in `config/preferences.ini`. Reopenable session state such as workflow scope, selected dataset, page state, panels, splitter sizes, ROI, and background settings is restored only from an explicitly opened `.framelab` workspace file.

## Repository Shape

- `framelab/`: main application package.
- `framelab/main_window/`: host-window mixins for chrome, Data, Measure, Analyze, loading, runtime jobs, and shared actions.
- `framelab/workflow/`: workflow profiles, typed hierarchy models, and workspace loading.
- `framelab/plugins/`: manifest-discovered data, measure, and analysis plugins.
- `framelab/ebus/`: built-in eBUS parsing, catalog, effective-config, sidecar, compare, and dialog logic.
- `framelab/datacard_authoring/`: acquisition datacard mapping, models, validation, and serialization services.
- `native/`: optional C backend and Python extension build inputs.
- `tests/`: pytest regression suite.
- `scripts/`: docs and test helper entrypoints.
- `tools/`: native/backend profiling and standalone packaging helpers.
- `docs/`: MkDocs source for user, reference, developer, and maintenance documentation.

## Documentation And Help

Editable documentation is Markdown under `docs/`. Bundled offline help is generated into `framelab/assets/help/` by the docs build script.

```bash
python scripts/docs/build.py --strict
python scripts/docs/check.py
```

Do not hand-edit generated help files. Change the source docs, update navigation or validation expectations when needed, then rebuild through the scripts.
