# Datacard System

The datacard system is the app's structured metadata-authoring subsystem. It exists so that acquisition metadata can be declared explicitly, validated, reused, and resolved per frame without forcing every workflow to infer meaning from file names.

This page documents the developer-facing structure of that system: mapping, typed models, validation, serialization, frame targeting, runtime metadata resolution, and the boundary between ordinary canonical defaults and eBUS-managed acquisition-wide values.

## Subsystem responsibilities

The datacard system is responsible for:

- loading editable acquisition field definitions
- providing typed models for defaults and overrides
- validating authoring payloads
- generating and merging override rows
- serializing datacards to JSON payloads
- resolving frame-specific metadata back into dataset rows at runtime
- carrying optional external-source blocks such as `external_sources.ebus`
- layering acquisition metadata on top of inherited session and campaign defaults

It is not responsible for TIFF discovery, image measurement, or analysis plotting.

## Main layers

### 1. Field mapping layer

Location:

```text
framelab/datacard_authoring/mapping.py
framelab/assets/acquisition_field_mapping.default.json
```

This layer defines the authoring-time field catalogue used by the wizard and validation services. Mapping entries define field metadata such as:

- key path
- label and tooltip
- input type
- enum options
- numeric bounds
- editor step hint
- visibility in Defaults and Overrides sections
- optional `ebus_label`
- optional `ebus_managed`

Treat the mapping as the field-definition source of truth for the wizard UI.

### 2. Typed model layer

Location:

```text
framelab/datacard_authoring/models.py
```

This layer defines structured dataclasses for:

- field specs and field mappings
- canonical override rows
- the editable acquisition datacard model
- override-generation plans and merge results

The current `AcquisitionDatacardModel` centers on these top-level sections:

- `identity`
- `paths`
- `intent`
- `defaults`
- `overrides`
- `quality`
- optional `external_sources`

### 3. Service layer

Location:

```text
framelab/datacard_authoring/service.py
```

This layer owns higher-level operations such as:

- loading and saving datacards
- payload sanitization
- typed validation
- override generation
- override append/merge behavior
- model-to-payload serialization

If a change affects datacard semantics, validation, merge behavior, or JSON shape rather than widget presentation, it probably belongs here.

### 4. Wizard UI layer

Location:

```text
framelab/plugins/data/acquisition_datacard_wizard.py
```

The wizard is a plugin-provided UI around the datacard-authoring services. It should remain a consumer of mapping and service layers rather than becoming an alternate validator or serializer.

### 5. Runtime resolution layer

Location:

```text
framelab/metadata.py
framelab/frame_indexing.py
framelab/acquisition_datacard.py
```

This is the stage that turns saved datacards back into per-row metadata during dataset scanning. It is part of the datacard system because authoring semantics are only meaningful if runtime resolution follows the same model.

### 6. Session-management normalization layer

Location:

```text
framelab/session_manager.py
```

This layer is not a second datacard authoring system. It is a structural helper that normalizes acquisition payloads when folders are renamed, reindexed, copied, or pasted across acquisitions.

Treat it as the bridge between folder-level session operations and stable datacard identity/path contracts.

## Metadata hierarchy

The runtime JSON metadata path is broader than one acquisition file.

Current layering order in `metadata.py` is:

1. campaign defaults and instrument defaults from `campaign_datacard.json`
2. session defaults from `session_datacard.json`
3. acquisition defaults from `acquisition_datacard.json`
4. effective acquisition-wide eBUS-backed baseline values for mapped canonical fields when applicable
5. frame-targeted acquisition overrides

This is why the UI label **Acquisition JSON** should be read as "the acquisition-root JSON metadata path" rather than "only one acquisition file".

## Semantic model inside the acquisition datacard

The most important developer concept is the acquisition datacard inheritance model.

### Defaults

`defaults` define the acquisition-level baseline metadata.

### Overrides

`overrides` provide frame-targeted replacement values layered on top of the inherited baseline.

Each serialized override row currently has this shape:

```json
{
  "selector": {"frame_range": [0, 9]},
  "changes": {"camera_settings": {"exposure_us": 5000}},
  "reason": "explicit frame state"
}
```

### Blank values

Blank values in normal wizard usage mean:

- do not set a replacement here
- leave the inherited value untouched

They do **not** mean:

- erase the inherited value
- introduce an explicit `null` clearing semantic

That is a deliberate current design choice.

## eBUS-managed canonical fields

Some canonical fields can be both:

- mapped through `ebus_label`
- marked `ebus_managed`
- backed by one readable acquisition-root `.pvcfg` snapshot

When that is true, the canonical field's acquisition-wide baseline is derived through the eBUS integration path rather than ordinary acquisition defaults alone.

Current consequences:

- the field may appear read-only or editable in the wizard depending on catalog policy
- frame-targeted override generation excludes those fields
- app-side approved acquisition-wide replacement values for those fields live under `external_sources.ebus.overrides`, not inside ordinary frame-targeted override rows

This keeps acquisition-wide eBUS state from competing silently with ordinary frame-targeted override semantics.

## Frame indexing and selector normalization

Frame-targeted overrides are meaningful only if selector semantics match the actual acquisition frame list.

Current responsibilities:

- `frame_indexing.py` resolves frame indices from the configured frames directory
- `acquisition_datacard.py` normalizes override selectors to zero-based indices
- `metadata.py` applies selector rows against the resolved frame index of each file

Maintain selector normalization centrally. Do not duplicate frame-target resolution logic in UI widgets or plugin code.

## Session-manager interaction with datacards

`session_manager.py` performs several datacard-sensitive mutations.

### Rename and reindex

When acquisition folders are renamed or renumbered, the helper rewrites normalized datacard identity and path fields so the payload remains self-consistent with the new folder name.

### Copy and paste

Copy/paste behaves as structured reuse, not as raw file duplication.

Current behavior:

- destination acquisition identity and label are normalized to the target folder
- path strings containing the old acquisition folder name are rewritten
- eBUS attachment bookkeeping is stripped on paste
- app-side eBUS override values remain part of the payload

This behavior should remain explicit because it is easy for maintainers to assume that paste is a raw JSON copy when it is intentionally not.

### eBUS enable toggling

Session Manager persists `external_sources.ebus.enabled` at the acquisition level. That flag affects whether the acquisition is considered eBUS-enabled when later loaded through the normal dataset path.

## Validation and serialization rules

The datacard service layer remains the authoritative validator.

Important current rules:

- unknown mapped fields should not survive as trusted typed entries
- field values must satisfy type and enum expectations from the mapping
- payload structure is normalized before save
- defaults and overrides are serialized back into stable nested JSON objects
- service-layer validation remains authoritative even if the wizard performs pre-validation for better UX

## Developer invariants worth preserving

1. Field mapping remains the field-definition source of truth for the wizard.
2. Acquisition defaults are layered on top of inherited session and campaign defaults.
3. Acquisition overrides replace targeted values on top of inherited defaults.
4. Blank values do not erase inherited values.
5. Service-layer validation remains authoritative even if the UI pre-validates inputs.
6. eBUS-managed canonical fields are acquisition-wide in the current design.
7. Runtime metadata resolution follows the same defaults-plus-overrides semantics that the wizard presents.
8. Session-manager copy/paste remains a normalized payload transfer, not a blind file copy.

## Common maintenance mistakes

Avoid these patterns:

- adding field meaning only in the wizard without updating mapping or validation
- introducing payload keys that typed models cannot represent
- changing runtime merge behavior without updating the authoring docs and tests
- treating `null` as a supported explicit-clear mechanism without designing the full contract
- letting frame-targeted overrides compete silently with eBUS-managed acquisition-wide keys
- duplicating frame-target resolution logic outside `frame_indexing.py` and `metadata.py`
- changing session-manager normalization behavior without verifying acquisition identity/path rewrite rules

## Relationship to other docs

- Use the **User Guide** datacard page for operator workflow and authoring steps.
- Use the **User Guide** Session Manager page for folder-level session operations.
- Use the **Reference** acquisition-mapping page for field-definition schema details.
- Use the **Reference** eBUS catalog page for eBUS parameter policy fields.
- Use this page for semantics, layering, and maintenance boundaries.
