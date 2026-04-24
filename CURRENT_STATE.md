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
- Dataset-wide metric work is coordinated through worker objects and applied back on the UI thread.
- Analyze workflows consume an `AnalysisContext` built from dataset metadata, metric state, normalization state, and background state.
- Analysis plugins should consume that context rather than reaching back into raw host state.

## Docs And Packaging

- Editable docs live under `docs/`.
- Bundled offline help lives under `framelab/assets/help/` and is generated through `scripts/docs/build.py`.
- `scripts/docs/check.py` performs source-file checks and a strict docs build.
- `tools/build_nuitka_app.py` is the repo-owned standalone packaging helper.
- The optional native backend is built from `native/` into `framelab/native/`.
