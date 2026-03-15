# Datacard Wizard

Use the **Acquisition Datacard Wizard** to create, edit, validate, and save acquisition metadata for the currently selected dataset. This page documents the datacard model actually consumed by the app, not only the button sequence.

## Purpose

Use a datacard when folder names and file names are not sufficient to describe the acquisition reliably. The wizard edits the **acquisition-level** datacard. At runtime, those acquisition-level values can still sit on top of inherited session and campaign defaults when those broader datacards exist. Typical reasons include:

- acquisition-wide defaults should be recorded explicitly
- exposure, iris position, or other mapped values vary by frame index
- the authoritative metadata should be authored instead of inferred from naming conventions
- selected canonical fields need approved app-side overrides over an eBUS snapshot baseline

## Datacard model

The supported semantic model is inheritance plus replacement.

- **Defaults** define inherited baseline metadata.
- **Overrides** replace only the fields explicitly provided for targeted frames or frame ranges.
- A blank field means **do not set a value here**.
- A blank field does **not** erase an inherited value.

In practice:

- keep stable acquisition-wide settings in **Defaults**
- use **Frame Mapping** only for values that actually vary over time

## Actual payload shape

The persisted datacard is not a flat `defaults + overrides` stub. The current model contains these top-level sections:

- `schema_version`
- `entity`
- `identity`
- `paths`
- `intent`
- `defaults`
- `overrides`
- `quality`
- optional `external_sources`

For mapped acquisition values, `defaults` and `overrides[].changes` use the canonical dot-path structure defined by the acquisition field mapping.

## Wizard tabs

### 1. Target

Use this tab to load the acquisition folder, inspect frame-index discovery, and choose the frame-index base used for authored override rows. Use it to:

- choose the acquisition root
- load an existing datacard or initialize a new one
- inspect discovered frame-index mode
- decide whether new rows should append to or replace existing override rows

Important details:

- `paths.frames_dir` defaults to `frames`
- frame-index discovery is based on the configured frames directory
- the wizard can author 0-based or 1-based ranges, but runtime metadata resolution normalizes authored selectors back to the resolved acquisition frame model
- override row ranges are inclusive at both ends

### 2. Identity / Paths / Intent

Use this tab for acquisition identity and acquisition-wide descriptive context. Typical content includes:

- camera, campaign, session, or acquisition identifiers
- frames-directory name
- capture type, subtype, scene, and tags

This tab defines acquisition context, not frame-varying sweep values.

### 3. Defaults

Use this tab to define acquisition-level baseline values. These defaults are layered on top of any inherited session or campaign defaults. Frame overrides later replace only the keys they explicitly provide. Recommended content:

- fixed exposure, if the whole acquisition used one exposure
- fixed iris position, if the whole acquisition used one setting
- stable instrument or configuration fields that should appear on every frame record

### 4. Frame Mapping

Use this tab when metadata varies with frame index. The current wizard supports three authoring modes:

- **Defaults only (unknown duration)**
- **Generate rows**
- **Manual rows**

The generator can build rows from:

- an explicit values list
- a numeric sweep
- a constant value over a frame range

Use this tab for:

- exposure sweeps
- iris sweeps
- blockwise configuration changes
- isolated exceptions inside a mostly uniform acquisition

Only specify the fields that truly change. Leave all other fields blank so they continue to inherit from Defaults.

### 5. Review and Save

Use this tab to validate the authored datacard, inspect the final payload, and save it to disk. Before saving, confirm:

- the intended dataset folder is selected
- defaults reflect the acquisition-wide baseline
- overrides target the intended frames or ranges
- no field was entered in overrides unless it is meant to replace the baseline

## Blank values and inheritance

This is the most important semantic rule in the current app. A blank field means:

- do not set a new value here
- keep the inherited baseline if one exists

It does not mean:

- clear the inherited value
- write an explicit `null` to erase the baseline

Normal wizard usage does not implement an inheritance-plus-clearing model.

## Frame targeting semantics

Override rows are stored with:

- `selector.frame_range`
- inclusive start and end indices
- nested `changes`
- optional `reason`

Operational rules worth remembering:

- later rows win when overlapping rows write the same key
- only fields actually present in `changes` are replaced
- unsupported or unmapped keys are not the normal authoring path and are filtered by the mapping-backed model
- frame ranges are structurally valid only when start and end are integers

When authoring frame-based sweeps:

- keep the frame logic simple and contiguous where possible
- avoid overlapping mappings unless you intentionally want later rows to take precedence
- verify the intended coverage before saving

## eBUS-managed canonical fields

When an acquisition has a readable root-level eBUS snapshot, some canonical fields can become **eBUS-managed** through the acquisition field mapping and eBUS catalog. Current behavior:

- the field stays visible in the wizard
- non-overridable fields become read-only in **Defaults**
- fields whose catalog entry is marked `overridable` stay editable in **Defaults**
- those editable acquisition-wide replacements are stored under `external_sources.ebus.overrides`, not under ordinary canonical defaults
- eBUS-managed acquisition-wide fields are excluded from frame-targeted override generation

This is intentional. The current design supports one acquisition-wide source of truth per eBUS-managed canonical field, not one baseline in eBUS plus competing acquisition-wide and frame-targeted paths.

## Minimal example

Use this structure when one acquisition-wide baseline is sufficient and no frame-specific sweep is needed.

```json
{
  "schema_version": "1.0",
  "entity": "acquisition",
  "identity": {
    "acquisition_id": "exp_2026_03_08_camA"
  },
  "paths": {
    "frames_dir": "frames"
  },
  "intent": {
    "capture_type": "calibration",
    "subtype": "",
    "scene": "",
    "tags": []
  },
  "defaults": {
    "camera_settings": {
      "exposure_us": 10000
    },
    "instrument": {
      "optics": {
        "iris": {
          "position": 12
        }
      }
    },
    "acquisition_settings": {}
  },
  "overrides": [],
  "quality": {
    "anomalies": [],
    "dropped_frames": [],
    "saturation_expected": false
  }
}
```

Interpretation:

- all frames inherit `camera_settings.exposure_us = 10000`
- all frames inherit `instrument.optics.iris.position = 12`
- no frame-specific replacement is defined

## Sweep example

Use this structure when the acquisition has one baseline plus frame-based exposure changes.

```json
{
  "schema_version": "1.0",
  "entity": "acquisition",
  "identity": {
    "acquisition_id": "exp_2026_03_08_exposure_sweep"
  },
  "paths": {
    "frames_dir": "frames"
  },
  "intent": {
    "capture_type": "calibration",
    "subtype": "exposure_sweep",
    "scene": "fixed_target",
    "tags": []
  },
  "defaults": {
    "camera_settings": {},
    "instrument": {
      "optics": {
        "iris": {
          "position": 18
        }
      }
    },
    "acquisition_settings": {}
  },
  "overrides": [
    {
      "selector": {
        "frame_range": [0, 9]
      },
      "changes": {
        "camera_settings": {
          "exposure_us": 2000
        }
      },
      "reason": "explicit frame state"
    },
    {
      "selector": {
        "frame_range": [10, 19]
      },
      "changes": {
        "camera_settings": {
          "exposure_us": 5000
        }
      },
      "reason": "explicit frame state"
    },
    {
      "selector": {
        "frame_range": [20, 29]
      },
      "changes": {
        "camera_settings": {
          "exposure_us": 10000
        }
      },
      "reason": "explicit frame state"
    }
  ],
  "quality": {
    "anomalies": [],
    "dropped_frames": [],
    "saturation_expected": false
  }
}
```

Interpretation:

- all frames inherit `instrument.optics.iris.position = 18`
- exposure is replaced by frame block
- no other inherited values are disturbed

## eBUS override example

When a canonical field is both `ebus_managed` and catalog-`overridable`, the wizard stores the app-side acquisition-wide replacement under:

```json
{
  "external_sources": {
    "ebus": {
      "overrides": {
        "device.Iris": 14
      }
    }
  }
}
```

That override is applied on top of the raw eBUS snapshot baseline and then mapped back into the canonical field.

## Validation guidance

Validate before saving whenever:

- the target acquisition changed
- field mappings were changed
- frame ranges were edited
- defaults were revised after overrides were already authored
- an eBUS-managed field was intentionally overridden

Validation is meant to confirm at least:

- top-level structure is valid
- field names are known to the mapping when mapping-backed sections are used
- typed values are compatible with the field definition
- frame targeting is structurally valid
- the final payload is internally consistent

## Common authoring mistakes

### Putting sweep values in Defaults

Problem:

- the value is not actually constant across the acquisition

Consequence:

- all frames inherit the wrong baseline until individually replaced

Correction:

- move the varying field into **Frame Mapping**

### Overusing overrides

Problem:

- fields that never change are repeated on many frame rows

Consequence:

- the datacard becomes harder to review and easier to break

Correction:

- move stable values into **Defaults**

### Expecting blanks to erase a default

Problem:

- an override field is left blank with the expectation that the inherited value will be cleared

Consequence:

- the inherited value remains in effect

Correction:

- author the desired explicit replacement value instead of leaving the field blank

### Expecting an eBUS-managed field to appear in frame mapping

Problem:

- the field is acquisition-wide eBUS-managed and therefore excluded from frame-targeted override tools

Consequence:

- the field cannot be swept or block-switched through the wizard's row generator

Correction:

- treat the field as acquisition-wide in the current design, or redesign the eBUS interaction contract before expecting frame-targeted behavior

## Recommended next pages

- [Data Workflow](../data-workflow.md)
- [eBUS Config Tools](ebus-config-tools.md)
- [Measure Workflow](../measure-workflow.md)
- [Troubleshooting](../troubleshooting.md)
