# Config Files

The app keeps its shareable runtime configuration in the project/app folder under `config/`. This page documents the file locations, ownership model, and runtime role of each configuration file.

FrameLab also supports user-created workspace documents with the `.framelab` extension. Those files are not part of the automatic `config/` directory, but they matter here because they now own the reopenable session state: workflow scope, page selection, panel state, splitter positions, and skip rules all come back only from the workspace file you explicitly open.

## Main configuration files

| File | Created automatically | Intended editor | Purpose |
| --- | --- | --- | --- |
| `config/preferences.ini` | Yes | app | Persistent application preferences such as theme, density, preview defaults, and runtime toggles |
| `config/plugin_selection.json` | Yes | app, optionally user | Persisted startup plugin-selection state |
| `config/acquisition_field_mapping.json` | Yes, if missing | user or app | Editable field-definition mapping used by the Acquisition Datacard Wizard |
| `config/ebus_parameter_catalog.json` | Yes, if missing | user or app | Editable eBUS parameter catalog used by inspect, compare, and eBUS-override eligibility rules |
| `config/workflow_metadata_governance.json` | No, created on demand | user or app | Profile-level metadata governance overrides and promoted ad-hoc field definitions |
| `framelab/assets/acquisition_field_mapping.default.json` | No, bundled asset | project source only | Factory-default mapping used as the seed/fallback for the editable runtime mapping |
| `framelab/assets/ebus_parameter_catalog.default.json` | No, bundled asset | project source only | Factory-default eBUS parameter catalog used as the seed/fallback for the editable runtime catalog |
| `framelab/assets/help/` | No, bundled build output | project source/build process | Offline documentation bundle opened from the Help menu |

## File details

### `config/plugin_selection.json`

This file stores the enabled plugin ids chosen in the startup selector. Payload characteristics:

- JSON object
- includes a schema-version field
- stores `enabled_plugin_ids` as a list of plugin identifiers

Important notes:

- the file is created after the startup selector is accepted
- if the file is missing or invalid, the app falls back to enabling all discovered plugins
- dependency closure is resolved at load time, so the effective enabled set may be larger than the explicitly stored list

### `config/preferences.ini`

This file stores persistent application preferences in INI format. Current use:

- theme and density preferences
- preview defaults
- panel/tab restore preferences that affect workspace restore behavior
- collapse defaults for summary strips and advanced controls
- scan-worker and RAW runtime preferences

Important notes:

- the file is created when preferences are first saved
- this file does not restore the last workflow session on app launch
- it does remember recent `.framelab` workspace-document paths used by File -> Open Workspace File and the Select Workflow dialog
- limited legacy migration may seed preferences from an older `ui_state.ini` when `preferences.ini` is missing
- deleting it is safe; the app will recreate it from defaults

### `*.framelab`

Workspace document created explicitly by the user from the File menu. Current runtime role:

- restores workflow context and active node
- restores the scanned dataset root and selected image
- restores current skip rules for dataset intake
- restores the Data-tab scan metric preset and Custom family selection
- restores Measure-page state such as threshold, average mode, ROI, and background source
- restores page/plugin selection, preview visibility, dock disclosure, and splitter positions relevant to the current session

Important notes:

- this is a local reopen file, not a portable dataset bundle
- paths are stored as filesystem paths and are expected to be valid on the same machine
- the file is JSON-backed even though it uses the custom `.framelab` extension
- global preferences such as theme and density still live in `config/preferences.ini`

### `config/acquisition_field_mapping.json`

This is the editable runtime mapping used by the Acquisition Datacard Wizard. It defines field metadata such as:

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

This is the editable runtime catalog used by the eBUS config tools. It defines eBUS parameter metadata such as:

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

### `config/workflow_metadata_governance.json`

This file stores optional profile-level governance overrides for workflow metadata. Typical use:

- promote an ad-hoc metadata field into a profile-defined field
- tighten or relax ad-hoc field/group policy per workflow profile
- override labels, groups, type hints, or enum options for workflow metadata fields

Payload characteristics:

- top-level `profiles` object keyed by workflow profile id
- optional `allow_ad_hoc_fields` and `allow_ad_hoc_groups` flags per profile
- `fields` list of promoted or overridden field definitions

Important notes:

- the file is created only when needed, for example when a field is promoted from the Metadata Inspector
- missing files are acceptable; built-in workflow profile governance remains authoritative until an override exists
- this file extends workflow metadata governance and does not replace acquisition datacard schema mapping

### Bundled default JSON assets

These files are shipped with the app and are used to seed missing editable runtime copies:

- `framelab/assets/acquisition_field_mapping.default.json`
- `framelab/assets/ebus_parameter_catalog.default.json`

Use them as factory defaults and packaging assets, not as the normal runtime editing targets.

## Dataset-side metadata companion files

Some metadata files live next to datasets rather than under the global `config/` directory.

### `.framelab/nodecard.json`

Generic workflow-node metadata file. Current runtime role:

- stores local metadata for workflow nodes such as workspace, trial, camera, campaign, or session levels
- participates in ancestry-based metadata inheritance
- is editable from the Workflow Manager / Metadata Inspector surfaces

Important notes:

- this is the primary higher-level metadata format for the workflow-driven shell
- it is separate from acquisition-specific datacards on purpose
- nodecards can coexist with older campaign/session datacards while compatibility bridges remain in place

### `campaign_datacard.json`

Campaign-level metadata file. Current runtime role:

- provides `campaign_defaults`
- may also provide `instrument_defaults`
- acts as the broadest JSON metadata layer in hierarchical resolution

Important note:

- this is now a compatibility layer alongside `.framelab/nodecard.json`, not the preferred long-term higher-level metadata authoring target

### `session_datacard.json`

Session-level metadata file. Current runtime role:

- provides `session_defaults`
- can redefine the acquisitions root through `paths.acquisitions_root_rel`
- is used by Session Manager to locate and manage acquisitions under one session

Important note:

- session datacards remain important for acquisition/session tooling, but generic session metadata is moving toward `.framelab/nodecard.json`

### `acquisition_datacard.json`

Acquisition-level canonical metadata file. Current runtime role:

- provides acquisition `defaults`
- provides frame-targeted `overrides`
- can carry `external_sources.ebus` for acquisition-local eBUS state and approved app-side overrides

The most behaviorally important eBUS sub-block is currently:

```text
external_sources.ebus.overrides
```

Those overrides are the app-side acquisition-wide replacement layer used by effective eBUS resolution for eligible canonical fields.

### Acquisition-local root-level `.pvcfg`

A dataset folder is treated as carrying a discoverable eBUS snapshot only when it contains exactly one readable root-level `.pvcfg` file. Important notes:

- the app reads this file but does not edit it
- automatic discovery is based on root-level uniqueness, not on a special filename requirement
- if several root-level `.pvcfg` files exist, the app will not guess which one is authoritative
- app-side eBUS override values live in the datacard JSON, not in the raw `.pvcfg` file

## Migration and fallback behavior

The app uses local `config/` paths as the primary runtime location. When a current file is missing, the app may attempt limited migration from legacy locations before falling back to defaults. This is primarily intended to preserve older UI-state and skip settings, plugin-selection state, and mapping files after the configuration model was moved into the app/project folder.

## Manual-edit guidance

General guidance:

- safe to edit while the app is closed: `preferences.ini`, `plugin_selection.json`, `acquisition_field_mapping.json`, `ebus_parameter_catalog.json`, `workflow_metadata_governance.json`
- safe to edit while the app is closed when you intentionally manage dataset metadata: `.framelab/nodecard.json`, `campaign_datacard.json`, `session_datacard.json`, `acquisition_datacard.json`
- not intended for routine runtime editing: bundled asset files under `framelab/assets/`
- if a file becomes invalid, the app will usually fall back to defaults rather than partially trusting malformed content

When hand-editing JSON files, preserve valid UTF-8 JSON object structure and do not change key types casually.
