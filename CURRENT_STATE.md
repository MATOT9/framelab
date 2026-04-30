# Current State

This is a compact snapshot of the current implementation. Prefer canonical docs for detailed contracts, and update this file when shipped behavior materially changes.

## Product Shape

- FrameLab is a PySide6 desktop workbench for acquisition review and measurement.
- The primary documented workflow profile is `calibration`: `workspace -> camera -> campaign -> session -> acquisition`.
- The `trials` profile exists but remains experimental.
- The main shell is organized as Data, Measure, and conditional Analyze workflows with a Workflow Explorer dock and Metadata Inspector dock.

## Startup And Plugins

- Startup creates the Qt application, discovers plugin manifests, loads saved plugin selection, shows the startup selector, and then opens the main window.
- Manifest discovery happens before plugin implementation import.
- Current plugin pages are `data`, `measure`, and `analysis`.
- Current data plugins include Acquisition Datacard Wizard and Session Manager (Legacy).
- Current measure plugin coverage includes Background Correction.
- Current analysis plugin coverage includes Intensity Trend Explorer and Event Signature.
- eBUS Config Tools are built into the host app under `Edit -> Advanced -> eBUS Config Tools`; they no longer participate as a selectable plugin.
- Stale `ebus_config_tools` ids in plugin selection data are tolerated by resolving only ids that still have manifests.

## Workspace And Preferences

- Persistent UI preferences live in `config/preferences.ini`.
- Reopenable session state is saved to explicit `.framelab` workspace files.
- Workspace documents currently restore workflow context, dataset scope, selected image, skip rules, Data scan metric setup, Measure settings, ROI, background settings, active page/plugin, preview visibility, panel state, and splitter sizes.
- The Select Workflow dialog can also open a saved `.framelab` workspace document, and recent workspace-document paths are remembered globally for quick reopen.
- Unless a `.framelab` file is opened, the app should behave like a fresh session except for persistent preferences and recent workspace-document history.
- Legacy `ui_state.ini` is retained only as a limited migration source for preferences when `preferences.ini` is missing.

## Workflow And Metadata

- Workflow loading is profile-driven, not pure folder-depth loading.
- Calibration sessions may be discovered directly under a campaign or under `01_sessions/` / `sessions/`.
- Acquisitions are tolerated by workflow loading if they have datacards even when naming is less strict.
- Structure-authoring tools remain stricter and prefer `acq-####` or `acq-####__label`.
- Metadata resolution combines path-derived data, filename UTC timestamps, `.framelab/nodecard.json`, campaign/session/acquisition datacards, effective eBUS-managed acquisition fields, and frame-targeted overrides.

## eBUS

- eBUS parsing, catalog policy, effective-config overlay, sidecar discovery, compare logic, and dialogs live under `framelab/ebus/`.
- Raw `.pvcfg` files are treated as immutable source artifacts.
- Acquisition-root eBUS discovery requires exactly one readable root-level `.pvcfg`.
- Effective eBUS values may overlay acquisition datacard `external_sources.ebus.overrides` for catalog-overridable keys.
- The eBUS dialogs can optionally hand off to the datacard wizard when that plugin is enabled.

## Measurement And Analysis

- Measure workflows cover thresholding, Top-K mean/std/SEM, ROI max/sum/mean/std/SEM, ROI + Top-K mean/std/SEM, normalization, background correction, exposure-normalized quantities such as `DN/ms`, and elapsed-time display for timestamped acquisition filenames.
- Dataset scans populate the loaded paths, resolved metadata, elapsed-time metadata, and static quick-look metrics such as max pixel and minimum non-zero by default. The Data tab exposes scan-time metric presets; fresh sessions use the Minimal preset, while explicit non-minimal presets can request threshold, Top-K, or ROI-family work after scan without involving plugins.
- Metric readiness is tracked by explicit families such as static scan, saturation, low signal, Top-K, ROI, ROI Top-K, and background-applied state. Measure controls keep pending UI values separate from applied compute inputs; threshold, low-signal, and Top-K changes do not recompute until their Apply actions run.
- Dataset-wide metric work is coordinated through targeted worker requests and applied back on the UI thread. Threshold apply requests only saturation counts, Top-K apply requests only Top-K arrays, ROI apply requests only ROI or ROI + Top-K arrays, and background changes recompute only background-sensitive families already in use.
- Nontrivial refresh and compute paths now carry explicit internal refresh reasons such as scan load, apply threshold, apply Top-K, apply ROI, plugin run, background change, view rebind, tab switch, workflow remap, workflow scope change, metadata change, and workspace restore. View-only reasons are rejected if they reach compute-only metric paths.
- Runtime jobs such as dataset load, metric compute, ROI apply, and plugin compute are tracked through explicit task state and surfaced compactly in the status bar.
- Main workflow tab changes are view transitions. They update layout, hints, column visibility, and visible analysis delivery when needed, but they do not start scans, rebuild cached metadata-table content, run metric recompute, flush caches, or invalidate analysis by themselves.
- Workflow scope selection is cheap when the selected scope is already active. Workflow structure operations such as empty-scope creation, rename, and renumber refresh the tree and remap already loaded paths when possible instead of entering scan/load paths.
- DEBUG logging under `framelab.refresh` records lightweight timing and transition diagnostics for metadata refreshes, analysis context rebuilds, plugin runs, workflow remaps, tab-settle paths, and metric-family transitions to computing or stale.
- Analyze workflows consume an `AnalysisContext` built from dataset metadata, metric state, metric-family readiness, normalization state, and background state. Contexts carry a data signature for scientific inputs so presentation-only plugin choices do not force context rebuilds.
- Analysis plugin context refresh is passive: enabled plugins receive cheap context updates, declare required/optional metric families and a run label, and compute through an explicit Analyze-page action. The host shows missing requirements, may explicitly request missing metric families from that action without adding plugin-driven work to Data-page scope scans, and can run plugin-declared preparation on a lightweight worker.
- Event Signature caches plugin-ready per-frame records by the consumed data signature. Changing X/Y presentation choices reuses those records and rebuilds only the table/plot projection.

## Docs And Packaging

- Editable docs live under `docs/`.
- Bundled offline help lives under `framelab/assets/help/` and is generated through `scripts/docs/build.py`.
- `scripts/docs/check.py` performs source-file checks and a strict docs build.
- `tools/build_nuitka_app.py` is the repo-owned standalone packaging helper.
- The optional native backend is built from `native/` into `framelab/native/`.
