# Plugin System

The plugin system is the app's extension boundary. It is designed so that plugin metadata can be discovered without importing plugin code, startup enablement can be resolved before the main window exists, and only the enabled entrypoints are imported at runtime. This page documents the maintainer-facing contract: discovery, validation, enablement, import, reload, and runtime class expectations.

## Why the plugin system is structured this way

The current design supports four goals:

- startup plugin selection without importing all plugin modules
- dependency validation before the main window opens
- enabled-only runtime cost
- per-page UI extension without hard-coding every feature into the host shell

## Terminology

### Manifest

A **manifest** is lightweight JSON metadata describing a plugin before code import.

### Entry point

An **entry point** is the Python module declared in the manifest. Importing that module is expected to register the plugin class with the page registry.

### Registered plugin class

A **registered plugin class** is the class the runtime loader expects to find after the entry point is imported.

### Enabled plugin set

The **enabled plugin set** is the startup selection closed over dependencies. Runtime imports are limited to this set.

## Discovery rules

Manifest discovery lives in `framelab/plugins/registry.py`.

### Plugin pages

The system currently supports three page scopes:

- `data`
- `measure`
- `analysis`

These correspond to the page-specific plugin roots under `framelab/plugins/`.

### Manifest file discovery

For a given page, the loader searches recursively under the page directory and accepts:

- `plugin.json`
- `*.plugin.json`

Files under `__pycache__` are ignored.

### Location and declared page must agree

The manifest's `page` value must match the page under which the manifest file was discovered. If a manifest declares `analysis` but is located under `framelab/plugins/data/`, validation fails.

## Manifest validation

Manifest parsing occurs before plugin import. Current validation guarantees:

- the manifest file must decode to a JSON object
- `plugin_id` must be non-empty
- `display_name` must be non-empty
- `entrypoint_module` must be non-empty
- `page` must be valid and consistent with file location
- dependency identifiers must be normalized to unique non-empty tokens
- duplicate `plugin_id` values across manifests are fatal
- dependencies pointing to unknown plugin ids are fatal

This is intentionally strict. Manifest errors are startup errors, not runtime warnings. For field-level reference details, see [Plugin Manifests](../reference/plugin-manifests.md).

## Startup selection and dependency closure

Startup selection lives in `framelab/plugins/selection.py`.

### Persisted selection

The app stores enabled plugin ids in local config. When no saved selection exists, the default is the full discovered manifest set.

### Dependency closure

Selection is always resolved transitively:

- enabling a plugin also enables its dependencies
- disabling a plugin disables dependents that require it

The startup dialog enforces this behavior at the checkbox layer so the final selection is always dependency-consistent.

### Important design point

Dependency closure is based on manifest metadata, not on importing plugin code and introspecting classes.

## Runtime import path

After the startup dialog is accepted, the host window resolves the enabled ids again and loads plugin classes page by page. Runtime loading sequence:

1. group enabled manifests by page
2. clear previously registered classes for the target page
3. import or reload each enabled entrypoint module
4. expect plugin classes to self-register during import
5. verify that every enabled manifest produced a registered class
6. return registered classes in manifest order

If an entrypoint imports successfully but fails to register the expected plugin id, loading fails with a clear error.

## Registration contract

Registration is explicit.

### Generic page registration

`register_page_plugin(plugin_cls, page=...)` in `framelab/plugins/registry.py`:

- normalizes page
- validates non-empty `plugin_id`
- normalizes class-level dependency declaration
- normalizes optional UI capabilities
- stores the class under the page registry

### Analysis helper registration

Analysis plugins currently use `register_analysis_plugin(...)`, which delegates to page registration for the `analysis` page.

## Runtime class contract

The manifest tells the loader **which module to import**. The imported module must then register a class that matches the host's expectations.

## Generic expectations for all page plugins

A plugin class must define:

- `plugin_id`
- page-compatible registration

Optional class-level declarations include:

- `dependencies`
- `ui_capabilities`

Optional runtime menu integration may be provided through host/plugin menu hooks.

## Analysis plugin contract

Analysis plugins currently have the clearest formal interface in `framelab/plugins/analysis/_base.py`. An analysis plugin must implement:

- `create_widget(parent)`
- `on_context_changed(context)`

Analysis plugins may also implement:

- `run_analysis(context)`
- `set_theme(mode)`
- `populate_menu(menu)`

The host owns plugin instantiation, stacked-widget placement, and the explicit Analyze-page run action. The plugin owns the returned widget and its local rendering logic.

### Analysis metric requirements

Analysis plugins are explicit metric consumers. They may declare:

- `required_metric_families`: metric families that must be ready before the host runs the plugin action
- `optional_metric_families`: additional families the plugin can consume when available
- `run_action_label`: the label shown on the host-owned Analyze action button

Metric family names are the string values from `MetricFamily`, such as `static_scan`, `topk`, `roi`, and `roi_topk`. The host displays required-family readiness, shows optional families that are not ready, and may request missing computable required families only when the user clicks the plugin run action. The plugin requirement contract does not modify Data-page scan metric scope.

`on_context_changed(context)` should stay cheap and passive. The context includes `metric_family_statuses`, so plugins can inspect readiness without reaching back into host-owned metric state. Migrated plugins should put table/plot computation behind `run_analysis(context)`. The base implementation delegates `run_analysis` to `on_context_changed` only as a compatibility fallback for older plugins.

## UI capability contract

Plugins can expose lightweight UI-policy hints via `PluginUiCapabilities`. Current fields include:

- `reveal_data_columns`
- `reveal_measure_columns`
- `show_metadata_controls`
- `metadata_group_fields`

These are hints to the host. They are not an alternate plugin-owned UI shell. The host still owns column visibility, metadata controls, and workflow tab structure.

### Important boundary

A plugin may request that certain controls or columns be revealed. It should not directly mutate host tables outside its supported integration surface unless the host explicitly delegates that responsibility.

## Reload behavior

The Analyze page currently exposes a **Reload Plugins** action. Reload behavior is intentionally limited:

- manifests are rediscovered through the registry path
- enabled entrypoint modules are re-imported or reloaded
- registered classes are rebuilt for the page
- plugin widgets are recreated by the host

Reload should be treated as a development convenience, not a guarantee of complete hot-reload safety for arbitrary plugin-local global state. If a plugin caches external module state aggressively or depends on import-time side effects, a full app restart is still the safer path.

## Manifest dependencies versus class dependencies

Both manifests and classes may declare dependencies, but they serve different purposes.

### Manifest dependencies

These are used before runtime import for:

- validation
- startup dependency closure
- enabled-set resolution

### Class dependencies

These are normalized at registration time and can be useful as a runtime declaration, but they do not replace manifest dependencies for startup selection. If the two declarations disagree, the manifest must be treated as the startup source of truth.

## Authoring checklist for new plugins

When adding a plugin:

1. place it under the correct page subtree in `framelab/plugins/`
2. add a manifest file using a unique `plugin_id`
3. ensure `entrypoint_module` imports cleanly
4. register the plugin class during import
5. keep manifest dependencies accurate
6. expose `ui_capabilities` only when the host genuinely needs policy hints
7. verify startup selection, enabled-only load, and reload behavior

## Failure modes worth checking first

If a plugin does not appear or load correctly, check in this order:

1. manifest file discovered under the expected page directory
2. manifest `page` matches location
3. `plugin_id` is unique
4. dependencies reference valid plugin ids
5. entrypoint module path is correct
6. module import actually registers the plugin class
7. the plugin is enabled after dependency closure

## Change guidance

Change these files depending on intent:

- manifest parsing or discovery rules -> `framelab/plugins/registry.py`
- selection persistence or startup dialog behavior -> `framelab/plugins/selection.py`
- analysis plugin base contract -> `framelab/plugins/analysis/_base.py`
- plugin authoring docs for manifest fields -> `docs/reference/plugin-manifests.md`

Do not bury plugin-loader policy inside page-specific UI code. Plugin discovery and import behavior belong in the registry and selection layers.


## Current shipped examples

The shipped plugin set is a useful guide to intended plugin patterns.

### Data-page plugins

- **acquisition_datacard_wizard** — modal authoring workflow around the datacard service layer
- **session_manager** — non-modal dialog for session-level acquisition management; depends on the wizard plugin

### Measure-page plugins

- **background_correction** — focused runtime dialog around host-owned background-reference state

### Analysis-page plugins

- **iris_gain** / **Intensity Trend Explorer** — embedded analysis view with explicit `AnalysisContext` consumption, static-scan requirement, optional Top-K/ROI families, and UI-capability hints
- **event_signature** / **Event Signature** — embedded per-frame signature plot using existing max-pixel, optional ROI Top-K, frame-index, and elapsed-time context fields

These examples show that the plugin system must support both:
- dialog-style runtime tools exposed from the **Plugins** menu
- embedded analysis views hosted inside the workflow shell
