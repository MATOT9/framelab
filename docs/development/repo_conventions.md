# Repository Conventions

Use this page for development workflow conventions that are broader than one subsystem but narrower than the full architecture guide.

## Canonical Boundaries

- Root context docs answer "where do I start?" and "what is current?"
- `docs/developer-guide/*` answers "how does this subsystem work?"
- `docs/reference/*` answers "what exact file or schema contract applies?"
- Local `AGENTS.md` files answer "what editing rules apply in this directory?"

## State Ownership

- Shared workflow, dataset, metric, and analysis state belongs on controllers or the host window, not inside plugin-local widgets.
- Worker objects own temporary job-local computation only.
- Plugins own plugin-local UI and interpretation state, not hidden alternate sources of workflow truth.
- Global preferences stay in `config/preferences.ini`.
- Reopenable session state stays in explicit `.framelab` workspace files.

## UI Organization

- `FrameLabWindow` is assembled from mixins under `framelab/main_window/`.
- Add chrome-level actions to `chrome.py`.
- Add Data-page widget behavior to `data_page.py`.
- Add scan/cache behavior to `dataset_loading.py`.
- Add Measure-page widgets to `inspect_page.py`.
- Add metric worker orchestration to `metrics_runtime.py`.
- Add analysis-plugin hosting behavior to `analysis.py`.

## Plugin Organization

- A plugin must have a manifest and an entrypoint module that registers a class during import.
- Manifest discovery should stay import-free.
- Optional runtime menu actions belong behind plugin menu hooks.
- Built-in host-owned tools, such as eBUS Config Tools, should not be forced into the plugin system just to appear in menus.

## Documentation Hygiene

- Keep one canonical home per topic.
- Link instead of restating long explanations.
- Separate current behavior from known issues and future work.
- Mark uncertain claims with phrases such as "appears to" or "not runtime-verified".
- Keep generated help synchronized through scripts, not manual edits.
