# AGENTS

These rules apply inside `framelab/ebus/`.

## Subsystem Boundaries

- Keep `.pvcfg` parsing in `parser.py`.
- Keep catalog loading and reverse canonical lookup in `catalog.py`.
- Keep effective raw-plus-override behavior in `effective.py`.
- Keep acquisition-local discovery in `sidecar.py`.
- Keep compare semantics in `compare.py`.
- Keep host-owned inspect/compare dialogs in `dialogs.py`.

## Behavior Rules

- Treat raw `.pvcfg` snapshots as immutable artifacts.
- Acquisition-root discovery requires exactly one readable root-level `.pvcfg`.
- App-side overrides belong in acquisition datacard `external_sources.ebus.overrides`.
- Only catalog-overridable keys should be overlaid into effective config.
- Datacard wizard integration is optional and conditional on that plugin being enabled.

## Validation

- eBUS metadata or mapping changes should include eBUS metadata-resolution tests.
- Plugin/startup changes should confirm `ebus_config_tools` is not rediscovered as a plugin.
- Update `docs/developer-guide/ebus-config-integration.md` when semantics change.
