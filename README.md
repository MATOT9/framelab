# FrameLab Imaging Analysis Workbench

FrameLab is a desktop workbench for image-based acquisition review. It helps you scan TIFF datasets, inspect hierarchical metadata and datacards, manage acquisition/session structure, review eBUS configuration files, compute image measurements, and hand those results to analysis plugins.

This README is intentionally lightweight. It gives a newcomer enough context to launch the app, run the tests, and find the important parts of the repo. The full operator and maintenance guidance lives in [docs/](docs/).

## What The App Covers

- **Data intake**: recursive dataset scan, skip rules, metadata source selection, datacard awareness, and compact preflight checks.
- **Session tooling**: acquisition/session management, datacard authoring, and eBUS config inspection helpers.
- **Measurement**: table + preview workflows for ROI, thresholding, Top-K, normalization, and background-correction flows.
- **Analysis**: plugin-driven plots and derived tables using a prepared analysis context instead of raw UI state.
- **Offline help**: the same Markdown source in `docs/` is bundled into the app as static HTML help.

## Repository Structure

- `framelab/`: main application package.
- `framelab/main_window/`: host window shell and the Data / Measure / Analyze page mixins.
- `framelab/plugins/`: built-in data, measure, and analysis plugins.
- `framelab/ebus/`: eBUS snapshot parsing, compare logic, effective config handling, and catalog helpers.
- `framelab/datacard_authoring/`: datacard authoring models and services.
- `tests/`: pytest-based regression suite.
- `scripts/`: repo utilities, including docs helpers and the test runner.
- `docs/`: source documentation for users and developers.
- `config/`: local mutable app config and UI state.
- `launcher.py`: simple entrypoint for local app runs.
- `stylesheets.py`: shared application theming.

## Quick Start

### 1. Create an environment

Conda / Mamba:

```bash
mamba create -n framelab python=3.12
conda activate framelab
mamba install --file requirements-conda.txt
```

Pip / venv:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` is the pip-oriented file. `requirements-conda.txt` is the conda-oriented file. Both are grouped into `Running`, `Documentation`, and `Build` blocks so you can trim them down if you only need part of the toolchain.

### 2. Launch the app

```bash
python launcher.py
```

or

```bash
python -m framelab
```

### 3. Run the tests

Use the lightweight repo runner:

```bash
python scripts/tests.py
```

The helper wraps `pytest` directly and keeps the common suite shortcuts in one
place.

Useful variants:

```bash
python scripts/tests.py --list-suites
python scripts/tests.py --suite fast
python scripts/tests.py --suite ui
python scripts/tests.py tests/test_background.py
python scripts/tests.py --pattern 'test_analysis_*.py'
```

If you use VS Code, the checked-in workspace settings already point the Python
extension at `pytest` and disable `unittest` discovery.

## Documentation

The full docs site lives in `docs/` and covers operator workflows, architecture, plugin contracts, and packaging details.

### Documentation layout

The repo keeps documentation in two forms:

- `docs/`: editable Markdown source, docs assets, and docs-only styling
- `framelab/assets/help/`: generated offline HTML help consumed by the app

That split is intentional:

```text
docs/ Markdown + assets -> MkDocs build -> staged site -> framelab/assets/help/
```

Practical rule:

- edit `docs/**`, `mkdocs.yml`, and `scripts/docs/*.py`
- do not hand-edit `framelab/assets/help/**`
- treat `.docs_build/` as disposable build output

When docs pages are added, moved, or renamed, keep these in sync:

- the source file under `docs/`
- navigation in `mkdocs.yml`
- links from other docs pages
- validation expectations in `scripts/docs/check.py`
- any app-side direct help routes if a page is opened by key

For day-to-day maintenance, think in three layers:

- source: `docs/`
- build config/tooling: `mkdocs.yml`, `scripts/docs/`
- runtime bundle: `framelab/assets/help/`

Build the offline help bundle:

```bash
python scripts/docs/build.py
```

Validate docs sources and a strict MkDocs build:

```bash
python scripts/docs/check.py
```

## Dependency Notes

The dependency files were trimmed to packages that are actually referenced by the current codebase:

- `PySide6`: desktop UI.
- `numpy`: numeric image and metric work.
- `tifffile`: TIFF dataset I/O.
- `matplotlib`: histogram + analysis plotting surfaces.
- `openpyxl`: `.xlsx` export path exposed by the UI.
- `mkdocs`, `mkdocs-material`, `pymdown-extensions`, `mathjax`: docs build pipeline.

There is currently no dedicated Python freeze toolchain checked into the repo, so the `Build` block is intentionally empty for now.

## Where To Go Next

- New operator: start with [docs/user-guide/quick-start.md](docs/user-guide/quick-start.md)
- Plugin or architecture work: start with [docs/developer-guide/index.md](docs/developer-guide/index.md)
- Packaging or offline help maintenance: see [docs/developer-guide/packaging.md](docs/developer-guide/packaging.md)
