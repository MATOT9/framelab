# Acquisition Mapping

The acquisition field mapping JSON defines which canonical datacard fields the wizard exposes and how those fields behave in the editor.

This mapping is an editor/schema-definition file. It does not directly define measurement formulas or analysis behavior.

## Mapping file locations

- editable runtime file: `config/acquisition_field_mapping.json`
- bundled default file: `framelab/assets/acquisition_field_mapping.default.json`

The editable runtime file is the normal source used by the wizard. If it is missing, the app seeds it from the bundled default file.

## Field definition keys

| Key | Required | Meaning |
| --- | --- | --- |
| `key` | Yes | Dot-path stored in the datacard payload |
| `label` | Yes | User-facing field label shown in the wizard |
| `group` | No | Wizard group heading; defaults to `General` when omitted or blank |
| `type` | Yes | One of `int`, `float`, `bool`, `enum`, or `string` |
| `tooltip` | No | Hover text for the field; blank means no tooltip |
| `ebus_label` | No | Qualified eBUS key used to map an effective eBUS value into this canonical field |
| `ebus_managed` | No | Whether this canonical field becomes acquisition-wide eBUS-managed when a readable acquisition-local snapshot exists |
| `unit` | No | Display suffix or semantic unit hint |
| `min` | No | Optional lower bound for editor validation |
| `max` | No | Optional upper bound for editor validation |
| `step` | No | Suggested editor increment for numeric editors |
| `options` | Required for `enum` | Allowed enum choices |
| `show_in_defaults` | No | Whether the field appears in the Defaults tab |
| `show_in_overrides` | No | Whether the field appears in override-generation and override-editing tools |

## Type rules

Supported field types are:

- `int`
- `float`
- `bool`
- `enum`
- `string`

A field definition is considered invalid and is ignored if:

- `key` is missing or blank
- `label` is missing or blank
- `type` is not one of the supported values
- `type` is `enum` and `options` does not resolve to a non-empty list of non-blank values

Duplicate keys are ignored after the first valid occurrence.

## Important semantics

### Bounds

- missing `min`/`max`, blank `min`/`max`, or `null` `min`/`max` means **no bound**
- bounds are editor constraints, not physical guarantees
- invalid numeric bound values are treated as absent

### Step

`step` is an editor hint for numeric controls. It is not a measurement rule, not a required quantization, and not a guarantee that authored data changes only in that increment.

### Visibility flags

`show_in_defaults` and `show_in_overrides` control **UI visibility**, not datacard payload validity.

That means:

- a hidden field is not automatically illegal in payloads
- a visible field is not automatically required in payloads
- these flags decide where the wizard exposes the field, not whether a hand-edited payload may contain it

### `ebus_label`

`ebus_label` links one canonical field to one qualified eBUS parameter key, for example `device.Exposure`.

The reverse eBUS-to-canonical lookup is derived at runtime from this mapping. The eBUS catalog does not redundantly store canonical field keys.

### `ebus_managed`

`ebus_managed: true` means:

- a readable acquisition-local eBUS snapshot may drive this canonical field acquisition-wide
- the wizard still shows the field in **Defaults**
- the field becomes read-only or app-overridable there depending on the eBUS catalog entry for the bound key
- the field is excluded from frame-targeted override tools while it is acquisition-wide eBUS-managed

`ebus_managed: false` means the field continues to use the normal datacard defaults and frame-targeted overrides model.

## Minimal example

```json
{
  "fields": [
    {
      "key": "camera_settings.exposure_us",
      "label": "Exposure [us]",
      "group": "Camera",
      "type": "int",
      "tooltip": "Camera exposure time in microseconds.",
      "ebus_label": "device.Exposure",
      "ebus_managed": true,
      "min": 1,
      "max": null,
      "step": 1,
      "show_in_defaults": true,
      "show_in_overrides": true
    }
  ]
}
```

## Operational guidance

Use the mapping file to define how canonical fields should be presented and validated in the authoring UI.

Do not use it to encode:

- workflow decisions that belong in the User Guide
- plugin-loading behavior
- the full eBUS parameter universe
- measurement formulas
- analysis semantics

For defaults-vs-overrides behavior and datacard inheritance semantics, see the user-facing Datacard Wizard documentation and the developer-facing datacard-system documentation.
