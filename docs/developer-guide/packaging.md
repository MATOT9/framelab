# Packaging

Packaging for FrameLab is more than building a Python executable. A working distribution depends on code, manifests, runtime assets, local-config behavior, and a current offline-help bundle.

This page documents what must ship, what is generated locally, and what to verify before release.

## Packaging goals

The current packaging model is designed to keep the app:

- shareable as a folder-based desktop application
- reasonably compact
- free of unnecessary runtime browser dependencies
- able to open documentation without internet access

## Runtime asset classes

A correct package includes more than Python modules.

### 1. Application code

Required:

```text
framelab/**
```

This includes the host window, workflow mixins, plugin loaders, datacard services, session-management helpers, measurement logic, eBUS tooling, and help helpers.

### 2. Plugin manifests and plugin packages

Required:

```text
framelab/plugins/**
```

Why it matters:

- manifests are needed for startup discovery and dependency validation
- plugin Python modules are needed for enabled-only runtime import

A package with plugin code but missing manifest files is incomplete.

### 3. Bundled runtime assets

Required assets currently include at least:

```text
framelab/assets/app_icon.*
framelab/assets/acquisition_field_mapping.default.json
framelab/assets/ebus_parameter_catalog.default.json
framelab/assets/help/**
```

These support:

- window/app identity
- default mapping fallback for datacard authoring
- default eBUS catalog fallback
- offline documentation access from the Help menu

### 4. Local config directory

The repo uses a shareable in-app config directory:

```text
config/
```

Typical runtime files include:

- `config/config.ini`
- `config/plugin_selection.json`
- `config/acquisition_field_mapping.json` when a user saves a local mapping override
- `config/ebus_parameter_catalog.json` when a user edits the local catalog

Treat this directory as user-local mutable state, not as a packaged default asset tree.

## What is bundled versus what is generated locally

### Bundled with the app

These are expected to ship with the distribution:

- Python package code
- plugin manifests and plugin source
- icons
- default acquisition mapping asset
- default eBUS catalog asset
- bundled offline help HTML

### Generated or modified locally

These are created or updated on the target machine:

- plugin selection config
- scan skip-pattern config
- user-edited mapping override file
- user-edited eBUS catalog file
- any rebuilt offline-help output if docs are rebuilt locally

## Offline documentation packaging

The offline-help model is a deliberate packaging choice.

Source chain:

```text
docs/*.md
  -> MkDocs build
  -> static HTML site
  -> copied to framelab/assets/help/
  -> opened by Help menu through help_docs.py
```

### Why this model is preferred

- no `QtWebEngine` dependency in the runtime app
- no internet dependency for local help
- one source format for docs instead of duplicating help inside Qt widgets

## Docs build pipeline

The docs build script is:

```bash
python3 scripts/docs/build.py
```

It:

- runs MkDocs build
- stages MathJax assets into the built site
- copies the finished site into `framelab/assets/help/` unless `--no-copy` is used

The docs validation script is:

```bash
python3 scripts/docs/check.py
```

It:

- checks that required docs source files exist
- runs a strict docs build into a check-site directory
- verifies that key built HTML outputs exist

## Current packaging cautions

### Docs dependency bootstrap message is still only a hint

`scripts/docs/build.py` may still refer to a `requirements.txt`-style installation flow even when the repo does not ship one. Treat the message as a toolchain hint, not as guaranteed complete dependency management.

### Keep docs layout and build scripts synchronized

The current docs tree uses nested user-guide paths such as:

- `docs/user-guide/data/datacard-wizard.md`
- `docs/user-guide/data/session-manager.md`
- `docs/user-guide/analysis/intensity-trend-explorer.md`

When pages are added, moved, or renamed, update all of the following together:

- `mkdocs.yml`
- `scripts/docs/check.py`
- any direct help-page routes if the app opens a page by key

This is a maintenance rule, not just a documentation nicety.

## Packaging checklist

Before producing a release or handoff build, verify all of the following.

### Application startup

- app launches cleanly
- startup plugin selector opens
- saved plugin selection can be loaded without error
- the main window opens with the selected plugin set

### Plugin system

- manifests are present in packaged layout
- enabled plugins load correctly
- disabled plugins do not need to import for startup selection
- runtime dialog tools such as Session Manager, eBUS compare, and Background Correction still open

### Runtime assets

- app icon resolves correctly
- default acquisition mapping asset is present
- default eBUS catalog asset is present
- bundled help directory contains `index.html`
- Help menu opens bundled pages successfully

### Data and measurement workflows

- dataset scan works in packaged layout
- local config files can be created under `config/`
- measurement workers run correctly in the packaged environment
- background correction and ROI workflows still function
- session-manager folder mutations still reload or unload the current dataset correctly when needed

### Documentation

- `framelab/assets/help/index.html` exists
- quick start, session-manager, developer guide, reference, and troubleshooting pages open
- MathJax-rendered pages display correctly

## Where packaging-sensitive behavior lives

- app startup and window bootstrapping -> `framelab/app.py`
- offline help resolution and browser launch -> `framelab/help_docs.py`
- config-path behavior and legacy migration -> `framelab/scan_settings.py`
- docs build pipeline -> `scripts/docs/build.py`
- docs validation -> `scripts/docs/check.py`

## Common packaging mistakes

Avoid these mistakes:

- shipping plugin source without manifest files
- shipping manifests without the corresponding plugin modules
- forgetting to refresh `framelab/assets/help/` after docs changes
- assuming config files are bundled defaults rather than mutable local state
- treating a successful Python package build as proof that Help integration works
- adding docs pages without updating nav and validation checks

## Recommended release flow

A practical release sequence is:

1. validate docs source layout and navigation
2. rebuild bundled help
3. run docs validation
4. run the app from the packaged layout
5. verify plugin startup, scan, session-manager actions, measurement, analysis, and Help paths
6. only then freeze or distribute the build

The packaging process should validate the real runtime layout, not just the importability of modules.
