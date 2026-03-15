# UI Structure

The FrameLab UI is intentionally split into a host shell plus page-specific mixins and plugin-owned widgets. The goal is not just file organization. The split reflects ownership boundaries: the host owns workflow state and shell behavior, while plugins own plugin-local UI and interpretation logic.

## Structural overview

The top-level host class is `FrameLabWindow` in `framelab/window.py`. It is assembled from mixins under `framelab/main_window/`:

- `WindowChromeMixin`
- `DataPageMixin`
- `DatasetLoadingMixin`
- `InspectPageMixin`
- `MetricsRuntimeMixin`
- `AnalysisPageMixin`
- `WindowActionsMixin`

This is the primary UI organization rule of the repo. If new UI behavior fits an existing workflow responsibility, add it to the owning mixin rather than expanding `window.py` indiscriminately.

## Host window responsibilities

`FrameLabWindow` is the UI host and shared-state owner. It is responsible for:

- window identity, size, and session-level defaults
- workflow selection, active-node tracking, and workflow breadcrumb state
- metadata-state control for effective/local workflow-node metadata
- long-lived dataset, metric, ROI, cache, and background state
- enabled plugin bookkeeping
- table column policy and visibility state
- worker-thread references and job ids
- building the workflow shell through mixins

It is not intended to hold every page method directly. The class body should primarily define shared constants, state initialization, and mixin composition.

## Workflow shell structure

The main shell is a tabbed workflow:

1. **Data**
2. **Measure**
3. **Analyze**

The Analyze tab is conditional. It is only shown when at least one analysis plugin has been loaded. Around those tabs, the shell now also owns:

- a compact workflow breadcrumb/path bar above the tabs
- a left **Workflow Explorer** dock for active-node selection and session-structure authoring
- a right **Metadata Inspector** dock for node-metadata editing and provenance review

The explorer intentionally carries a small active-lineage rail so the current path reads as structure, not just as another badge row. The metadata inspector keeps provenance compact through source badges plus a source-node column instead of large explanation-heavy panels. This is an important UI policy detail: tab visibility is partly derived from plugin availability, not only from hard-coded shell structure.

## Mixin responsibilities

### `WindowChromeMixin`

This mixin owns shell-level UI concerns:

- menu bar
- toolbar
- status bar
- workflow breadcrumb row
- workflow and metadata dock construction
- theme application
- Help menu actions
- column-visibility menus
- plugin-menu population hooks

If a feature changes app-wide chrome rather than page-local workflow behavior, it belongs here.

### `DataPageMixin`

This mixin owns Data-tab widgets and interactions, including metadata controls and the data table. Use it for:

- controls that affect how rows are grouped or inspected in the Data stage
- Data-page widget layout and signals
- Data-page-only interactions that do not require scan or cache internals

### `DatasetLoadingMixin`

This mixin owns dataset lifecycle operations and image access helpers. Use it for:

- browse/open folder flow
- recursive TIFF discovery
- skip-pattern handling during scan
- image caching
- corrected-image caching
- background-aware image retrieval helpers

This mixin is the correct place for scan and cache behavior, even when those operations are triggered from the Data or Measure pages.

### `InspectPageMixin`

This mixin owns Measure-tab UI layout and user interactions. Use it for:

- threshold controls
- average-mode controls
- ROI tools
- preview and histogram widgets
- background-correction controls
- Measure-page labels and state presentation

### `MetricsRuntimeMixin`

This mixin owns asynchronous metric job orchestration. Use it for:

- starting and cancelling background metric jobs
- applying worker results back to host state
- ROI-apply progress handling
- UI updates triggered by completed worker jobs

This separation matters because measurement runtime is not only widget behavior; it is host-state mutation coordinated with workers.

### `AnalysisPageMixin`

This mixin owns analysis plugin hosting. Use it for:

- analysis plugin instantiation
- side-rail and workspace stacked-widget hosting
- active analysis-plugin selection UI
- analysis-context construction
- dynamic visibility policy based on plugin UI capabilities

A practical maintenance note: some internal variable names still use `profile` for historical reasons, but the user-facing concept is an **analysis plugin**, not a saved analysis profile.

### `WindowActionsMixin`

This mixin owns menu or shell actions that do not fit entirely inside a single page-layout mixin. Typical examples include ROI save/load and table export behavior.

## Shared-state model

The UI is modular in file layout, but the session model is still centralized.

### Important rule

The host window is the source of truth for shared workflow state. This includes:

- workflow workspace/profile/active-node state
- metadata inspector / workflow explorer visibility state
- dataset paths and row metadata
- measurement arrays
- ROI selection
- normalization state
- background configuration and library
- plugin instance list
- theme mode
- column visibility overrides

Mixins operate on that shared state. They are not independent widgets with isolated data models.

### Why this matters

When refactoring, do not mistake file separation for state separation. Moving a method between mixins is easy. Moving state ownership away from the host is an architectural change. Two examples added by the workflow refactor are:

- `workflow_state_controller` for typed node hierarchy, active-node selection, and profile context
- `metadata_state_controller` for nodecard loading, schema/governance resolution, templates, and effective metadata validation

## Dynamic visibility policy

The host UI includes a real policy layer for what is shown. Examples:

- the Analyze tab only appears when analysis plugins exist
- plugin UI capabilities can request additional data or measurement columns
- metadata controls can be shown or emphasized based on plugin needs
- some measure-table columns depend on the active average mode

This behavior is coordinated in host-side page mixins. Do not hard-code ad hoc visibility changes inside unrelated widgets when a policy-driven host path already exists.

## Host/plugin boundary

This is one of the most important UI boundaries in the app.

### The host owns

- workflow tabs
- the analysis-plugin selector
- the left-rail controls stack and right-side workspace stack that contain analysis-plugin views
- plugin menu containers under the **Plugins** menu
- shared dataset and measurement context
- theme propagation and visibility policy

### The plugin owns

- its plugin-local controls widget, workspace widget, or legacy combined widget
- plugin-local rendering state
- interpretation of the provided context
- optional plugin-local menu actions inside the host-provided plugin menu

### Boundary rule

Plugins should consume host-provided context and UI hooks. They should not silently become alternate owners of dataset state, shell structure, or cross-page UI policy. For analysis plugins, prefer the split host API when the plugin has a natural control surface and a natural workspace surface:

- `create_controls_widget(parent)`
- `create_workspace_widget(parent)`

`create_widget(parent)` remains the fallback for legacy or compact plugin layouts, but new host-aware analysis plugins should let the page mixin own the outer shell structure.

## Threading and UI updates

The UI uses workers for long-running measurement operations. All widget mutation and long-lived host-state application still belongs in the UI thread.

### Maintenance rule

If a new feature requires a long-running dataset-wide computation:

1. snapshot the required host state
2. run the computation in a worker
3. emit results back through signals
4. validate job identity before applying results
5. update widgets from the host thread only

Avoid direct widget access from worker code.

## Help integration

The UI deliberately avoids embedding long-form help inside Qt widgets. Instead:

- Help menu actions call `framelab/help_docs.py`
- help pages are resolved to local HTML files under `framelab/assets/help/`
- pages open in the desktop browser or system URL handler

This keeps runtime lighter and prevents the app from maintaining a second documentation system inside the Qt layer.

## Where to make common UI changes

### Change menu items, toolbar actions, Help entries, or theme behavior

Edit:

- `framelab/main_window/chrome.py`

### Change scan controls or Data-page widgets

Edit:

- `framelab/main_window/data_page.py`
- and `dataset_loading.py` if scan behavior changes

### Change Measure-page controls, ROI tools, or preview layout

Edit:

- `framelab/main_window/inspect_page.py`

### Change measurement job lifecycle or worker result application

Edit:

- `framelab/main_window/metrics_runtime.py`
- `framelab/workers.py`

### Change analysis-plugin host behavior or context construction

Edit:

- `framelab/main_window/analysis.py`

### Change plugin-local widget layout

Edit the plugin package itself under `framelab/plugins/` rather than trying to force plugin-local UI into the host mixins.
