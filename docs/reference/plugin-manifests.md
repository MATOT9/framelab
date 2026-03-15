# Plugin Manifests

Plugin manifests allow the app to discover plugin metadata before importing plugin code. This supports three important runtime behaviors:

- startup selection without importing every plugin implementation
- dependency validation before launch
- enabled-only runtime imports after the user confirms the selection

## Discovery rules

Manifest discovery is page-scoped. The app searches under the plugin tree for files named:

- `plugin.json`
- `*.plugin.json`

Discovery is performed recursively under each workflow-page package:

- `framelab/plugins/data/`
- `framelab/plugins/measure/`
- `framelab/plugins/analysis/`

Files under `__pycache__` are ignored.

## Manifest fields

| Field | Required | Type | Meaning |
| --- | --- | --- | --- |
| `plugin_id` | Yes | string | Stable plugin identifier used for selection, registration, and dependency resolution |
| `display_name` | Yes | string | User-facing name shown in the startup selector and other UI surfaces |
| `page` | Yes | string | Workflow page target: `data`, `measure`, or `analysis` |
| `entrypoint_module` | Yes | string | Python module imported when the plugin is enabled |
| `dependencies` | Yes | array of strings | Other plugin ids that must be enabled before this plugin can be considered complete |
| `description` | No | string | Concise user-facing description shown under the plugin checkbox |

## Example

```json
{
  "plugin_id": "acquisition_datacard_wizard",
  "display_name": "Acquisition Datacard Wizard",
  "page": "data",
  "entrypoint_module": "framelab.plugins.data.acquisition_datacard_wizard",
  "dependencies": [],
  "description": "Create and edit acquisition datacards for the selected folder."
}
```

## Validation rules

The manifest layer is validated before runtime plugin imports. The current rules are:

- `plugin_id` must be present and non-empty
- `display_name` must be present and non-empty
- `page` must resolve to one of `data`, `measure`, or `analysis`
- `entrypoint_module` must be present and non-empty
- `dependencies` are normalized into a stable tuple of non-empty string ids
- `plugin_id` values must be unique across all discovered manifests
- every dependency must reference a known `plugin_id`
- the manifest `page` must agree with the page directory in which the file was discovered

If any of these checks fail, plugin discovery fails rather than partially loading a broken manifest set.

## Runtime implication of dependencies

Dependencies affect both persistence and launch-time resolution. Important consequences:

- the saved plugin-selection file may list only the directly chosen plugin ids
- the effective enabled set is closed over dependencies at load time
- disabling a plugin in the startup selector can also disable dependent plugins

## Registration contract

A valid manifest is necessary but not sufficient. After the enabled manifest set is imported:

- the plugin entrypoint module must import successfully
- the plugin implementation must register itself with the host registry
- the registered `plugin_id` must match the manifest identity expected by the loader

If a manifest imports successfully but no matching plugin registers, loading fails.

## Authoring guidance

When adding a new plugin:

1. place the manifest under the correct page subtree
2. keep `plugin_id` stable once published
3. treat `display_name` as user-facing copy, not a stable identifier
4. keep `description` short and operational
5. use dependencies only when the plugin cannot function correctly without another plugin being enabled
