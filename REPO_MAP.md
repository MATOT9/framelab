# Repository Map

Use this file to find the right owner before editing. For implementation detail, follow the linked canonical docs rather than expanding this map.

## Root Files

- `launcher.py`: local desktop launch entrypoint.
- `README.md`: concise project overview.
- `START_HERE.md`: first-read routing for development sessions.
- `BUILD_AND_RUN.md`: setup, launch, docs build, native build, and packaging commands.
- `TESTING.md`: validation entry point.
- `TODO`: informal backlog source used to ground [KNOWN_ISSUES.md](KNOWN_ISSUES.md) and [ROADMAP.md](ROADMAP.md).
- `mkdocs.yml`: MkDocs navigation and site configuration.
- `pytest.ini`: pytest defaults.
- `env_dev.yml`, `env_run.yml`, `requirements*.txt`: environment inputs.

## Main Directories

- `framelab/`: application package.
- `framelab/main_window/`: `FrameLabWindow` mixins for chrome, Data, Measure, Analyze, dataset loading, metric runtime, and shared actions.
- `framelab/workflow/`: workflow profiles, typed hierarchy models, governance config, and workspace loading.
- `framelab/plugins/`: manifest-discovered data, measure, and analysis plugins.
- `framelab/ebus/`: built-in eBUS parser, catalog, effective-config, sidecar, compare, and dialog stack.
- `framelab/datacard_authoring/`: acquisition datacard mapping, models, validation, generation, merge, and serialization.
- `framelab/native/`: Python-facing native backend wrapper.
- `framelab/assets/`: runtime assets, bundled default JSON, and generated offline help.
- `native/`: optional C backend source, CMake project, headers, tests, and benchmarks.
- `tests/`: pytest regression suite.
- `scripts/`: repo helper entrypoints for docs and tests.
- `tools/`: native build, profiling, tracing, and standalone packaging helpers.
- `docs/`: MkDocs source documentation.
- `config/`: local mutable runtime config. Treat it as user-local state, not source defaults.
- `sample_data/`: lightweight example data and fixtures.

## Common Change Targets

- App startup or plugin selector: `framelab/app.py`, `framelab/plugins/selection.py`, `framelab/plugins/registry.py`.
- Menus, toolbar, help, preferences, and host chrome: `framelab/main_window/chrome.py`.
- Dataset scan and image cache behavior: `framelab/main_window/dataset_loading.py`, `framelab/dataset_state.py`, `framelab/image_io.py`.
- Workflow tree, workspace roots, and profile logic: `framelab/workflow/`.
- Metadata resolution: `framelab/metadata.py`, `framelab/metadata_state.py`, `framelab/node_metadata.py`.
- Acquisition datacard semantics: `framelab/datacard_authoring/`, `framelab/acquisition_datacard.py`.
- eBUS inspect, compare, and effective config behavior: `framelab/ebus/`.
- Measure-page controls and preview behavior: `framelab/main_window/inspect_page.py`.
- Metric jobs and worker result application: `framelab/main_window/metrics_runtime.py`, `framelab/workers.py`, `framelab/metrics_state.py`.
- Analysis context and plugin hosting: `framelab/analysis_context.py`, `framelab/main_window/analysis.py`, `framelab/plugins/analysis/`.
- Native decode/metric behavior: `native/`, `framelab/native/`, `framelab/raw_decode.py`.
- Documentation source: `docs/`, `mkdocs.yml`, `scripts/docs/`.
- Standalone packaging: `tools/build_nuitka_app.py`, `tools/nuitka_build.toml`, `docs/developer-guide/packaging.md`.

## Canonical Docs

- Architecture and state ownership: [docs/developer-guide/architecture.md](docs/developer-guide/architecture.md).
- Plugin system: [docs/developer-guide/plugin-system.md](docs/developer-guide/plugin-system.md).
- Datacard system: [docs/developer-guide/datacard-system.md](docs/developer-guide/datacard-system.md).
- eBUS integration: [docs/developer-guide/ebus-config-integration.md](docs/developer-guide/ebus-config-integration.md).
- UI structure: [docs/developer-guide/ui-structure.md](docs/developer-guide/ui-structure.md).
- Packaging: [docs/developer-guide/packaging.md](docs/developer-guide/packaging.md).
- Config files: [docs/reference/config-files.md](docs/reference/config-files.md).
- Plugin manifests: [docs/reference/plugin-manifests.md](docs/reference/plugin-manifests.md).
