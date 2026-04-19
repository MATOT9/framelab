# Benchmark Workflow

Use this page for performance work in image decode, native metrics, and UI/runtime pipelines.

## Before Measuring

- Identify the exact bottleneck: decode, metadata resolution, metric computation, UI update, plotting, or packaging startup.
- Record dataset size, pixel format, image dimensions, backend path, and active preferences.
- Check whether the native extension is present or Python fallback is in use.
- Keep measurement changes separate from broad refactors.

## Python-Level Checks

Use targeted tests first:

```bash
python scripts/tests.py tests/test_raw_decode.py tests/test_native_backend.py
python scripts/tests.py tests/test_metrics_math.py tests/test_workers.py
```

Use `tools/profile_metrics_backend.py` when comparing backend paths or metric performance.

## Native Backend Checks

Build before benchmarking:

```bash
python tools/build_native_backend.py
```

Then verify the Python wrapper and decode/metric behavior through the relevant tests. Native C changes should preserve fallback behavior when the extension is unavailable.

## UI Runtime Checks

For UI performance, separate:

- scanning and metadata resolution
- image loading and cache behavior
- metric worker runtime
- worker result application
- table or preview repaint cost
- analysis plot refresh cost

Prefer controller or worker instrumentation before changing widget layout.

## Reporting Results

Record:

- command used
- dataset or fixture description
- backend path
- before/after timing
- variance or repeated-run notes
- follow-up tests needed

If a performance item moves from backlog to shipped behavior, update root `CURRENT_STATE.md`, `KNOWN_ISSUES.md`, and `ROADMAP.md`.
