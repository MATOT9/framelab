# Documentation Layout

This repository keeps the documentation in two distinct forms:

- `docs/` is the editable source tree.
- `framelab/assets/help/` is the generated offline help bundle consumed by the app at runtime.

Treat those two locations as having different ownership. Source files are maintained by developers. The bundled help tree is build output and must be regenerated, not edited by hand.

## Why this split exists

The app opens local HTML help pages from the **Help** menu rather than rendering long-form Markdown inside the Qt interface. That design keeps documentation authoring, styling, navigation, and search in the docs toolchain while still allowing the packaged application to ship with an offline copy.

The practical consequence is simple:

```text
Markdown sources in docs/ -> MkDocs build output -> copied into framelab/assets/help/
```

If a help page looks stale in the running app, the usual cause is that the bundled help copy was not rebuilt after the Markdown source changed.

## Repository locations and ownership

### `docs/`

Editable documentation source tree.

This folder contains:

- top-level navigation pages such as `docs/index.md`
- audience-specific sections such as `docs/user-guide/`, `docs/developer-guide/`, `docs/reference/`, and `docs/troubleshooting/`
- shared static assets under `docs/assets/`
- docs-specific styling under `docs/stylesheets/`

Edit Markdown, placeholder figures, and docs CSS here.

### `mkdocs.yml`

MkDocs site configuration.

This file controls:

- site navigation
- theme options
- Markdown extensions
- CSS and JavaScript inclusion
- build behavior such as `use_directory_urls`

When a page is added, moved, or renamed, this file usually needs to be updated as well.

### `scripts/docs/`

Documentation maintenance scripts.

The current scripts serve two different purposes:

- `build.py` builds the HTML documentation site and can copy it into the bundled runtime location
- `check.py` validates that required source files exist and that a strict build completes successfully

These scripts are part of the docs maintenance contract. If the docs tree is reorganized, review both scripts along with `mkdocs.yml`.

### `framelab/assets/help/`

Generated offline-help bundle used by the application.

The Help menu opens files from this tree through the offline help helpers in the runtime package. Do not hand-edit files here. Any manual change will be overwritten by the next docs build.

### `.docs_build/`

Temporary build output.

This folder is disposable and may be removed at any time. It is used for intermediate site output such as:

- `.docs_build/site/` for a normal build
- `.docs_build/check-site/` for strict validation builds

## Source-tree organization inside `docs/`

The documentation set is intentionally split by question type rather than by implementation package.

### `docs/user-guide/`

Operator-facing workflow documentation.

Use this section for topics such as:

- scanning a dataset
- choosing metadata source
- computing measurements
- interpreting analysis plots
- using built-in workflows and plugins

### `docs/developer-guide/`

Maintenance and extension documentation.

Use this section for topics such as:

- startup and runtime architecture
- UI ownership and module boundaries
- plugin discovery and runtime contracts
- datacard system lifecycle
- packaging and release expectations

### `docs/reference/`

Contract-style lookup pages.

Use this section when the question is about exact file locations, schema keys, manifest fields, or shortcut scope rather than workflow.

### `docs/troubleshooting/`

Cross-cutting triage and failure-routing pages.

Use this section to decide which subsystem is failing and which deeper guide to consult next.

## Build pipeline

The normal docs build flow is:

1. read Markdown and assets from `docs/`
2. build a static site with MkDocs
3. stage required vendor assets into the built site
4. optionally copy the built site into `framelab/assets/help/`

One implementation detail matters here: MathJax assets are staged into the built site during the docs build. That means the rendered site is not only Markdown transformed by MkDocs; it is also post-processed into the runtime bundle expected by the app.

## What to edit and what not to edit

Edit these directly:

- `docs/**/*.md`
- `docs/assets/**`
- `docs/stylesheets/**`
- `mkdocs.yml`
- `scripts/docs/*.py` when docs build behavior changes

Do **not** edit these as a way of making lasting documentation changes:

- `framelab/assets/help/**`
- `.docs_build/**`

Generated HTML output is a product of the source tree. Lasting changes belong in the source tree, not in the generated copy.

## Common maintenance tasks

### Update documentation content

1. Edit the Markdown source under `docs/`.
2. Rebuild the docs bundle.
3. Verify the page from the bundled help copy opened by the app.

### Add or rename a page

When adding, moving, or renaming a page, update all of the following as needed:

- the Markdown file in `docs/`
- navigation entries in `mkdocs.yml`
- any cross-links inside other docs pages
- validation expectations in `scripts/docs/check.py`
- any runtime help-page routing if the page is opened directly from the app

### Refresh the offline help bundle

Run:

```bash
python3 scripts/docs/build.py
```

This rebuilds the static site and updates `framelab/assets/help/` unless copy is explicitly disabled.

### Validate docs sources and strict build behavior

Run:

```bash
python3 scripts/docs/check.py
```

This checks required source files and performs a strict build into the disposable validation output tree.

## Practical maintenance rule

Keep the documentation system mentally split into three layers:

- **source**: `docs/`
- **build configuration and tooling**: `mkdocs.yml`, `scripts/docs/`
- **runtime bundle**: `framelab/assets/help/`

Most documentation work should touch only the first layer. Reorganizations and build issues usually touch the second. The third should normally change only as a generated result of the first two.
