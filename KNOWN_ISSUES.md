# Known Issues

This file is the compact registry of known bugs, fragile zones, and incomplete areas. Keep it grounded in repo evidence such as `TODO`, tests, docs, or inspected code.

## Active Bugs And Fragile Areas

- The pytest suite needs refactoring to avoid stalls and very long runners.
- The Trials workflow profile folder structure and "create new" behavior are not yet reliable.
- The app can lag when changing workflow tabs.
- Some badges or chips may disappear after changing active workflow scope.
- The right-click menu is unavailable when there is no active preview.
- The standalone build path has had permission errors when deleting `.pyd` files.
- Workspace/preferences persistence was recently reshaped; keep verifying that session-like UI state is restored only from `.framelab` files while preferences remain in `config/preferences.ini`.

## Design Debts

- Acquisition datacard handling and generic workflow-node metadata should eventually converge into a clearer single mechanism.
- Session Manager remains a legacy plugin for datacard copy/paste and acquisition-local eBUS toggles that are not fully workflow-native yet.
- The Trials profile is present but should not be treated as production-equivalent to Calibration.
- Some UI state names still use legacy `ui_state` terminology even though persisted scope is now preferences-only.

## Feature Gaps

- ROI sum is not yet a first-class metric.
- Computer last boot time calculation is planned but not implemented.
- Setup builder work is planned, including preregistered cameras, lenses, filters, and a visual setup authoring UI.
- Dead pixel detection is planned.
- Spectral responsivity assessment is planned.
- RGB and Bayer pixel-format support needs further work.

## Performance Backlog

- RAW loader mmap support needs completion or verification across supported paths.
- Native backend SIMD support is planned.
- Native backend LTO support is planned.
- Native backend PGO support is planned.
- UI tab-switch performance needs profiling before broad refactors.

## Documentation Risks

- Generated help can drift if `docs/` changes are not rebuilt into `framelab/assets/help/`.
- New docs pages require `mkdocs.yml` and `scripts/docs/check.py` updates when they become part of the documented source set.
- Root context docs can decay unless behavior changes also update `CURRENT_STATE.md`, `KNOWN_ISSUES.md`, and the relevant canonical docs.
