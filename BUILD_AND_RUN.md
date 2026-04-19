# Build And Run

This is the setup, launch, docs, native, and packaging entry point.

## Environment

Conda or Mamba:

```bash
mamba create -n framelab python=3.12
conda activate framelab
mamba install --file requirements-conda.txt
```

Pip or venv:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt` is pip-oriented. `requirements-conda.txt` is conda-oriented. The `env_dev.yml` and `env_run.yml` files are environment-oriented inputs for fuller setup flows.

## Launch

```bash
python launcher.py
```

or:

```bash
python -m framelab
```

On startup, the app discovers plugin manifests, resolves saved plugin selection, shows the plugin selector, then opens the workflow window.

## Workspace And Preferences

- Persistent global preferences live in `config/preferences.ini`.
- Plugin startup selection lives in `config/plugin_selection.json`.
- Reopenable session state lives in `.framelab` workspace documents saved or opened through the File menu.
- Without opening a `.framelab` workspace file, the app should start like a fresh session except for preferences.

## Documentation Build

Build the docs and copy bundled help:

```bash
python scripts/docs/build.py --strict
```

Build without refreshing bundled help:

```bash
python scripts/docs/build.py --strict --no-copy
```

Validate docs sources and a strict build:

```bash
python scripts/docs/check.py
```

If MathJax assets are not discovered automatically, set `FRAMELAB_MATHJAX_DIR` to the active environment's MathJax `es5` directory.

## Native Backend

Build the optional native backend:

```bash
python tools/build_native_backend.py
```

The helper configures CMake for the active interpreter and writes the resulting Python extension into `framelab/native/`.

Common dependencies:

- CMake 3.21 or newer.
- A C11-capable compiler.
- Python headers for the target interpreter.
- NumPy headers for the target interpreter.

## Standalone Packaging

Check the Nuitka package configuration:

```bash
python tools/build_nuitka_app.py --check
```

Run a small smoke compile:

```bash
python tools/build_nuitka_app.py --smoke
```

Build a clean standalone package:

```bash
python tools/build_nuitka_app.py --clean
```

The package helper currently targets host-native Linux and Windows folder builds from `launcher.py`.

## Local Config Caution

The `config/` directory is local mutable app state. Do not treat it as a bundled default asset tree. Factory defaults that should ship with the app belong under `framelab/assets/`.
