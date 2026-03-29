"""Helpers for ROI normalization that mirror NumPy slice semantics."""

from __future__ import annotations

from collections.abc import Sequence


def normalize_roi_rect_like_numpy(
    roi_rect: Sequence[object],
    image_shape: Sequence[int],
) -> tuple[int, int, int, int]:
    """Clamp one ROI rectangle using NumPy slice semantics.

    Parameters
    ----------
    roi_rect:
        Four-item ``(x0, y0, x1, y1)`` ROI tuple.
    image_shape:
        Image shape whose first two dimensions are ``(height, width)``.
    """

    if len(roi_rect) != 4:
        raise ValueError("roi_rect must contain exactly 4 values")
    if len(image_shape) < 2:
        raise ValueError("image_shape must provide at least height and width")

    try:
        x0_raw, y0_raw, x1_raw, y1_raw = (int(value) for value in roi_rect)
    except (TypeError, ValueError) as exc:
        raise ValueError("roi_rect must contain integer-like values") from exc

    height = max(0, int(image_shape[0]))
    width = max(0, int(image_shape[1]))
    x0, x1, _xstep = slice(x0_raw, x1_raw).indices(width)
    y0, y1, _ystep = slice(y0_raw, y1_raw).indices(height)
    return (x0, y0, x1, y1)
