# AGENTS

These rules apply inside `framelab/plugins/`.

## Plugin Contract

- Manifest discovery must not import plugin implementation modules.
- Every plugin needs a unique manifest `plugin_id`.
- The manifest `page` must match the directory under `framelab/plugins/`.
- The entrypoint module must register the expected plugin class during import.
- Manifest dependencies are the startup source of truth.

## Runtime Boundaries

- Plugins may contribute page-local widgets, analysis views, or plugin-menu actions.
- Plugins should consume host-provided context and hooks.
- Plugins should not own workflow tree, dataset rows, metric arrays, or app-wide UI policy.
- eBUS Config Tools are built-in host-owned tools and should not be restored as a data-page plugin.

## Validation

- Plugin discovery or selection changes should include `tests/test_plugin_registry.py`.
- Startup-selection behavior should include `tests/test_app_startup.py` when applicable.
- Plugin UI changes should include the closest page or dialog tests.
