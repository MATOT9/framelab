# AGENTS

These rules apply inside `tools/`.

## Tooling Boundaries

- Keep standalone packaging behavior in `build_nuitka_app.py` and `nuitka_build.toml`.
- Keep native backend build orchestration in `build_native_backend.py`.
- Keep profiling and tracing utilities narrow and task-specific.
- Do not hide application behavior inside one-off tools.

## Runtime Assets

- Packaging helpers should include required runtime assets deliberately.
- Do not copy broad artwork or generated folders into standalone builds unless code needs them.
- Keep docs bundling behavior aligned with `docs/developer-guide/packaging.md`.

## Validation

- Packaging changes should run `python tools/build_nuitka_app.py --check`.
- Native build-helper changes should run `python tools/build_native_backend.py` when feasible.
- Update maintenance docs when tool commands or expected outputs change.
