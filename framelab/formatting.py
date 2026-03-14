"""Formatting helpers for metric display."""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

def _format_float_or_dash(value: float, decimals: int = 2) -> str:
    """Return fixed-decimal text for finite values, otherwise ``"-"``."""
    if not np.isfinite(value):
        return "-"
    return f"{value:.{decimals}f}"


def _rounding_digits_from_uncertainty(uncertainty: float) -> Optional[int]:
    """Return Python ``round`` digits for one-significant uncertainty."""
    if not np.isfinite(uncertainty):
        return None
    magnitude = abs(uncertainty)
    if magnitude == 0.0:
        return 2
    order = int(math.floor(math.log10(magnitude)))
    return max(-8, min(8, -order))


def format_metric_triplet(
    mean_value: float,
    std_value: float,
    sem_value: float,
    rounding_mode: str,
) -> tuple[str, str, str]:
    """Format mean, standard deviation, and standard error for display.

    Parameters
    ----------
    mean_value : float
        Central value to display.
    std_value : float
        Standard deviation associated with ``mean_value``.
    sem_value : float
        Standard error associated with ``mean_value``.
    rounding_mode : {"off", "std", "stderr"}
        Scientific rounding mode:
        - ``"off"``: fixed two-decimal formatting.
        - ``"std"``: round mean based on one significant digit of std.
        - ``"stderr"``: round mean based on one significant digit of stderr.

    Returns
    -------
    tuple[str, str, str]
        Display-ready ``(mean_text, std_text, sem_text)`` strings.
    """
    mean = float(mean_value)
    std = float(std_value)
    sem = float(sem_value)

    if not np.isfinite(mean):
        return ("-", "-", "-")

    if rounding_mode == "off":
        return (
            _format_float_or_dash(mean),
            _format_float_or_dash(std),
            _format_float_or_dash(sem),
        )

    base_uncertainty = std if rounding_mode == "std" else sem
    round_digits = _rounding_digits_from_uncertainty(base_uncertainty)
    if round_digits is None:
        return (
            _format_float_or_dash(mean),
            _format_float_or_dash(std),
            _format_float_or_dash(sem),
        )

    decimals = max(0, round_digits)
    rounded_mean = round(mean, round_digits)
    rounded_std = round(std, round_digits) if np.isfinite(std) else np.nan
    rounded_sem = round(sem, round_digits) if np.isfinite(sem) else np.nan

    return (
        f"{rounded_mean:.{decimals}f}",
        _format_float_or_dash(rounded_std, decimals),
        _format_float_or_dash(rounded_sem, decimals),
    )


def format_value_with_uncertainty(
    value: float,
    uncertainty: float,
    rounding_mode: str,
    off_decimals: int = 3,
) -> tuple[str, str]:
    """Format value and uncertainty with optional scientific rounding.

    Parameters
    ----------
    value : float
        Value to display.
    uncertainty : float
        Uncertainty associated with ``value``.
    rounding_mode : {"off", "std", "stderr"}
        Rounding selector. Any non-``"off"`` mode rounds using one
        significant digit of ``uncertainty``.
    off_decimals : int, default=3
        Fixed decimal precision used when ``rounding_mode == "off"``.

    Returns
    -------
    tuple[str, str]
        Display-ready ``(value_text, uncertainty_text)`` strings.
    """
    val = float(value)
    unc = float(uncertainty)
    if not np.isfinite(val):
        return ("-", "-")

    if rounding_mode == "off":
        return (
            _format_float_or_dash(val, off_decimals),
            _format_float_or_dash(unc, off_decimals),
        )

    digits = _rounding_digits_from_uncertainty(unc)
    if digits is None:
        return (
            _format_float_or_dash(val, off_decimals),
            _format_float_or_dash(unc, off_decimals),
        )

    decimals = max(0, digits)
    rounded_value = round(val, digits)
    rounded_unc = round(unc, digits) if np.isfinite(unc) else np.nan
    return (
        f"{rounded_value:.{decimals}f}",
        _format_float_or_dash(rounded_unc, decimals),
    )
