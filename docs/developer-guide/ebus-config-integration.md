# eBUS Config Integration

This page documents the eBUS snapshot subsystem: parser ownership, discovery rules, catalog responsibilities, effective-config precedence, and optional wizard integration.

## Why eBUS support is separate from the datacard field mapping

The app distinguishes between two different configuration spaces:

- the **canonical acquisition metadata schema** used by the app and exposed by the datacard wizard
- the much larger **eBUS parameter space** stored in `.pvcfg` snapshots

These should not be collapsed into one file. Why:

- most eBUS parameters are not canonical app metadata fields
- many are useful for compare or audit, but not as editable datacard defaults
- stuffing the full eBUS parameter universe into `acquisition_field_mapping.json` would bloat the wizard and blur schema ownership

The split is therefore:

- canonical datacard field mapping -> `config/acquisition_field_mapping.json`
- eBUS parameter catalog -> `config/ebus_parameter_catalog.json`

More specifically:

- canonical field to eBUS binding is declared once in `acquisition_field_mapping.json` through `ebus_label`
- the eBUS subsystem derives the reverse eBUS-to-canonical lookup at runtime

This avoids maintaining the same mapping twice in opposite directions.

## Ownership by module

The eBUS subsystem is intentionally split by responsibility:

- `framelab/ebus/parser.py`
  - parses immutable `.pvcfg` XML snapshots into normalized parameter records
- `framelab/ebus/catalog.py`
  - loads the editable and bundled eBUS parameter catalog
  - derives reverse eBUS-to-canonical lookup from the acquisition field mapping
- `framelab/ebus/effective.py`
  - loads app-side override maps and overlays them on the raw snapshot baseline
  - describes standalone-file versus acquisition-root sources for the inspect/compare UI
- `framelab/ebus/sidecar.py`
  - discovery helpers for acquisition-local snapshot files
- `framelab/plugins/data/ebus_config_tools/`
  - runtime UI plugin for inspect, compare, and optional wizard hand-off

The datacard wizard does not own eBUS parsing or comparison logic. It only reflects eBUS-managed canonical fields when a readable acquisition-local snapshot exists.

## Snapshot discovery rules

There are two distinct source kinds in the current app.

### Standalone file source

A path that points directly to one `.pvcfg` file is treated as a standalone snapshot source. Semantics:

- parse the raw snapshot
- no acquisition-root lookup is needed
- no acquisition-side eBUS override context is loaded automatically

### Acquisition-root source

A dataset folder is treated as an acquisition eBUS source only when it contains exactly one readable root-level `.pvcfg` file. Semantics:

- parse the discovered raw snapshot
- load any `external_sources.ebus.overrides` from the acquisition datacard
- expose that pair as an effective acquisition source

If several root-level `.pvcfg` files exist, discovery is intentionally ambiguous and the app does not guess.

## Immutable snapshot policy

The app treats the raw `.pvcfg` file as an immutable baseline artifact. The app must not:

- rewrite the XML
- normalize values back into the file
- persist app-side edits into the raw snapshot

This keeps the saved eBUS artifact and the app-authored interpretation layer distinct.

## Effective-config precedence

When an acquisition-root source is valid, effective eBUS values are synthesized in this order:

1. discover one readable root-level `.pvcfg`
2. parse the raw `.pvcfg`
3. load `external_sources.ebus.overrides`
4. overlay only catalog-`overridable` keys
5. map effective eBUS values into canonical app metadata fields for mapping entries marked `ebus_managed`

That effective acquisition-wide result then coexists with the canonical datacard model as follows:

- non-eBUS-managed canonical fields still come from normal datacard defaults and frame-targeted overrides
- eBUS-managed canonical fields come from the effective eBUS config instead of normal acquisition-wide defaults
- frame-targeted datacard overrides do not compete with those eBUS-managed keys in the current design

## Current storage model

App-side eBUS state may live in the acquisition datacard under:

```json
{
  "external_sources": {
    "ebus": {
      "overrides": {
        "device.Iris": 5
      }
    }
  }
}
```

Important nuance:

- the current behaviorally important field is `external_sources.ebus.overrides`
- the service layer can preserve additional eBUS provenance keys if they are present
- the current shipped UI primarily authors the override map rather than a full attachment/provenance record

Do not document or design around automatic provenance-writing behavior unless that feature is actually implemented.

## Why some wizard fields become read-only or stay editable

When an acquisition has a readable acquisition-local eBUS snapshot, canonical fields marked `ebus_managed: true` stay visible in the datacard wizard. This is intentional. Without it, the user would have:

- one acquisition-wide baseline path through the readable eBUS snapshot
- one competing acquisition-wide edit path through wizard defaults

Field behavior is split by catalog policy:

- `overridable: false` keeps the field read-only in Defaults
- `overridable: true` keeps the field editable in Defaults, but saves into `external_sources.ebus.overrides` instead of normal canonical defaults

This preserves visibility without allowing contradictory acquisition-wide edit paths.

## Compare semantics

The compare dialog exposes two modes that intentionally answer different questions.

### Raw compare

Compares the raw normalized snapshots exactly as saved by eBUS. Use it for:

- raw reproducibility checks
- saved transport/device/stream differences
- forensic inspection of what eBUS recorded

### Effective compare

Compares:

- raw snapshot baseline
- plus app-side acquisition-wide eBUS overrides when the source is an acquisition root

Use it for:

- app interpretation differences between acquisitions
- differences introduced by approved manual supplements
- canonical metadata differences driven by effective eBUS-managed values

Important nuance:

- standalone `.pvcfg` sources usually behave like raw sources in effective mode because they do not carry acquisition-side override context
- the current dataset folder can be preloaded as an acquisition source when the compare dialog is launched from the main window and discovery succeeds

## Optional wizard integration

The eBUS data plugin does **not** hard-depend on the datacard wizard plugin. Reason:

- inspect and compare workflows are useful even when the datacard wizard is disabled
- forcing a dependency would make eBUS tooling unavailable unless the wizard were also enabled

Current behavior:

- the eBUS plugin stands alone
- when the datacard wizard plugin is enabled, the eBUS plugin may offer an `Open Datacard Wizard` bridge action

## Maintenance rules

When extending this subsystem:

- keep `.pvcfg` parsing in `framelab/ebus`, not in widget code
- keep canonical field mapping and eBUS parameter catalog separate
- do not expand the datacard wizard into a full eBUS browser
- do not let frame-targeted overrides compete with acquisition-wide eBUS-managed fields unless that behavior is explicitly designed later
- preserve the immutable-snapshot rule
- avoid overclaiming provenance-writing features that the current UI does not actually perform

## Related pages

- [Plugin System](plugin-system.md)
- [Datacard System](datacard-system.md)
- [Reference: eBUS Parameter Catalog](../reference/ebus-parameter-catalog.md)
