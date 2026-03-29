# FrameLab native backend merge notes

This backend revision is tuned to the current FrameLab worker/dataflow structure.

## Intended first integration points

Keep TIFF loading on the Python side for now:

- `framelab.image_io.read_2d_image(...)`
- `tifffile` path remains unchanged

Use the native backend first for the worker-side metric paths:

1. **Static scan**
   - Python call site: `framelab.workers.scan_single_static_image`
   - Native entry point: `framelab_compute_static_scan(...)`
   - Python-facing wrapper target: `framelab.native.compute_static_metrics(...)`

2. **Dynamic stats worker**
   - Python call site: `framelab.workers.DynamicStatsWorker.run`
   - Native entry point: `framelab_compute_dynamic_metrics(...)`
   - This is designed to replace the current sequence:
     - `apply_background(...)` for worker-side metrics
     - `compute_min_non_zero_and_max(...)`
     - `count_at_or_above_threshold(...)`
     - `compute_topk_stats_inplace(...)`

3. **ROI worker**
   - Python call site: `framelab.workers.RoiApplyWorker.run`
   - Native entry point: `framelab_compute_roi_metrics(...)`
   - Normalize / clamp ROI in Python first so NumPy slicing semantics stay the source of truth.

## Important behavior choices in this revision

- TIFF is **not** forced through the native decode layer yet.
- Background subtraction for dynamic / ROI metrics is handled **on the fly** inside the native metrics path.
- `min_non_zero` and `max_pixel` are exposed as integer-like outputs (`int64_t`) to match the current app-facing semantics better than the earlier generic-double result shape.
- Top-k stats are computed exactly with a bounded min-heap, so the worker path avoids a full corrected-frame copy plus full-array partition.
- Background shape-mismatch fallback remains a **Python-side policy decision**.

## Where the new app-shaped metrics API lives

- Header:
  - `native/include/framelab_native/metrics/app_metrics.h`
- Implementation:
  - `native/src/metrics/app_metrics.c`
- Python hook surface:
  - `framelab/native/backend.py`

## Current scope

This package still does **not** ship a finished Python extension binding.
The C API and Python-facing hook surface are now aligned with the current
FrameLab worker architecture, but the actual bridge layer remains the next step.
