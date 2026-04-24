# Architecture

FrameLab is a Qt desktop application organized around a workflow host window and a manifest-driven plugin system. The architecture is designed so that plugin choice happens before runtime imports, workflow hierarchy is profile-driven rather than depth-driven, dataset work is staged in a predictable pipeline, and page-specific logic stays grouped by responsibility rather than collapsing into one large window module.

## Architectural overview

At a high level, the application has seven major layers:

1. **Process and Qt bootstrap**
2. **Plugin manifest discovery and startup selection**
3. **Workflow profile and workspace loading**
4. **Main window host construction**
5. **Dataset and measurement runtime**
6. **Analysis plugin orchestration**
7. **Offline help and packaged assets**

A useful mental model is:

```text
process start
  -> QApplication + app identity
  -> discover plugin manifests
  -> restore persisted selection
  -> startup selector dialog
  -> resolve enabled plugin set
  -> choose workflow profile + workspace root
  -> build workflow tree from filesystem + profile rules
  -> construct main window
  -> load enabled plugin classes
  -> scan dataset scope
  -> resolve metadata and static scan metrics
  -> explicitly apply downstream metric jobs when requested
  -> build analysis context from available state
  -> push context to loaded analysis plugins
```

## Startup lifecycle

Startup behavior is split between `framelab/app.py`, `framelab/plugins/*`, `framelab/workflow/*`, and `framelab/window.py`.

### 1. Process identity and Qt application

`main()` in `framelab/app.py` does the following before any workflow UI is built:

- prepares process identity for desktop integration
- creates `QApplication`
- applies app identity and icon
- applies the default stylesheet

This stage should remain lightweight. Do not import heavy plugin UI or dataset logic here.

### 2. Manifest discovery before runtime import

The app discovers plugin manifests before importing plugin implementation modules. This is a deliberate design choice. Why it matters:

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

### 4. Workflow profile and workspace loading

The workflow shell is profile-driven. The built-in profiles currently live in `framelab/workflow/profiles.py`. Current built-in profiles:

- `calibration`: `workspace -> camera -> campaign -> session -> acquisition`
- `trials`: `workspace -> trial -> camera -> session -> acquisition`

The trials profile exists, but it should still be treated as experimental in operator documentation. Typed hierarchy loading is owned by `WorkflowStateController` in `framelab/workflow/state.py`. Important architectural point:

- the workflow tree is **not** loaded purely by folder depth
- node type is inferred from the active profile, explicit anchor choice, nodecards, and filesystem heuristics
- campaign session discovery treats `01_sessions/` and `sessions/` as special containers
- session discovery can succeed from either `session_datacard.json` or discoverable acquisition content
- acquisition discovery is tolerant enough to recognize datacard-backed acquisitions even when folder names are less strict than the session-management naming contract

This means workflow behavior should be documented and maintained as a contract, not as a loose convention.

### 5. Main window construction

The enabled plugin set can include both page-embedded plugins and dialog-style tools such as Session Manager or Background Correction, while the host also owns built-in runtime tools such as eBUS inspect/compare. The host window must therefore support both permanent page contributions and transient runtime actions without forcing every tool through the plugin system. `FrameLabWindow` in `framelab/window.py` is then constructed with the enabled plugin ids. During initialization it:

- resolves the enabled plugin set again for safety
- groups enabled manifests by page
- imports enabled plugin entrypoints and collects registered plugin classes
- constructs the shared state controllers:
  - `WorkflowStateController`
  - `MetadataStateController`
  - `DatasetStateController`
  - `MetricsPipelineController`
  - `AnalysisContextController`
- initializes caches, runtime flags, worker references, and plugin registries
- builds the workflow shell through mixins in `framelab/main_window/*`

`FrameLabWindow` remains the long-lived workflow host, but dataset, metric, and analysis-context state are no longer stored only as raw attributes on the window.

## Workflow hierarchy contract

The folder layout matters because several parts of the application depend on it.

### Session containers

For calibration workflows, sessions may be discovered:

- directly under a campaign folder
- under `campaign/01_sessions/`
- under `campaign/sessions/`

This behavior is centralized in `WorkflowStateController._discover_campaign_session_dirs()` and mirrored by `session_manager.resolve_campaign_sessions_root()`.

### Session recognition

A folder looks like a session when either of the following is true:

- it contains `session_datacard.json`
- it yields discoverable acquisitions under the current rules

### Acquisition recognition

A folder looks like an acquisition when either of the following is true:

- it contains `acquisition_datacard.json`
- it matches `acq-####` or `acq-####__label` and contains a `frames/` directory

### Session-management strictness

Session-management operations are intentionally stricter than workflow loading. They only manage acquisition folders matching the acquisition naming contract parsed by `framelab/acquisition_datacard.py`. That distinction is intentional:

- workflow loading tries to stay tolerant enough to open existing data
- structure-authoring tools try to keep the filesystem normalized and predictable

## Runtime data flow

The core runtime pipeline is more important than the module list. Most maintenance work eventually touches one or more stages in this flow:

```text
supported image discovery
  -> path + nodecard/datacard metadata resolution
  -> controller-owned runtime state + caches
  -> static scan metrics and explicit measurement jobs
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

For each discovered image, metadata is resolved through `framelab/metadata.py`. This stage can combine:

- path-derived metadata
- workflow nodecards from `.framelab/nodecard.json`
- acquisition, session, and campaign datacard layers
- eBUS-backed acquisition-wide baseline values for mapped canonical fields
- frame-index-derived override context

This is the authoritative path for turning files into structured per-row metadata. Do not reimplement metadata resolution inside UI code or analysis plugins.

Filename UTC timestamp tokens matching `YYYYMMDD_HHMMSS_mmmZ` are parsed into per-row metadata during this path. When any loaded row has such a timestamp, `DatasetStateController` derives `elapsed_time_s` from the first valid timestamp in the loaded scope order.

### Stage 3: measurement metrics

Dataset scanning computes only lightweight pass-1 values needed for a responsive loaded state, including max pixel, minimum non-zero pixel, resolved metadata, and elapsed time from filename UTC timestamps when present. It does not automatically start downstream dynamic metric workers after scan completion.

The Measure workflow can then explicitly compute per-image metrics such as:

- max pixel
- minimum non-zero pixel
- saturated-pixel count
- Top-K mean/std/SEM
- ROI max/sum/mean/std/SEM
- ROI + Top-K mean/std/SEM
- `DN/ms`
- elapsed time from filename UTC timestamps when present
- background-match status

These results are stored through `MetricsPipelineController`. Dynamic metric computation is delegated to worker classes in `framelab/workers.py` and orchestrated by `MetricsRuntimeMixin`, which applies worker results back into controller-owned state. Global Top-K uses the dynamic metrics path, while ROI-derived modes, including ROI + Top-K, use `RoiApplyWorker` so the Top-K population is selected inside the ROI.

Metric readiness is tracked by named families rather than inferred only from array presence. Current families include static scan, saturation, low signal, Top-K, ROI, ROI Top-K, and background-applied status, with states such as not requested, pending inputs, computing, ready, stale, and failed. Measure-page controls store pending UI values separately from the last applied compute inputs, so changing threshold, low-signal threshold, Top-K count, or Average Mode is a view/input edit until the relevant Apply action runs.

### Stage 4: analysis context build

The Analyze workflow does not re-measure images. It packages the current dataset and metric controller state into an `AnalysisContext` through `framelab/analysis_context.py`. That context is built from:

- measurement-mode-dependent mean/std/SEM values
- per-row metadata
- normalized intensity-derived fields when normalization is enabled
- ROI Top-K values and elapsed-time metadata when available
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

The window should not be treated as the only source of truth for workflow nodes, dataset rows, or measurement arrays anymore.

### State owned by `WorkflowStateController`

The workflow controller owns:

- active workflow profile
- workspace root
- anchor type
- typed node tree
- active node selection
- workflow ancestry and path-to-node resolution

### State owned by `MetadataStateController`

The metadata controller owns:

- nodecard loading and caching
- profile-governance schema views
- effective inherited workflow-node metadata
- metadata validation snapshots

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

The metrics controller owns measurement settings and the latest measurement results:

- static and dynamic metric arrays
- ROI rectangle and ROI-derived arrays
- ROI + Top-K arrays derived from the selected ROI and Top-K count
- normalization and rounding settings
- background configuration, loaded references, and match bookkeeping
- threshold, low-signal, and Top-K pending/applied settings
- per-family metric readiness state
- in-flight metric-job and ROI-apply job lifecycle state

If state affects more than one workflow page, it probably belongs on a shared controller or the host shell rather than inside one page widget.

### State owned by worker objects

Worker objects own temporary job-local computation only. They should not mutate long-lived host state directly. Results must return through signals and be applied in the host thread.

### State owned by plugins

Plugins should own plugin-local UI widgets and plugin-local interpretation state. They should not become hidden alternate sources of truth for workflow, dataset, or measurement state already owned by the host.

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

Supporting controller modules currently live outside `main_window/`:

- `framelab/workflow/state.py`
- `framelab/metadata_state.py`
- `framelab/dataset_state.py`
- `framelab/metrics_state.py`
- `framelab/analysis_context.py`

## Workers, threads, and UI-thread rules

This repo already uses worker threads for expensive per-dataset operations.

### Current asynchronous jobs

- dynamic metric computation via `DynamicStatsWorker`
- dataset-wide ROI and ROI + Top-K application via `RoiApplyWorker`

### Architectural rule

UI widgets and long-lived host state are owned by the UI thread. Workers compute arrays and emit results back to the host. New long-running operations should follow the same pattern:

- prepare a snapshot of the required input state
- run computation in a worker
- apply results only after job id validation in the host

Do not allow workers to read mutable host state repeatedly during execution.
