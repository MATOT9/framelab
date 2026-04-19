# AGENTS

These rules apply inside `native/`.

## Native Boundaries

- Keep public C ABI declarations in `native/include/framelab_native/api.h`.
- Keep Python extension glue under `native/src/api/`.
- Keep decode code under `native/src/decode/`.
- Keep metric code under `native/src/metrics/`.
- Keep portable loader/file-map code under `native/src/loaders/`.
- Keep CPU dispatch and common helpers under `native/src/common/`.

## Compatibility

- Preserve Python fallback behavior when the native extension is unavailable.
- Do not change ABI contracts without updating wrapper code, docs, and tests.
- Keep platform-specific build logic in CMake/toolchain files or repo build helpers, not scattered through source.

## Validation

- Build with `python tools/build_native_backend.py`.
- Run native/decode tests from root `TESTING.md`.
- Record benchmark context for performance claims.
