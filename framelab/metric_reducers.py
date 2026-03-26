"""Shared metric reducers with low-allocation NumPy implementations."""

from __future__ import annotations

import math

import numpy as np


def compute_min_non_zero_and_max(image: np.ndarray) -> tuple[int, int]:
    """Return minimum non-zero and maximum values without value-selection copies."""

    arr = np.asarray(image)
    if arr.size == 0:
        return (0, 0)

    if np.issubdtype(arr.dtype, np.floating):
        finite_mask = np.isfinite(arr)
        if not np.any(finite_mask):
            return (0, 0)
        max_value = float(
            np.max(
                arr,
                where=finite_mask,
                initial=-np.inf,
            ),
        )
        non_zero_mask = finite_mask & (arr != 0)
        if not np.any(non_zero_mask):
            return (0, max(int(round(max_value)), 0))
        min_non_zero = float(
            np.min(
                arr,
                where=non_zero_mask,
                initial=np.inf,
            ),
        )
        return (
            max(int(round(min_non_zero)), 0),
            max(int(round(max_value)), 0),
        )

    max_value = int(np.max(arr))
    non_zero_mask = arr != 0
    if not np.any(non_zero_mask):
        return (0, max(max_value, 0))
    min_non_zero = int(
        np.min(
            arr,
            where=non_zero_mask,
            initial=np.iinfo(arr.dtype).max,
        ),
    )
    return (max(min_non_zero, 0), max(max_value, 0))


def count_at_or_above_threshold(
    image: np.ndarray,
    threshold_value: float,
    *,
    scratch_mask: np.ndarray | None = None,
) -> tuple[int, np.ndarray]:
    """Count pixels at or above the threshold using one reusable mask buffer."""

    arr = np.asarray(image)
    if scratch_mask is None or scratch_mask.shape != arr.shape:
        scratch_mask = np.empty(arr.shape, dtype=bool)
    np.greater_equal(arr, threshold_value, out=scratch_mask)
    return (int(np.count_nonzero(scratch_mask)), scratch_mask)


def compute_topk_stats_inplace(
    image: np.ndarray,
    count: int,
) -> tuple[float, float, float]:
    """Return mean/std/sem for the largest ``count`` pixels using in-place partition."""

    flat = np.ravel(np.asarray(image))
    if flat.size == 0:
        return (float("nan"), float("nan"), float("nan"))

    k = min(max(1, int(count)), int(flat.size))
    split = int(flat.size) - k
    flat.partition(split)
    top_k = flat[split:]
    if top_k.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    std_value = float(np.std(top_k, dtype=np.float64))
    return (
        float(np.mean(top_k, dtype=np.float64)),
        std_value,
        float(std_value / math.sqrt(top_k.size)),
    )


def compute_roi_stats(image: np.ndarray) -> tuple[float, float, float, float]:
    """Return max/mean/std/sem for one ROI view without promoting the whole ROI."""

    roi = np.asarray(image)
    if roi.size == 0:
        return (np.nan, np.nan, np.nan, np.nan)
    max_value = float(np.max(roi))
    mean_value = float(np.mean(roi, dtype=np.float64))
    std_value = float(np.std(roi, dtype=np.float64))
    return (
        max_value,
        mean_value,
        std_value,
        float(std_value / math.sqrt(roi.size)),
    )
