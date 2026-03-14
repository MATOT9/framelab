# Architecture

FrameLab is a Qt desktop application organized around a workflow host window and a manifest-driven plugin system. The architecture is designed so that plugin choice happens before runtime imports, dataset work is staged in a predictable pipeline, and page-specific logic stays grouped by responsibility rather than collapsing into one large window module.

## Architectural overview

At a high level, the application has six major layers:

1. **Process and Qt bootstrap**
2. **Plugin manifest discovery and startup selection**
3. **Main window host construction**
4. **Dataset and measurement runtime**
5. **Analysis plugin orchestration**
6. **Offline help and packaged assets**

A useful mental model is:

```text
process start
  -> QApplication + app identity
  -> discover plugin manifests
  -> restore persisted selection
  -> startup selector dialog
  -> resolve enabled plugin set
  -> construct main window
  -> load enabled plugin classes
  -> scan dataset
  -> resolve metadata
  -> compute metrics
  -> build analysis context
  -> push context to loaded analysis plugins
```

## Startup lifecycle

Startup behavior is split between `framelab/app.py`, `framelab/plugins/*`, and `framelab/window.py`.

### 1. Process identity and Qt application

`main()` in `framelab/app.py` does the following before any workflow UI is built:

- prepares process identity for desktop integration
- creates `QApplication`
- applies app identity and icon
- applies the default stylesheet

This stage should remain lightweight. Do not import heavy plugin UI or dataset logic here.

### 2. Manifest discovery before runtime import

The app discovers plugin manifests before importing plugin implementation modules. This is a deliberate design choice.

Why it matters:

- the startup selector can list plugins without importing them
- dependency closure can be resolved before the main window is created
- disabled plugins do not incur import or widget-instantiation cost

Manifest discovery and validation live in `framelab/plugins/registry.py`.

### 3. Persisted selection and startup dialog

The selection layer in `framelab/plugins/selection.py`:

- loads persisted enabled plugin ids from local config
- defaults to all discovered plugins when no selection file exists
- resolves transitive dependencies
- presents a startup dialog that enforces dependency-consistent checkbox state
- writes the final enabled set back to local config

At this point the app still has not built the main workflow window.

### 4. Main window construction

The enabled plugin set can include both page-embedded plugins and dialog-style tools such as Session Manager, eBUS compare/inspect helpers, or Background Correction. The host window must therefore support both permanent page contributions and transient runtime actions from the same plugin system.


`FrameLabWindow` in `framelab/window.py` is then constructed with the enabled plugin ids.

During initialization it:

- resolves the enabled plugin set again for safety
- groups enabled manifests by page
- imports enabled plugin entrypoints and collects registered plugin classes
- constructs the shared state controllers:
  - `DatasetStateController`
  - `MetricsPipelineController`
  - `AnalysisContextController`
- initializes caches, runtime flags, worker references, and plugin registries
- builds the workflow shell through mixins in `framelab/main_window/*`

`FrameLabWindow` remains the long-lived workflow host, but dataset, metric, and
analysis-context state are no longer stored only as raw attributes on the window.

## Runtime data flow

The core runtime pipeline is more important than the module list. Most maintenance work eventually touches one or more stages in this flow:

```text
supported image discovery
  -> path + datacard metadata resolution
  -> controller-owned runtime state + caches
  -> measurement metrics
  -> analysis context build
  -> plugin update
```

### Stage 1: dataset discovery

The Data workflow triggers folder scan and supported-image discovery.
`DatasetStateController` stores:

- loaded dataset root
- discovered row paths
- cached metadata per path
- metadata-source selection and availability
- metadata-table visible row ordering
- current selected row index

Dataset discovery and image loading helpers live primarily in `framelab/main_window/dataset_loading.py`.

### Stage 2: metadata resolution

For each discovered image, metadata is resolved through `framelab/metadata.py`.

This stage can combine:

- path-derived metadata
- acquisition, session, and campaign datacard layers
- eBUS-backed acquisition-wide baseline values for mapped canonical fields
- frame-index-derived override context

This is the authoritative path for turning files into structured per-row metadata. Do not reimplement metadata resolution inside UI code or analysis plugins.

### Stage 3: measurement metrics

The Measure workflow computes per-image metrics such as:

- max pixel
- minimum non-zero pixel
- saturated-pixel count
- Top-K mean/std/SEM
- ROI mean/std/SEM
- `DN/ms`
- background-match status

These results are stored as NumPy arrays on the host window. Dynamic metric computation is delegated to worker classes in `framelab/workers.py` and orchestrated by `MetricsRuntimeMixin`.
These results and their settings now live in `MetricsPipelineController`. Dynamic
metric computation is still delegated to worker classes in `framelab/workers.py`
and orchestrated by `MetricsRuntimeMixin`, but the mixin now applies worker
results back into controller-owned state.

### Stage 4: analysis context build

The Analyze workflow does not re-measure images. It packages the current
dataset and metric controller state into an `AnalysisContext` through
`framelab/analysis_context.py`.

That context is built from:

- measurement-mode-dependent mean/std/SEM values
- per-row metadata
- normalized intensity-derived fields when normalization is enabled
- background state flags and reference labels

The analysis plugin interface should be treated as a consumer of this prebuilt context, not as a place to reach back into raw host state ad hoc.

## State ownership

A maintainer should treat state ownership as a first-class architectural rule.

### State owned by `FrameLabWindow`

The host window owns UI-shell and runtime-integration state, including:

- image and corrected-image caches
- active worker and thread references
- plugin instances and currently enabled plugin ids
- column-visibility overrides and theme state
- processing-failure banners and status text

The window should not be treated as the only source of truth for dataset rows or
measurement arrays anymore.

### State owned by `DatasetStateController`

The dataset controller owns long-lived dataset/session selection state:

- scanned dataset root
- discovered paths
- per-path metadata cache
- active and preferred metadata-source mode
- JSON-metadata availability
- metadata-table visible row ordering
- currently selected dataset row

### State owned by `MetricsPipelineController`

The metrics controller owns measurement settings and the latest measurement
results:

- static and dynamic metric arrays
- ROI rectangle and ROI-derived arrays
- normalization and rounding settings
- background configuration, loaded references, and match bookkeeping
- threshold and Top-K settings
- in-flight metric-job and ROI-apply job lifecycle state

If state affects more than one workflow page, it probably belongs on a shared
controller or the host shell rather than inside one page widget.

### State owned by worker objects

Worker objects own temporary job-local computation only. They should not mutate long-lived host state directly. Results must return through signals and be applied in the host thread.

### State owned by plugins

Plugins should own plugin-local UI widgets and plugin-local interpretation state. They should not become hidden alternate sources of truth for dataset or measurement state already owned by the host.

## Mixins and subsystem boundaries

The window is composed from mixins under `framelab/main_window/`. This is a structural boundary, not just a style choice.

### Current host composition

- `WindowChromeMixin` -> menus, toolbar, status bar, theme, help entry points
- `DataPageMixin` -> Data tab widgets and interactions
- `DatasetLoadingMixin` -> folder scan, image loading, cache management, background-aware image access
- `InspectPageMixin` -> Measure tab widgets, ROI controls, background controls, preview wiring
- `MetricsRuntimeMixin` -> asynchronous metric jobs and ROI apply jobs
- `AnalysisPageMixin` -> analysis plugin loading, stacked widget hosting, context delivery
- `WindowActionsMixin` -> file/menu actions that do not belong entirely to one page widget

When adding behavior, put it in the mixin that owns the workflow or shell responsibility. Do not default to adding everything in `window.py`.

Supporting controller modules currently live outside `main_window/`:

- `framelab/dataset_state.py`
- `framelab/metrics_state.py`
- `framelab/analysis_context.py`

## Workers, threads, and UI-thread rules

This repo already uses worker threads for expensive per-dataset operations.

### Current asynchronous jobs

- dynamic metric computation via `DynamicStatsWorker`
- dataset-wide ROI application via `RoiApplyWorker`

### Architectural rule

UI widgets and long-lived host state are owned by the UI thread. Workers compute arrays and emit results back to the host. New long-running operations should follow the same pattern:

- prepare a snapshot of the required input state
- run computation in a worker
- apply results only after job id validation in the host

Do not allow workers to read mutable host state repeatedly during execution.

## Plugin architecture in context

The plugin system is intentionally split into two phases:

### Phase 1: metadata-only discovery

Manifest scanning identifies what could be loaded.

### Phase 2: enabled-only runtime import

Only the enabled plugin entrypoints are imported. Those entrypoints self-register classes with the page registry.

This separation is central to startup cost, dependency closure, and change safety. If a future refactor removes the separation between manifest discovery and runtime import, it should be treated as an architectural change, not a refactor detail.

## Help and documentation architecture

Offline help is intentionally external to the Qt widget tree.

Source chain:

```text
docs/*.md
  -> MkDocs build
  -> static HTML bundle
  -> framelab/assets/help/
  -> Help menu opens local HTML pages in external viewer
```

This keeps runtime free of embedded browser dependencies such as `QtWebEngine`, and it preserves one documentation source format.

## Change-safe boundaries

Use these rules when deciding where to make modifications:

- **Change startup selection behavior** -> `framelab/plugins/selection.py`
- **Change manifest parsing/validation** -> `framelab/plugins/registry.py`
- **Change shared dataset state** -> `framelab/dataset_state.py`
- **Change shared metric/background state** -> `framelab/metrics_state.py`
- **Change analysis-context assembly** -> `framelab/analysis_context.py`
- **Change workflow shell behavior** -> `framelab/window.py` and the appropriate `main_window/*` mixin
- **Change measurement computation** -> `framelab/workers.py`, `framelab/background.py`, and Measure-stage mixins
- **Change metadata semantics** -> `framelab/metadata.py`, `framelab/frame_indexing.py`, and datacard-authoring layers
- **Change analysis-plugin data contract** -> `framelab/plugins/analysis/_base.py` and `framelab/analysis_context.py`
- **Change docs bundling or offline help behavior** -> `scripts/docs/*` and `framelab/help_docs.py`

## Architecture invariants worth preserving

These are the current architectural invariants that future work should preserve unless there is a deliberate redesign:

1. Plugin discovery must not require importing all plugin code.
2. Disabled plugins should not be imported at runtime.
3. Dataset rows must be formed through the central metadata path, not plugin-local ad hoc parsing.
4. Analysis plugins must consume host-built context rather than silently re-reading raw files.
5. Long-running dataset-wide operations should execute in workers, not in the UI thread.
6. Offline docs remain Markdown-source -> static HTML -> bundled help assets.

If a change crosses one of those boundaries, document it explicitly in the commit or design note.
