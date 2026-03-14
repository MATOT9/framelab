# Config Files

The app keeps its shareable runtime configuration in the project/app folder under `config/`.

This page documents the file locations, ownership model, and runtime role of each configuration file.

## Main configuration files

| File | Created automatically | Intended editor | Purpose |
| --- | --- | --- | --- |
| `config/config.ini` | Yes | user or app | Persistent scan settings, currently used for skip-pattern storage |
| `config/plugin_selection.json` | Yes | app, optionally user | Persisted startup plugin-selection state |
| `config/acquisition_field_mapping.json` | Yes, if missing | user or app | Editable field-definition mapping used by the Acquisition Datacard Wizard |
| `config/ebus_parameter_catalog.json` | Yes, if missing | user or app | Editable eBUS parameter catalog used by inspect, compare, and eBUS-override eligibility rules |
| `framelab/assets/acquisition_field_mapping.default.json` | No, bundled asset | project source only | Factory-default mapping used as the seed/fallback for the editable runtime mapping |
| `framelab/assets/ebus_parameter_catalog.default.json` | No, bundled asset | project source only | Factory-default eBUS parameter catalog used as the seed/fallback for the editable runtime catalog |
| `framelab/assets/help/` | No, bundled build output | project source/build process | Offline documentation bundle opened from the Help menu |

## File details

### `config/config.ini`

This file stores persistent scan settings in INI format.

Current use:

- skip-pattern persistence for dataset scanning

Important notes:

- the file is created when settings are first saved
- missing files are acceptable; defaults are used until saved
- legacy config files may be migrated into the local `config/` directory when the current file is missing
- editing while the app is closed is acceptable if valid INI syntax is preserved

### `config/plugin_selection.json`

This file stores the enabled plugin ids chosen in the startup selector.

Payload characteristics:

- JSON object
- includes a schema-version field
- stores `enabled_plugin_ids` as a list of plugin identifiers

Important notes:

- the file is created after the startup selector is accepted
- if the file is missing or invalid, the app falls back to enabling all discovered plugins
- dependency closure is resolved at load time, so the effective enabled set may be larger than the explicitly stored list

### `config/acquisition_field_mapping.json`

This is the editable runtime mapping used by the Acquisition Datacard Wizard.

It defines field metadata such as:

- dot-path keys
- labels
- groups
- value types
- bounds
- enum options
- visibility in defaults and override editors
- optional eBUS binding through `ebus_label`
- optional acquisition-wide eBUS control through `ebus_managed`

Important notes:

- if the file is missing, the app seeds it from the bundled default mapping
- if the file exists but contains no valid fields, the app falls back to built-in defaults
- missing metadata keys required by newer builds may be backfilled into the editable mapping file
- this file is intended to be user-editable, but changes should be made while the app is closed unless you are explicitly reloading mapping state from the wizard

### `config/ebus_parameter_catalog.json`

This is the editable runtime catalog used by the eBUS config tools.

It defines eBUS parameter metadata such as:

- qualified eBUS keys
- labels and descriptions
- relevance classification
- compare visibility
- whether a parameter is app-overridable
- type hints used when an override is permitted

Important notes:

- if the file is missing, the app seeds it from the bundled default catalog
- this file classifies eBUS keys; it does **not** define the canonical app metadata schema
- canonical mapping is derived at runtime from `acquisition_field_mapping.json` through each field's `ebus_label`
- uncatalogued keys may still parse and compare, but they lose catalog-backed labeling and policy metadata

### Bundled default JSON assets

These files are shipped with the app and are used to seed missing editable runtime copies:

- `framelab/assets/acquisition_field_mapping.default.json`
- `framelab/assets/ebus_parameter_catalog.default.json`

Use them as factory defaults and packaging assets, not as the normal runtime editing targets.

## Dataset-side metadata companion files

Some metadata files live next to datasets rather than under the global `config/` directory.

### `campaign_datacard.json`

Campaign-level metadata file.

Current runtime role:

- provides `campaign_defaults`
- may also provide `instrument_defaults`
- acts as the broadest JSON metadata layer in hierarchical resolution

### `session_datacard.json`

Session-level metadata file.

Current runtime role:

- provides `session_defaults`
- can redefine the acquisitions root through `paths.acquisitions_root_rel`
- is used by Session Manager to locate and manage acquisitions under one session

### `acquisition_datacard.json`

Acquisition-level canonical metadata file.

Current runtime role:

- provides acquisition `defaults`
- provides frame-targeted `overrides`
- can carry `external_sources.ebus` for acquisition-local eBUS state and approved app-side overrides

The most behaviorally important eBUS sub-block is currently:

```text
external_sources.ebus.overrides
```

Those overrides are the app-side acquisition-wide replacement layer used by effective eBUS resolution for eligible canonical fields.

### Acquisition-local root-level `.pvcfg`

A dataset folder is treated as carrying a discoverable eBUS snapshot only when it contains exactly one readable root-level `.pvcfg` file.

Important notes:

- the app reads this file but does not edit it
- automatic discovery is based on root-level uniqueness, not on a special filename requirement
- if several root-level `.pvcfg` files exist, the app will not guess which one is authoritative
- app-side eBUS override values live in the datacard JSON, not in the raw `.pvcfg` file

## Migration and fallback behavior

The app uses local `config/` paths as the primary runtime location.

When a current file is missing, the app may attempt limited migration from legacy locations before falling back to defaults. This is primarily intended to preserve older skip settings, plugin-selection state, and mapping files after the configuration model was moved into the app/project folder.

## Manual-edit guidance

General guidance:

- safe to edit while the app is closed: `config.ini`, `plugin_selection.json`, `acquisition_field_mapping.json`, `ebus_parameter_catalog.json`
- safe to edit while the app is closed when you intentionally manage dataset metadata: `campaign_datacard.json`, `session_datacard.json`, `acquisition_datacard.json`
- not intended for routine runtime editing: bundled asset files under `framelab/assets/`
- if a file becomes invalid, the app will usually fall back to defaults rather than partially trusting malformed content

When hand-editing JSON files, preserve valid UTF-8 JSON object structure and do not change key types casually.
