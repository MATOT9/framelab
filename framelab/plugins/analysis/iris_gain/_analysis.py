"""Curve building, math helpers, and result-table population."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Optional

import numpy as np
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

from .._base import AnalysisRecord
from ._shared import _CurveSeries, _FitSeries, _SortableTableItem


class IrisGainAnalysisMixin:
    """Analysis math and result-table helpers."""

    @staticmethod
    def _to_numeric(value: object) -> Optional[float]:
        """Convert a value to finite float, returning ``None`` otherwise."""
        try:
            number = float(value)
        except Exception:
            return None
        if not np.isfinite(number):
            return None
        return number

    @staticmethod
    def _format_float(value: float) -> str:
        """Format a floating-point value using default display precision."""
        return IrisGainAnalysisMixin._format_float_with_decimals(value, None)

    @staticmethod
    def _format_float_with_decimals(
        value: float,
        decimals: Optional[int],
    ) -> str:
        """Format float with optional fixed decimals."""
        if not np.isfinite(value):
            return "-"
        if decimals is None:
            return f"{value:.6g}"
        safe_decimals = max(0, int(decimals))
        return f"{value:.{safe_decimals}f}"

    def _current_data(
        self,
        combo: Optional[qtw.QComboBox],
        default: str,
    ) -> str:
        """Return current combo data as a string with a fallback value."""
        if combo is None:
            return default
        value = combo.currentData()
        return str(value) if value is not None else default

    def _series_info(
        self,
        record: AnalysisRecord,
        x_mode: str,
    ) -> Optional[tuple[float, str, tuple[int, float | str]]]:
        """Return X value, series label, and stable sort key for a record."""
        metadata = record.metadata
        if x_mode == "iris":
            x_value = self._to_numeric(metadata.get("iris_position"))
            if x_value is None:
                return None
            exp_value = self._to_numeric(metadata.get("exposure_ms"))
            if exp_value is None:
                return (x_value, "Exposure (missing)", (1, "missing"))
            return (
                x_value,
                f"Exp {exp_value:g} ms",
                (0, exp_value),
            )

        x_value = self._to_numeric(metadata.get("exposure_ms"))
        if x_value is None:
            return None
        iris_value = self._to_numeric(metadata.get("iris_position"))
        if iris_value is not None:
            return (
                x_value,
                f"Iris {iris_value:g}",
                (0, iris_value),
            )

        iris_label = metadata.get("iris_label")
        if iris_label not in (None, ""):
            label = str(iris_label)
            return (x_value, label, (1, label.lower()))

        parent = metadata.get("parent_folder")
        label = str(parent) if parent not in (None, "") else "Iris (missing)"
        return (x_value, label, (1, label.lower()))

    def _source_y_mode(self, x_mode: str, y_mode: str) -> str:
        """Return the raw metric source used to build the requested Y mode."""
        if x_mode == "iris" and y_mode in {"gain", "gain_last"}:
            return "dn_per_ms"
        return y_mode

    def _source_value_for_y(
        self,
        record: AnalysisRecord,
        y_mode: str,
        x_mode: str,
    ) -> Optional[float]:
        """Return raw metric value used for the chosen Y axis."""
        if y_mode in {"gain", "gain_last"}:
            if x_mode == "exposure":
                return float(record.mean) if np.isfinite(record.mean) else None
            return self._to_numeric(record.metadata.get("dn_per_ms"))
        if y_mode == "mean":
            return float(record.mean) if np.isfinite(record.mean) else None
        if y_mode == "dn_per_ms":
            return self._to_numeric(record.metadata.get("dn_per_ms"))
        return self._to_numeric(record.metadata.get("max_pixel"))

    def _source_error_for_y(
        self,
        record: AnalysisRecord,
        y_mode: str,
        err_mode: str,
        x_mode: str,
    ) -> float:
        """Return raw per-record uncertainty for the chosen Y mode."""
        def _metadata_error(key: str) -> float:
            value = self._to_numeric(record.metadata.get(key))
            return float(value) if value is not None else float(np.nan)

        if err_mode == "off":
            return float(np.nan)
        if y_mode in {"gain", "gain_last"}:
            if x_mode == "exposure":
                if err_mode == "std":
                    return (
                        float(record.std)
                        if np.isfinite(record.std)
                        else float(np.nan)
                    )
                return (
                    float(record.sem)
                    if np.isfinite(record.sem)
                    else float(np.nan)
                )
            if err_mode == "std":
                return _metadata_error("dn_per_ms_std")
            return _metadata_error("dn_per_ms_sem")
        if y_mode == "mean":
            if err_mode == "std":
                return (
                    float(record.std)
                    if np.isfinite(record.std)
                    else float(np.nan)
                )
            return (
                float(record.sem)
                if np.isfinite(record.sem)
                else float(np.nan)
            )
        if y_mode == "dn_per_ms":
            if err_mode == "std":
                return _metadata_error("dn_per_ms_std")
            return _metadata_error("dn_per_ms_sem")
        return float(np.nan)

    def _error_value(self, samples: np.ndarray, mode: str) -> float:
        """Return std or std error for a sample vector."""
        if mode == "off" or samples.size == 0:
            return float(np.nan)
        std_value = float(np.std(samples))
        if mode == "std":
            return std_value
        return std_value / float(np.sqrt(samples.size))

    @staticmethod
    def _round_digits_from_uncertainty(uncertainty: float) -> Optional[int]:
        """Return ``round`` digits for one-significant-digit uncertainty."""
        if not np.isfinite(uncertainty):
            return None
        magnitude = abs(uncertainty)
        if magnitude <= 0.0:
            return None
        order = int(math.floor(math.log10(magnitude)))
        return max(-8, min(8, -order))

    @staticmethod
    def _round_uncertainty_one_sd(uncertainty: float) -> float:
        """Round uncertainty to one significant digit."""
        if not np.isfinite(uncertainty):
            return uncertainty
        magnitude = abs(float(uncertainty))
        if magnitude <= 0.0:
            return float(uncertainty)
        order = int(math.floor(math.log10(magnitude)))
        scale = 10.0**order
        rounded = round(magnitude / scale) * scale
        return float(math.copysign(rounded, float(uncertainty)))

    def _round_value_and_error(
        self,
        value: float,
        error: float,
    ) -> tuple[float, float]:
        """Round uncertainty to 1 s.d., then round value to same precision."""
        if not np.isfinite(value) or not np.isfinite(error):
            return (value, error)
        rounded_error = self._round_uncertainty_one_sd(error)
        digits = self._round_digits_from_uncertainty(rounded_error)
        if digits is None:
            return (value, rounded_error)
        return (
            float(round(value, digits)),
            float(round(rounded_error, digits)),
        )

    def _rounding_decimals_from_error(self, error: float) -> Optional[int]:
        """Return display decimals implied by 1-s.d. rounded uncertainty."""
        rounded_error = self._round_uncertainty_one_sd(error)
        digits = self._round_digits_from_uncertainty(rounded_error)
        if digits is None:
            return None
        return max(0, int(digits))

    @staticmethod
    def _propagated_mean_uncertainty(samples: np.ndarray) -> float:
        """Propagate uncertainty of arithmetic mean from per-sample errors."""
        arr = np.asarray(samples, dtype=np.float64)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return float(np.nan)
        return float(np.sqrt(np.sum(arr**2)) / float(arr.size))

    @staticmethod
    def _relative_uncertainty_percent(value: float, error: float) -> float:
        """Return relative uncertainty (error/value) in percent."""
        if (
            not np.isfinite(value)
            or not np.isfinite(error)
            or np.isclose(value, 0.0, atol=1e-15)
        ):
            return float(np.nan)
        return float(abs(error / value) * 100.0)

    @staticmethod
    def _gain_last_alignment_parameters(
        values: np.ndarray,
    ) -> tuple[float, Optional[int]]:
        """Return alignment factor and first finite index for gain-last mode."""
        arr = np.asarray(values, dtype=np.float64)
        if arr.size == 0:
            return (1.0, None)
        finite_idx = np.flatnonzero(np.isfinite(arr))
        if finite_idx.size == 0:
            return (1.0, None)
        first_index = int(finite_idx[0])
        first_value = float(arr[first_index])
        if np.isclose(first_value, 0.0, atol=1e-15):
            return (1.0, None)
        return (float(1.0 / first_value), first_index)

    def _apply_gain_last_alignment(
        self,
        values: np.ndarray,
    ) -> tuple[np.ndarray, float, Optional[int]]:
        """Apply gain-last alignment and return scaled values and factor."""
        arr = np.asarray(values, dtype=np.float64)
        factor, first_index = self._gain_last_alignment_parameters(arr)
        aligned = arr * factor
        if first_index is not None and first_index < aligned.size:
            aligned[first_index] = 1.0
        return (aligned, float(abs(factor)), first_index)

    def _is_gain_last_alignment_enabled(self, y_mode: str) -> bool:
        """Return whether gain-last display alignment is enabled."""
        return (
            y_mode == "gain_last"
            and self._gain_last_align_checkbox is not None
            and self._gain_last_align_checkbox.isChecked()
        )

    def _gain_from_curve_reference(
        self,
        y_values: list[float],
        err_values: list[float],
        err_mode: str,
        reference_index: int,
    ) -> tuple[list[float], list[float]]:
        """Convert y-values to gain relative to a selected reference point."""
        if not y_values:
            return ([], [])

        n_values = len(y_values)
        ref_idx = reference_index
        if ref_idx < 0:
            ref_idx = n_values + ref_idx
        if ref_idx < 0 or ref_idx >= n_values:
            return (
                [float(np.nan)] * n_values,
                [float(np.nan)] * len(err_values),
            )

        gains = [float(np.nan)] * len(y_values)
        gain_errs = [float(np.nan)] * len(err_values)
        gains[ref_idx] = 1.0
        if err_mode != "off" and ref_idx < len(gain_errs):
            gain_errs[ref_idx] = 0.0

        ref_value = float(y_values[ref_idx])
        ref_error = (
            float(err_values[ref_idx])
            if ref_idx < len(err_values)
            else float(np.nan)
        )
        if not np.isfinite(ref_value) or np.isclose(ref_value, 0.0, atol=1e-12):
            return (gains, gain_errs)

        for idx in range(len(y_values)):
            if idx == ref_idx:
                continue
            value = float(y_values[idx])
            if not np.isfinite(value):
                continue

            gain = value / ref_value
            gains[idx] = float(gain)
            if err_mode == "off":
                continue

            value_error = (
                float(err_values[idx])
                if idx < len(err_values)
                else float(np.nan)
            )
            variance_terms: list[float] = []
            if np.isfinite(value_error) and not np.isclose(value, 0.0, atol=1e-12):
                variance_terms.append((value_error / value) ** 2)
            if np.isfinite(ref_error):
                variance_terms.append((ref_error / ref_value) ** 2)
            if variance_terms:
                gain_errs[idx] = float(abs(gain) * np.sqrt(sum(variance_terms)))
        return (gains, gain_errs)

    def _build_iris_gain_from_mean_dn_per_ms(
        self,
        records: list[AnalysisRecord],
        y_mode: str,
        err_mode: str,
        round_to_sd: bool,
    ) -> list[_CurveSeries]:
        """Build single gain curve from mean DN/ms at each iris position."""
        grouped: dict[float, list[tuple[float, float, float]]] = defaultdict(list)
        for record in records:
            x_value = self._to_numeric(record.metadata.get("iris_position"))
            y_value = self._to_numeric(record.metadata.get("dn_per_ms"))
            if x_value is None or y_value is None:
                continue
            std_value = self._to_numeric(record.metadata.get("dn_per_ms_std"))
            sem_value = self._to_numeric(record.metadata.get("dn_per_ms_sem"))
            grouped[self._x_key(x_value)].append(
                (
                    float(y_value),
                    float(std_value) if std_value is not None else float(np.nan),
                    float(sem_value) if sem_value is not None else float(np.nan),
                )
            )

        if not grouped:
            return []

        x_values: list[float] = []
        base_values: list[float] = []
        std_values: list[float] = []
        sem_values: list[float] = []
        counts: list[int] = []
        for x_key in sorted(grouped.keys()):
            samples = grouped[x_key]
            value_arr = np.asarray(
                [sample[0] for sample in samples],
                dtype=np.float64,
            )
            value_arr = value_arr[np.isfinite(value_arr)]
            if value_arr.size == 0:
                continue
            std_arr = np.asarray([sample[1] for sample in samples], dtype=np.float64)
            sem_arr = np.asarray([sample[2] for sample in samples], dtype=np.float64)

            x_values.append(float(x_key))
            base_values.append(float(np.mean(value_arr)))
            std_values.append(self._propagated_mean_uncertainty(std_arr))
            sem_values.append(self._propagated_mean_uncertainty(sem_arr))
            counts.append(int(value_arr.size))

        if not x_values:
            return []

        ref_index = 0 if y_mode == "gain" else -1
        selected_source_errors = (
            list(std_values)
            if err_mode == "std"
            else list(sem_values)
            if err_mode == "stderr"
            else [float(np.nan)] * len(base_values)
        )
        gain_values, gain_err_values = self._gain_from_curve_reference(
            list(base_values),
            selected_source_errors,
            err_mode,
            ref_index,
        )
        _, gain_std_values = self._gain_from_curve_reference(
            list(base_values),
            list(std_values),
            "std",
            ref_index,
        )
        _, gain_sem_values = self._gain_from_curve_reference(
            list(base_values),
            list(sem_values),
            "stderr",
            ref_index,
        )

        if round_to_sd and err_mode in {"std", "stderr"}:
            source_errors = (
                gain_std_values if err_mode == "std" else gain_sem_values
            )
            rounded_y: list[float] = []
            rounded_errors: list[float] = []
            for y_value, source_error in zip(gain_values, source_errors):
                rounded_y_value, rounded_error = self._round_value_and_error(
                    y_value,
                    source_error,
                )
                rounded_y.append(rounded_y_value)
                rounded_errors.append(rounded_error)
            gain_values = rounded_y
            if err_mode == "std":
                gain_std_values = rounded_errors
            else:
                gain_sem_values = rounded_errors
            gain_err_values = list(rounded_errors)

        return [
            _CurveSeries(
                curve_id=1,
                label="Mean DN/ms by Iris",
                x_values=x_values,
                y_values=gain_values,
                std_values=gain_std_values,
                sem_values=gain_sem_values,
                error_values=gain_err_values,
                point_counts=counts,
            )
        ]

    def _build_curves(
        self,
        records: list[AnalysisRecord],
        x_mode: str,
        y_mode: str,
        err_mode: str,
    ) -> list[_CurveSeries]:
        """Build display curves from raw records and selected axis modes."""
        source_y_mode = self._source_y_mode(x_mode, y_mode)
        raw_curves: dict[str, dict[str, object]] = {}

        for record in records:
            info = self._series_info(record, x_mode)
            if info is None:
                continue
            x_value, curve_label, sort_key = info
            y_value = self._source_value_for_y(record, source_y_mode, x_mode)
            if y_value is None or not np.isfinite(y_value):
                continue
            y_error = self._source_error_for_y(
                record,
                source_y_mode,
                err_mode,
                x_mode,
            )
            x_key = float(round(x_value, 12))
            if curve_label not in raw_curves:
                raw_curves[curve_label] = {
                    "sort_key": sort_key,
                    "points": defaultdict(list),
                    "point_errors": defaultdict(list),
                }
            points = raw_curves[curve_label]["points"]
            assert isinstance(points, defaultdict)
            points[x_key].append(float(y_value))
            point_errors = raw_curves[curve_label]["point_errors"]
            assert isinstance(point_errors, defaultdict)
            point_errors[x_key].append(float(y_error))

        sorted_curves = sorted(
            raw_curves.items(),
            key=lambda item: item[1]["sort_key"],  # type: ignore[index]
        )
        built: list[_CurveSeries] = []
        for curve_idx, (curve_label, payload) in enumerate(sorted_curves, start=1):
            points = payload["points"]
            assert isinstance(points, defaultdict)
            point_errors = payload["point_errors"]
            assert isinstance(point_errors, defaultdict)

            x_values: list[float] = []
            y_values: list[float] = []
            std_values: list[float] = []
            sem_values: list[float] = []
            err_values: list[float] = []
            point_counts: list[int] = []
            for x_key in sorted(points.keys()):
                values = np.asarray(points[x_key], dtype=np.float64)
                values = values[np.isfinite(values)]
                if values.size == 0:
                    continue

                y_point = float(np.mean(values))
                n_point = int(values.size)
                std_point = float(np.std(values))
                sem_point = float(std_point / np.sqrt(max(1, n_point)))
                if err_mode == "off":
                    err_point = float(np.nan)
                else:
                    err_samples = np.asarray(
                        point_errors.get(x_key, []),
                        dtype=np.float64,
                    )
                    err_samples = err_samples[np.isfinite(err_samples)]
                    if err_samples.size > 0:
                        err_point = float(
                            np.sqrt(np.sum(err_samples**2)) / max(1, n_point)
                        )
                    elif source_y_mode == "max_pixel":
                        err_point = self._error_value(values, err_mode)
                    else:
                        err_point = float(np.nan)

                x_values.append(float(x_key))
                y_values.append(y_point)
                std_values.append(std_point)
                sem_values.append(sem_point)
                err_values.append(err_point)
                point_counts.append(n_point)

            if not x_values:
                continue

            if y_mode in {"gain", "gain_last"} and x_mode == "exposure":
                ref_index = 0 if y_mode == "gain" else -1
                y_for_gain = list(y_values)
                y_values, err_values = self._gain_from_curve_reference(
                    y_for_gain,
                    err_values,
                    err_mode,
                    ref_index,
                )
                _, std_values = self._gain_from_curve_reference(
                    y_for_gain,
                    std_values,
                    "std",
                    ref_index,
                )
                _, sem_values = self._gain_from_curve_reference(
                    y_for_gain,
                    sem_values,
                    "stderr",
                    ref_index,
                )

            built.append(
                _CurveSeries(
                    curve_id=curve_idx,
                    label=curve_label,
                    x_values=x_values,
                    y_values=y_values,
                    std_values=std_values,
                    sem_values=sem_values,
                    error_values=err_values,
                    point_counts=point_counts,
                )
            )
        return built

    @staticmethod
    def _fit_from_points(
        x_vals: np.ndarray,
        y_vals: np.ndarray,
    ) -> Optional[_FitSeries]:
        """Compute linear regression fit and R^2 from x/y arrays."""
        x_vals = np.asarray(x_vals, dtype=np.float64)
        y_vals = np.asarray(y_vals, dtype=np.float64)
        finite_mask = np.isfinite(x_vals) & np.isfinite(y_vals)
        x_fit = x_vals[finite_mask]
        y_fit = y_vals[finite_mask]
        if x_fit.size < 2:
            return None

        x_span = float(np.max(x_fit) - np.min(x_fit))
        if np.isclose(x_span, 0.0, atol=1e-15):
            return None

        try:
            slope, intercept = np.polyfit(x_fit, y_fit, 1)
        except Exception:
            return None

        y_pred = slope * x_fit + intercept
        ss_res = float(np.sum((y_fit - y_pred) ** 2))
        mean_y = float(np.mean(y_fit))
        ss_tot = float(np.sum((y_fit - mean_y) ** 2))
        if np.isclose(ss_tot, 0.0, atol=1e-18):
            r2 = 1.0 if np.isclose(ss_res, 0.0, atol=1e-18) else float(np.nan)
        else:
            r2 = 1.0 - (ss_res / ss_tot)

        x_line = np.linspace(float(np.min(x_fit)), float(np.max(x_fit)), 128)
        y_line = slope * x_line + intercept
        return _FitSeries(
            label="Linear fit",
            slope=float(slope),
            intercept=float(intercept),
            r2=float(r2),
            x_values=x_line,
            y_values=y_line,
            kind="linear_fit",
        )

    def _build_linear_fit(self, curves: list[_CurveSeries]) -> list[_FitSeries]:
        """Build single global linear fit across all visible series points."""
        x_chunks: list[np.ndarray] = []
        y_chunks: list[np.ndarray] = []
        for curve in curves:
            if not self._curve_visibility.get(curve.label, True):
                continue
            x_arr = np.asarray(curve.x_values, dtype=np.float64)
            y_arr = np.asarray(curve.y_values, dtype=np.float64)
            if x_arr.size == 0 or y_arr.size == 0:
                continue
            x_chunks.append(x_arr)
            y_chunks.append(y_arr)

        if not x_chunks:
            return []
        fit = self._fit_from_points(
            np.concatenate(x_chunks),
            np.concatenate(y_chunks),
        )
        return [fit] if fit is not None else []

    def _build_mean_x_overlay(self, curves: list[_CurveSeries]) -> list[_FitSeries]:
        """Build a single global line using weighted mean Y at each X value."""
        grouped: dict[float, list[tuple[float, int, float, float]]] = defaultdict(
            list,
        )
        for curve in curves:
            if not self._curve_visibility.get(curve.label, True):
                continue
            for x_value, y_value, count, std_value, sem_value in zip(
                curve.x_values,
                curve.y_values,
                curve.point_counts,
                curve.std_values,
                curve.sem_values,
            ):
                if not np.isfinite(x_value) or not np.isfinite(y_value):
                    continue
                weight = max(1, int(count))
                x_key = float(round(float(x_value), 12))
                grouped[x_key].append(
                    (
                        float(y_value),
                        weight,
                        float(std_value),
                        float(sem_value),
                    )
                )

        if not grouped:
            return []

        x_values: list[float] = []
        y_values: list[float] = []
        std_values: list[float] = []
        sem_values: list[float] = []
        for x_key in sorted(grouped.keys()):
            pairs = grouped[x_key]
            weights = np.asarray([pair[1] for pair in pairs], dtype=np.float64)
            values = np.asarray([pair[0] for pair in pairs], dtype=np.float64)
            total = float(np.sum(weights))
            if not np.isfinite(total) or total <= 0.0:
                continue
            weighted_mean = float(np.sum(values * weights) / total)
            if len(pairs) == 1:
                single_std = float(pairs[0][2])
                single_sem = float(pairs[0][3])
                weighted_std = (
                    single_std if np.isfinite(single_std) else float(np.nan)
                )
                weighted_sem = (
                    single_sem if np.isfinite(single_sem) else float(np.nan)
                )
            else:
                weighted_var = float(
                    np.sum(weights * (values - weighted_mean) ** 2) / total
                )
                weighted_std = float(np.sqrt(max(0.0, weighted_var)))
                weighted_sem = float(weighted_std / np.sqrt(max(1.0, total)))
            x_values.append(float(x_key))
            y_values.append(weighted_mean)
            std_values.append(weighted_std)
            sem_values.append(weighted_sem)

        if not x_values:
            return []

        return [
            _FitSeries(
                label="Mean by X",
                slope=float(np.nan),
                intercept=float(np.nan),
                r2=float(np.nan),
                x_values=np.asarray(x_values, dtype=np.float64),
                y_values=np.asarray(y_values, dtype=np.float64),
                std_values=np.asarray(std_values, dtype=np.float64),
                sem_values=np.asarray(sem_values, dtype=np.float64),
                kind="mean_x",
            )
        ]

    def _build_overlay_series(
        self,
        curves: list[_CurveSeries],
        overlay_mode: str,
        x_mode: str,
        y_mode: str,
        err_mode: str,
    ) -> list[_FitSeries]:
        """Build overlay series for the selected trend-line mode."""
        if overlay_mode == "linear_fit":
            overlay = self._build_linear_fit(curves)
        elif overlay_mode == "mean_x":
            overlay = self._build_mean_x_overlay(curves)
        else:
            return []

        if (
            overlay_mode == "mean_x"
            and x_mode == "iris"
            and y_mode in {"gain", "gain_last"}
        ):
            return self._convert_mean_overlay_to_gain(
                overlay,
                y_mode,
                err_mode,
            )
        return overlay

    def _convert_mean_overlay_to_gain(
        self,
        overlay: list[_FitSeries],
        y_mode: str,
        err_mode: str,
    ) -> list[_FitSeries]:
        """Convert mean-by-X DN/ms overlay to gain with propagated errors."""
        if not overlay:
            return []
        fit = overlay[0]
        if fit.kind != "mean_x":
            return overlay

        y_arr = np.asarray(fit.y_values, dtype=np.float64)
        if y_arr.size == 0:
            return overlay

        std_arr = (
            np.asarray(fit.std_values, dtype=np.float64)
            if fit.std_values is not None
            else np.full(y_arr.shape, np.nan, dtype=np.float64)
        )
        sem_arr = (
            np.asarray(fit.sem_values, dtype=np.float64)
            if fit.sem_values is not None
            else np.full(y_arr.shape, np.nan, dtype=np.float64)
        )
        if std_arr.size != y_arr.size:
            std_arr = np.full(y_arr.shape, np.nan, dtype=np.float64)
        if sem_arr.size != y_arr.size:
            sem_arr = np.full(y_arr.shape, np.nan, dtype=np.float64)

        ref_index = 0 if y_mode == "gain" else -1
        selected_errors = (
            list(std_arr)
            if err_mode == "std"
            else list(sem_arr)
            if err_mode == "stderr"
            else [float(np.nan)] * y_arr.size
        )
        gain_values, _ = self._gain_from_curve_reference(
            list(y_arr),
            selected_errors,
            err_mode,
            ref_index,
        )
        _, gain_std = self._gain_from_curve_reference(
            list(y_arr),
            list(std_arr),
            "std",
            ref_index,
        )
        _, gain_sem = self._gain_from_curve_reference(
            list(y_arr),
            list(sem_arr),
            "stderr",
            ref_index,
        )
        return [
            _FitSeries(
                label=fit.label,
                slope=fit.slope,
                intercept=fit.intercept,
                r2=fit.r2,
                x_values=np.asarray(fit.x_values, dtype=np.float64),
                y_values=np.asarray(gain_values, dtype=np.float64),
                std_values=np.asarray(gain_std, dtype=np.float64),
                sem_values=np.asarray(gain_sem, dtype=np.float64),
                kind=fit.kind,
            )
        ]

    @staticmethod
    def _x_key(value: float) -> float:
        """Normalize X values to stable dictionary keys."""
        return float(round(float(value), 12))

    def _point_count_by_x(self, curves: list[_CurveSeries]) -> dict[float, int]:
        """Return total point-count per X over visible curves."""
        counts: dict[float, int] = defaultdict(int)
        for curve in curves:
            if not self._curve_visibility.get(curve.label, True):
                continue
            for x_value, n_points in zip(curve.x_values, curve.point_counts):
                if not np.isfinite(x_value):
                    continue
                counts[self._x_key(x_value)] += int(max(0, n_points))
        return counts

    def _trend_table_rows(
        self,
        curves: list[_CurveSeries],
        fit_series: list[_FitSeries],
        overlay_mode: str,
        err_mode: str,
        round_to_sd: bool,
    ) -> list[tuple[int, str, int, float, float, float, float, float]]:
        """Build rows representing trend-only points."""
        if not fit_series:
            return []

        fit = fit_series[0]
        rows: list[tuple[int, str, int, float, float, float, float, float]] = []
        counts_by_x = self._point_count_by_x(curves)

        if overlay_mode == "mean_x":
            std_arr = (
                np.asarray(fit.std_values, dtype=np.float64)
                if fit.std_values is not None
                else np.asarray([], dtype=np.float64)
            )
            sem_arr = (
                np.asarray(fit.sem_values, dtype=np.float64)
                if fit.sem_values is not None
                else np.asarray([], dtype=np.float64)
            )
            for idx, x_value in enumerate(np.asarray(fit.x_values, dtype=np.float64)):
                y_value = float(fit.y_values[idx])
                count = int(counts_by_x.get(self._x_key(float(x_value)), 0))
                std_value = (
                    float(std_arr[idx])
                    if idx < std_arr.size
                    else float(np.nan)
                )
                sem_value = (
                    float(sem_arr[idx])
                    if idx < sem_arr.size
                    else float(np.nan)
                )
                selected_error = (
                    std_value
                    if err_mode == "std"
                    else sem_value
                    if err_mode == "stderr"
                    else float(np.nan)
                )
                delta_percent = self._relative_uncertainty_percent(
                    y_value,
                    selected_error,
                )
                if round_to_sd and err_mode != "off":
                    if err_mode == "std":
                        y_value, std_value = self._round_value_and_error(
                            y_value,
                            std_value,
                        )
                    else:
                        y_value, sem_value = self._round_value_and_error(
                            y_value,
                            sem_value,
                        )
                    if np.isfinite(delta_percent):
                        delta_percent = float(round(delta_percent, 2))
                rows.append(
                    (
                        1,
                        fit.label,
                        count,
                        float(x_value),
                        y_value,
                        std_value,
                        sem_value,
                        delta_percent,
                    )
                )
            return rows

        if overlay_mode == "linear_fit":
            x_chunks: list[np.ndarray] = []
            for curve in curves:
                if not self._curve_visibility.get(curve.label, True):
                    continue
                x_arr = np.asarray(curve.x_values, dtype=np.float64)
                x_arr = x_arr[np.isfinite(x_arr)]
                if x_arr.size:
                    x_chunks.append(x_arr)
            if not x_chunks:
                return []

            mean_overlay = self._build_mean_x_overlay(curves)
            mean_fit = mean_overlay[0] if mean_overlay else None
            std_by_x: dict[float, float] = {}
            sem_by_x: dict[float, float] = {}
            if mean_fit is not None:
                std_arr = (
                    np.asarray(mean_fit.std_values, dtype=np.float64)
                    if mean_fit.std_values is not None
                    else np.asarray([], dtype=np.float64)
                )
                sem_arr = (
                    np.asarray(mean_fit.sem_values, dtype=np.float64)
                    if mean_fit.sem_values is not None
                    else np.asarray([], dtype=np.float64)
                )
                for idx, x_value in enumerate(mean_fit.x_values):
                    x_key = self._x_key(float(x_value))
                    if idx < std_arr.size:
                        std_by_x[x_key] = float(std_arr[idx])
                    if idx < sem_arr.size:
                        sem_by_x[x_key] = float(sem_arr[idx])

            unique_x = np.unique(np.concatenate(x_chunks))
            for x_value in unique_x:
                x_float = float(x_value)
                x_key = self._x_key(x_float)
                y_value = float(fit.slope * x_float + fit.intercept)
                std_value = std_by_x.get(x_key, float(np.nan))
                sem_value = sem_by_x.get(x_key, float(np.nan))
                selected_error = (
                    std_value
                    if err_mode == "std"
                    else sem_value
                    if err_mode == "stderr"
                    else float(np.nan)
                )
                delta_percent = self._relative_uncertainty_percent(
                    y_value,
                    selected_error,
                )
                if round_to_sd and err_mode != "off":
                    if err_mode == "std":
                        y_value, std_value = self._round_value_and_error(
                            y_value,
                            std_value,
                        )
                    else:
                        y_value, sem_value = self._round_value_and_error(
                            y_value,
                            sem_value,
                        )
                    if np.isfinite(delta_percent):
                        delta_percent = float(round(delta_percent, 2))
                rows.append(
                    (
                        1,
                        fit.label,
                        int(counts_by_x.get(x_key, 0)),
                        x_float,
                        y_value,
                        std_value,
                        sem_value,
                        delta_percent,
                    )
                )
            return rows

        return rows

    @staticmethod
    def _make_table_item(
        value: str,
        align: Qt.AlignmentFlag,
        sort_value: object,
    ) -> qtw.QTableWidgetItem:
        """Create sortable display item for the analysis table."""
        item = _SortableTableItem(value, sort_value)
        item.setTextAlignment(int(align | Qt.AlignVCenter))
        return item

    def _fill_table(
        self,
        curves: list[_CurveSeries],
        x_mode: str,
        y_mode: str,
        err_mode: str,
        overlay_mode: str,
        fit_series: list[_FitSeries],
        round_to_sd: bool,
    ) -> None:
        """Populate the result table from curve and overlay data."""
        if self._table is None:
            return

        x_header = self._table_x_label_for_mode(x_mode)
        y_header = self._y_label_for_mode(y_mode)
        self._table_x_header = x_header
        self._table_y_header = y_header
        if overlay_mode == "off":
            self._table_base_headers = [
                "Curve #",
                "Curve",
                "N",
                x_header,
                y_header,
            ]
        elif y_mode in {"gain", "gain_last"}:
            self._table_base_headers = [
                "Curve #",
                "Curve",
                "N",
                x_header,
                y_header,
                "Abs Unc",
                "Δ [%]",
            ]
        else:
            self._table_base_headers = [
                "Curve #",
                "Curve",
                "N",
                x_header,
                y_header,
                "Std",
                "Std Err",
                "Δ [%]",
            ]
        self._table.setColumnCount(len(self._table_base_headers))
        if self._table_sort_column >= len(self._table_base_headers):
            self._table_sort_column = -1
            self._table_sort_order = Qt.AscendingOrder
        self._update_table_header_labels()
        self._configure_result_table_columns()
        self._table.setSortingEnabled(False)
        align_gain_last = self._is_gain_last_alignment_enabled(y_mode)

        if overlay_mode == "off":
            rows = sum(len(curve.x_values) for curve in curves)
            self._table.setRowCount(rows)
            row_idx = 0
            for curve in curves:
                curve_y_values = np.asarray(curve.y_values, dtype=np.float64)
                curve_uncertainty_scale = 1.0
                if align_gain_last:
                    curve_y_values, curve_uncertainty_scale, _ = (
                        self._apply_gain_last_alignment(curve_y_values)
                    )
                for idx, x_value in enumerate(curve.x_values):
                    y_value = float(curve_y_values[idx])
                    y_decimals: Optional[int] = None
                    if round_to_sd and err_mode != "off":
                        rounding_error = (
                            float(curve.std_values[idx])
                            if err_mode == "std"
                            else float(curve.sem_values[idx])
                        )
                        rounding_error *= curve_uncertainty_scale
                        y_value, rounded_error = self._round_value_and_error(
                            y_value,
                            rounding_error,
                        )
                        y_decimals = self._rounding_decimals_from_error(
                            rounded_error,
                        )
                    y_text = self._format_float_with_decimals(
                        y_value,
                        y_decimals,
                    )
                    items = [
                        self._make_table_item(
                            str(int(curve.curve_id)),
                            Qt.AlignCenter,
                            int(curve.curve_id),
                        ),
                        self._make_table_item(
                            curve.label,
                            Qt.AlignLeft,
                            curve.label.lower(),
                        ),
                        self._make_table_item(
                            str(int(curve.point_counts[idx])),
                            Qt.AlignCenter,
                            int(curve.point_counts[idx]),
                        ),
                        self._make_table_item(
                            self._format_float(x_value),
                            Qt.AlignCenter,
                            float(x_value),
                        ),
                        self._make_table_item(
                            y_text,
                            Qt.AlignCenter,
                            y_value,
                        ),
                    ]
                    for col_idx, item in enumerate(items):
                        self._table.setItem(row_idx, col_idx, item)
                    row_idx += 1
            self._apply_result_table_sort()
            return

        trend_rows = self._trend_table_rows(
            curves,
            fit_series,
            overlay_mode,
            err_mode,
            False,
        )
        trend_uncertainty_scale = 1.0
        trend_aligned_values: Optional[np.ndarray] = None
        if align_gain_last and trend_rows:
            trend_y_values = np.asarray(
                [float(row[4]) for row in trend_rows],
                dtype=np.float64,
            )
            trend_aligned_values, trend_uncertainty_scale, _ = (
                self._apply_gain_last_alignment(trend_y_values)
            )
        self._table.setRowCount(len(trend_rows))
        for row_idx, row in enumerate(trend_rows):
            (
                curve_id,
                label,
                count,
                x_value,
                y_value,
                std_value,
                sem_value,
                delta_percent,
            ) = row
            if trend_aligned_values is not None and row_idx < trend_aligned_values.size:
                y_value = float(trend_aligned_values[row_idx])
            else:
                y_value = float(y_value)
            std_value = float(std_value) * trend_uncertainty_scale
            sem_value = float(sem_value) * trend_uncertainty_scale
            selected_error = (
                std_value
                if err_mode == "std"
                else sem_value
                if err_mode == "stderr"
                else float(np.nan)
            )
            delta_percent = self._relative_uncertainty_percent(
                y_value,
                selected_error,
            )
            y_decimals = (
                self._rounding_decimals_from_error(selected_error)
                if round_to_sd and err_mode != "off"
                else None
            )
            y_text = self._format_float_with_decimals(y_value, y_decimals)
            abs_unc_text = self._format_float(selected_error)
            std_text = self._format_float(std_value)
            sem_text = self._format_float(sem_value)
            if y_decimals is not None and err_mode in {"std", "stderr"}:
                abs_unc_text = self._format_float_with_decimals(
                    selected_error,
                    y_decimals,
                )
            if y_decimals is not None and err_mode == "std":
                std_text = self._format_float_with_decimals(
                    std_value,
                    y_decimals,
                )
            if y_decimals is not None and err_mode == "stderr":
                sem_text = self._format_float_with_decimals(
                    sem_value,
                    y_decimals,
                )
            delta_text = (
                self._format_float_with_decimals(delta_percent, 2)
                if round_to_sd
                else self._format_float(delta_percent)
            )
            if y_mode in {"gain", "gain_last"}:
                items = [
                    self._make_table_item(
                        str(int(curve_id)),
                        Qt.AlignCenter,
                        int(curve_id),
                    ),
                    self._make_table_item(
                        label,
                        Qt.AlignLeft,
                        label.lower(),
                    ),
                    self._make_table_item(
                        str(int(count)),
                        Qt.AlignCenter,
                        int(count),
                    ),
                    self._make_table_item(
                        self._format_float(x_value),
                        Qt.AlignCenter,
                        float(x_value),
                    ),
                    self._make_table_item(
                        y_text,
                        Qt.AlignCenter,
                        float(y_value),
                    ),
                    self._make_table_item(
                        abs_unc_text,
                        Qt.AlignCenter,
                        float(selected_error),
                    ),
                    self._make_table_item(
                        delta_text,
                        Qt.AlignCenter,
                        float(delta_percent),
                    ),
                ]
            else:
                items = [
                    self._make_table_item(
                        str(int(curve_id)),
                        Qt.AlignCenter,
                        int(curve_id),
                    ),
                    self._make_table_item(
                        label,
                        Qt.AlignLeft,
                        label.lower(),
                    ),
                    self._make_table_item(
                        str(int(count)),
                        Qt.AlignCenter,
                        int(count),
                    ),
                    self._make_table_item(
                        self._format_float(x_value),
                        Qt.AlignCenter,
                        float(x_value),
                    ),
                    self._make_table_item(
                        y_text,
                        Qt.AlignCenter,
                        float(y_value),
                    ),
                    self._make_table_item(
                        std_text,
                        Qt.AlignCenter,
                        float(std_value),
                    ),
                    self._make_table_item(
                        sem_text,
                        Qt.AlignCenter,
                        float(sem_value),
                    ),
                    self._make_table_item(
                        delta_text,
                        Qt.AlignCenter,
                        float(delta_percent),
                    ),
                ]
            for col_idx, item in enumerate(items):
                self._table.setItem(row_idx, col_idx, item)

        self._apply_result_table_sort()

    def _run_analysis(self, _index: int | None = None) -> None:
        """Recompute curves, overlay, table, and plot for current controls."""
        if self._context is None or self._table is None:
            return

        records = list(self._context.records)
        if not records:
            self._set_empty("Load a dataset to run this analysis.")
            return

        x_mode = self._current_data(self._x_axis_combo, "iris")
        y_mode = self._current_data(self._y_axis_combo, "gain")
        err_mode = self._current_data(self._error_bar_combo, "off")
        round_to_sd = (
            self._round_sd_checkbox.isChecked()
            if self._round_sd_checkbox is not None
            else False
        )
        overlay_mode = self._current_data(self._trend_line_combo, "off")
        fit_enabled = overlay_mode != "off"
        if x_mode == "iris" and y_mode in {"gain", "gain_last"}:
            overlay_mode = "mean_x"
            fit_enabled = True
        self._plot_x_mode = x_mode
        self._plot_y_mode = y_mode
        self._plot_hide_raw_series = (
            x_mode == "iris" and y_mode in {"gain", "gain_last"}
        )
        curves = self._build_curves(
            records,
            x_mode,
            y_mode,
            err_mode,
        )
        if not curves:
            self._set_empty(
                "No valid points for selected axes. Check iris/exposure metadata.",
            )
            return

        x_label = self._plot_x_label_for_mode(x_mode)
        y_label = self._y_label_for_mode(y_mode)

        fit_series = self._build_overlay_series(
            curves,
            overlay_mode,
            x_mode,
            y_mode,
            err_mode,
        )
        self._fill_table(
            curves,
            x_mode,
            y_mode,
            err_mode,
            overlay_mode,
            fit_series,
            round_to_sd,
        )
        self._update_plot(
            curves,
            x_label,
            y_label,
            err_mode,
            fit_series,
            fit_enabled,
            overlay_mode,
        )
