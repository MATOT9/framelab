# eBUS Parameter Catalog

The eBUS parameter catalog defines how `.pvcfg` parameters are labeled, classified, compared, and optionally made overridable in the app.

It is **not** the same thing as the acquisition field mapping used by the datacard wizard.

## File locations

- editable runtime file: `config/ebus_parameter_catalog.json`
- bundled default file: `framelab/assets/ebus_parameter_catalog.default.json`

## Why this file exists separately

The eBUS parameter universe is much larger than the canonical app metadata schema.

This catalog exists so the app can:

- inspect and compare many eBUS parameters without turning them all into wizard fields
- decide which eBUS keys are safe to override in the app
- classify eBUS parameters even when they have no canonical app-metadata equivalent

## Entry keys

| Key | Required | Meaning |
| --- | --- | --- |
| `qualified_key` | Yes | Stable qualified eBUS key such as `device.Exposure` or `stream.RequestTimeout` |
| `section` | Yes | Display/group section used by inspect and compare dialogs |
| `label` | Yes | User-facing label |
| `description` | No | Hover/help description |
| `unit` | No | Unit hint for display |
| `relevance` | No | One of `scientific`, `operational`, or `ui_noise` |
| `show_in_compare` | No | Whether the parameter should normally appear in compare views |
| `show_in_summary` | No | Whether the parameter should be emphasized in summaries or compact views |
| `overridable` | No | Whether the app may store an acquisition-wide override for this eBUS key |
| `editable_in_ebus` | No | Whether the value is expected to be meaningfully editable in eBUS itself |
| `value_type_hint` | No | Type hint used by override handling, for example `int`, `float`, `bool`, or `string` |

## Important semantics

### `overridable`

This flag controls app-side edit eligibility.

If `overridable` is `true`:

- a canonical field bound to this key may stay editable in the datacard wizard Defaults tab when it is also eBUS-managed
- the app may store an acquisition-wide override in `external_sources.ebus.overrides`
- effective compare can differ from raw compare for acquisition-root sources

If `overridable` is `false`:

- the key remains inspectable and comparable
- the app must not expose it for app-side override editing

### `editable_in_ebus`

This flag is an operator hint, not a parser rule.

Use `editable_in_ebus: false` for fields where:

- the raw eBUS snapshot value is known to be fixed, placeholder-like, or untrustworthy for your workflow
- the app may need a manual supplement even though eBUS still emits a value

### Uncatalogued keys

The parser can still read keys that are not catalogued.

When a key is uncatalogued:

- it can still appear in inspect and compare flows
- fallback section and label behavior are used
- no catalog-backed relevance or override policy exists for that key

Cataloguing a key is therefore about classification and policy, not basic parser visibility.

## Canonical mapping ownership

The eBUS catalog does **not** own the canonical mapping.

Canonical mapping lives in `acquisition_field_mapping.json` through each canonical field's `ebus_label`.

That means:

- `acquisition_field_mapping.json` defines which canonical app metadata fields are tied to eBUS keys
- `ebus_parameter_catalog.json` defines how raw eBUS parameters are labeled, classified, compared, and made overridable

The app derives the reverse eBUS-to-canonical view at runtime instead of storing the same mapping twice.

## Current raw-snapshot + app-side override model

The raw snapshot stays on disk as the immutable acquisition-local or standalone `.pvcfg` file.

When an approved app-side replacement is needed, the current app stores it under:

```text
external_sources.ebus.overrides
```

This means:

- the raw eBUS artifact stays immutable
- the app-authored override layer stays explicit and reviewable in JSON
- only acquisition-wide, catalog-approved eBUS overrides are supported through the current UI

## Related pages

- [Config Files](config-files.md)
- [Acquisition Mapping](acquisition-mapping.md)
- [Developer Guide: eBUS Config Integration](../developer-guide/ebus-config-integration.md)
