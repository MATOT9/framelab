# FrameLab Imaging Analysis Workbench

FrameLab is a desktop workbench for image-based acquisition review. It helps you scan TIFF datasets, inspect hierarchical metadata and datacards, manage workflow structure, review eBUS configuration files, compute image measurements, and hand those results to analysis plugins.

This README is intentionally lightweight. It gives a newcomer enough context to launch the app, understand the expected filesystem model, run the tests, and find the important parts of the repo. The full operator and maintenance guidance lives in [docs/](docs/).

## What The App Covers

- **Data intake**: recursive dataset scan, skip rules, metadata source selection, datacard awareness, and compact preflight checks.
- **Workflow context**: profile-driven workspace selection with a persistent Workflow Explorer and Metadata Inspector in the main shell.
- **Structure tooling**: workflow-native session/acquisition authoring plus legacy session repair flows that still remain outside the main workflow shell.
- **Measurement**: table + preview workflows for ROI, thresholding, Top-K, normalization, and background-correction flows.
- **Analysis**: plugin-driven plots and derived tables using a prepared analysis context instead of raw UI state.
- **Offline help**: the same Markdown source in `docs/` is bundled into the app as static HTML help.

## Workflow Profiles and Required Layout

For most work, use the **Calibration** workflow profile.

Its logical hierarchy is:

```text
workspace -> camera -> campaign -> session -> acquisition
```

Recommended calibration layout:

```text
workspace/
  camera/
    campaign/
      01_sessions/
        YYYY-MM-DD__sess01/
          session_datacard.json
          acquisitions/
            acq-0001__dark/
              acquisition_datacard.json
              frames/
              notes/
              thumbs/
            acq-0002__iris/
              acquisition_datacard.json
              frames/
              notes/
              thumbs/
```

Important code-backed layout rules:

- sessions may live directly under the campaign folder or under `01_sessions/` or `sessions/`
- `session_datacard.json.paths.acquisitions_root_rel` can redirect the acquisitions root
- session-management tools only manage acquisition folders matching `acq-####` or `acq-####__label`
- the workflow loader can still discover acquisitions from datacards even when the folder name is less strict, but that is not the recommended operating model

The **Trials** profile exists, but it should still be treated as experimental.

## Repository Structure

- `framelab/`: main application package.
- `framelab/main_window/`: host window shell and the Data / Measure / Analyze page mixins.
- `framelab/workflow/`: workflow profiles, typed hierarchy models, and workflow state loading.
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

On first launch, choose a workflow profile and workspace root. After that:

- use the left **Workflow Explorer** dock to change the active node scope
- use the right **Metadata Inspector** dock to inspect inherited and local metadata
- use **Workflow Explorer -> Structure** for session and acquisition create/rename/delete/reindex work
- keep **Session Manager (Legacy)** only for acquisition-datacard copy/paste or acquisition-local eBUS toggles that still live outside the workflow shell

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

The full docs site lives in `docs/` and covers operator workflows, required folder structure, architecture, plugin contracts, and packaging details.

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

## Native Backend Build

The native backend builds as:

- core static library: `framelab_native`
- Python extension module: `_native` written into `framelab/native/`

The supported helper entrypoint is:

```bash
python tools/build_native_backend.py
```

That script configures CMake against the active interpreter by default and writes the resulting extension into `framelab/native/`.

### Common Build Dependencies

- CMake 3.21 or newer
- a C11-capable compiler
- Python headers for the target interpreter
- NumPy headers for the target interpreter

### Native Build on Linux

Ubuntu/Debian example dependencies:

```bash
sudo apt update
sudo apt install -y build-essential cmake python3-dev
python -m pip install -r requirements.txt
```

Build the extension:

```bash
python tools/build_native_backend.py --build-type Release
```

### Native Build on Windows

Recommended dependencies:

- Visual Studio Build Tools 2022 or Visual Studio 2022 with the Desktop C++ workload
- CMake on `PATH`
- the target Python environment with `numpy` installed

Build from a developer shell or any shell where MSVC and CMake are available:

```powershell
python tools\build_native_backend.py --build-type Release
```

Optional generator/platform example:

```powershell
python tools\build_native_backend.py --generator "Visual Studio 17 2022" --platform x64
```

### Cross-Compile on Ubuntu for Windows

The repo now ships a MinGW-w64 toolchain file:

- `native/cmake/toolchains/mingw-w64-x86_64.cmake`

Install the host-side cross toolchain:

```bash
sudo apt update
sudo apt install -y cmake mingw-w64
python -m pip install -r requirements.txt
```

Cross-compiling the Python extension requires Windows-target Python artifacts, not just the host Linux interpreter. You must provide:

- Windows Python include directory
- Windows NumPy include directory
- Windows Python import library compatible with your toolchain

Example:

```bash
python tools/build_native_backend.py \
  --target-system windows \
  --toolchain-file native/cmake/toolchains/mingw-w64-x86_64.cmake \
  --output-dir native/staging-windows \
  --python-include-dir /opt/python-win/include \
  --python-numpy-include-dir /opt/python-win/Lib/site-packages/numpy/_core/include \
  --python-library /opt/python-win/libs/libpython312.a
```

Notes:

- `--python-include-dir` and `--python-numpy-include-dir` must be provided together when overriding target Python artifacts.
- For Windows cross builds, the Python import library is required.
- If you want the helper to keep the built binary out of the source tree while iterating, point `--output-dir` at a staging folder and copy `_native.pyd` into `framelab/native/` only after the app is closed.

### Useful Build Helper Options

- `--build-type Release|RelWithDebInfo|Debug`
- `--generator <cmake-generator>`
- `--platform <cmake-platform>`
- `--toolchain-file <path>`
- `--target-system native|linux|windows`
- `--python <python-executable>`
- `--python-include-dir <path>`
- `--python-numpy-include-dir <path>`
- `--python-library <path>`
- `--enable-ipo` / `--disable-ipo`

### Troubleshooting

- If the build fails with a linker error saying `_native.pyd` or `_native.so` cannot be opened, close any running FrameLab or `python.exe` process that has loaded the extension.
- If CMake cannot find Python/NumPy during a cross build, provide explicit target artifact paths instead of relying on interpreter discovery.
- On Windows, IPO/LTO is disabled by default for conservative extension builds. Enable it explicitly only when the toolchain is known-good.

## Where To Go Next

- New operator: start with [docs/user-guide/quick-start.md](docs/user-guide/quick-start.md)
- Required hierarchy and naming: [docs/user-guide/workflow-structure.md](docs/user-guide/workflow-structure.md)
- Plugin or architecture work: start with [docs/developer-guide/index.md](docs/developer-guide/index.md)
- Packaging or offline help maintenance: see [docs/developer-guide/packaging.md](docs/developer-guide/packaging.md)
