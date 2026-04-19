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


def compute_roi_stats_full(
    image: np.ndarray,
    *,
    topk_count: int | None = None,
) -> dict[str, float | int | None]:
    """Return ROI stats plus optional Top-K stats constrained to the ROI view."""

    roi = np.asarray(image)
    result: dict[str, float | int | None] = {
        "roi_count": int(roi.size),
        "roi_max": float("nan"),
        "roi_sum": float("nan"),
        "roi_mean": float("nan"),
        "roi_std": float("nan"),
        "roi_sem": float("nan"),
        "roi_topk_count": None,
        "roi_topk_mean": None,
        "roi_topk_std": None,
        "roi_topk_sem": None,
    }
    if roi.size == 0:
        if topk_count is not None:
            result.update(
                {
                    "roi_topk_count": 0,
                    "roi_topk_mean": float("nan"),
                    "roi_topk_std": float("nan"),
                    "roi_topk_sem": float("nan"),
                },
            )
        return result

    roi_sum = float(np.sum(roi, dtype=np.float64))
    roi_std = float(np.std(roi, dtype=np.float64))
    result.update(
        {
            "roi_max": float(np.max(roi)),
            "roi_sum": roi_sum,
            "roi_mean": float(np.mean(roi, dtype=np.float64)),
            "roi_std": roi_std,
            "roi_sem": float(roi_std / math.sqrt(roi.size)),
        },
    )
    if topk_count is not None:
        k = min(max(1, int(topk_count)), int(roi.size))
        topk_mean, topk_std, topk_sem = compute_topk_stats_inplace(
            np.array(roi, copy=True, order="C"),
            k,
        )
        result.update(
            {
                "roi_topk_count": int(k),
                "roi_topk_mean": topk_mean,
                "roi_topk_std": topk_std,
                "roi_topk_sem": topk_sem,
            },
        )
    return result
