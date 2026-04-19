# AGENTS

These rules apply inside `framelab/main_window/`.

## Mixin Ownership

- `chrome.py`: menus, toolbar, status bar, help, preferences, docks, theme, and app-wide chrome.
- `data_page.py`: Data-tab widgets and page-local interactions.
- `dataset_loading.py`: folder scan, image discovery, image loading, cache behavior, and background-aware image access.
- `inspect_page.py`: Measure-tab controls, preview, histogram, ROI, and background UI.
- `metrics_runtime.py`: metric worker lifecycle, ROI apply jobs, and worker result application.
- `analysis.py`: analysis plugin hosting, selection UI, context delivery, and analysis page visibility.
- `window_actions.py`: menu or shell actions that do not belong fully to one page mixin.

## UI State

- Treat the host window as the shared-state owner.
- Do not let page widgets become alternate sources of workflow, dataset, or metric truth.
- Persist session-like UI state only through workspace document capture/restore.
- Keep preferences as global defaults, not as last-session restore.

## Threading

- Do not mutate widgets or shared host state from workers.
- Snapshot inputs before long-running jobs.
- Validate job identity before applying worker results.

## Validation

- Use targeted UI tests for changed mixins.
- Prefer controller/state tests when behavior does not require real widget interaction.
