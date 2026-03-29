"""Qt model classes for image metrics table."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex

from .datacard_labels import label_for_metadata_field
from .formatting import format_metric_triplet


class MetricsTableModel(QAbstractTableModel):
    """Model backing the metrics table with incremental update support."""

    HEADERS = (
        "#",
        label_for_metadata_field("path"),
        label_for_metadata_field("iris_position"),
        label_for_metadata_field("exposure_ms"),
        "Max Pixel",
        "ROI Max",
        "Min > 0",
        "# Saturated",
        "Average Metric",
        "Std",
        "Std Err",
        "DN/ms",
    )
    SATURATED_ROW_BRUSH = QtGui.QBrush(QtGui.QColor(210, 48, 48, 72))
    LOW_SIGNAL_ROW_BRUSH = QtGui.QBrush(QtGui.QColor(214, 157, 51, 72))

    def __init__(self, parent: Optional[qtw.QWidget] = None) -> None:
        super().__init__(parent)
        self._paths: list[str] = []
        self._iris_positions: Optional[np.ndarray] = None
        self._exposure_ms: Optional[np.ndarray] = None
        self._maxs: Optional[np.ndarray] = None
        self._roi_maxs: Optional[np.ndarray] = None
        self._min_non_zero: Optional[np.ndarray] = None
        self._sat_counts: Optional[np.ndarray] = None
        self._low_signal_flags: Optional[np.ndarray] = None
        self._avg_topk: Optional[np.ndarray] = None
        self._avg_topk_std: Optional[np.ndarray] = None
        self._avg_topk_sem: Optional[np.ndarray] = None
        self._avg_roi: Optional[np.ndarray] = None
        self._avg_roi_std: Optional[np.ndarray] = None
        self._avg_roi_sem: Optional[np.ndarray] = None
        self._dn_per_ms: Optional[np.ndarray] = None
        self._avg_mode = "none"
        self._avg_header = "Average Metric"
        self._std_header = "Std"
        self._sem_header = "Std Err"
        self._dn_per_ms_header = "DN/ms"
        self._rounding_mode = "off"
        self._normalize_intensity = False
        self._normalization_scale = 1.0
        self._sort_column = -1
        self._sort_order = Qt.AscendingOrder
        self._sort_indicator_visible = False

    def _base_header_label(self, section: int) -> Optional[str]:
        """Return section label without sort-indicator decorations."""
        if section == 8:
            return self._avg_header
        if section == 9:
            return self._std_header
        if section == 10:
            return self._sem_header
        if section == 11:
            return self._dn_per_ms_header
        if 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def _header_tooltip(self, section: int) -> Optional[str]:
        """Return concise tooltip text for each header section."""
        tips = {
            0: "Row index. Fixed numbering, unaffected by table sorting.",
            1: "Image path. Long values are left-elided to keep file name visible.",
            2: "Iris position extracted from selected metadata source.",
            3: "Exposure extracted from selected metadata source (milliseconds).",
            4: "Maximum pixel intensity in the image. Normalized when enabled.",
            5: "Maximum intensity inside the applied ROI for this image.",
            6: "Smallest strictly non-zero pixel intensity in the image.",
            7: "Count of pixels above the saturation threshold.",
            8: (
                f"{self._avg_header}. Computed from Top-K pixels or ROI, "
                "depending on average mode."
            ),
            9: f"{self._std_header} associated with the selected average metric.",
            10: f"{self._sem_header} associated with the selected average metric.",
            11: (
                f"{self._dn_per_ms_header}: average intensity divided by "
                "exposure time."
            ),
        }
        return tips.get(section)

    def rowCount(
        self,
        parent: QModelIndex = QModelIndex(),
    ) -> int:  # type: ignore[override]
        """Return number of table rows."""
        if parent.isValid():
            return 0
        return len(self._paths)

    def columnCount(
        self,
        parent: QModelIndex = QModelIndex(),
    ) -> int:  # type: ignore[override]
        """Return number of table columns."""
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ):  # type: ignore[override]
        """Return header labels for horizontal sections."""
        if orientation == Qt.Horizontal:
            label = self._base_header_label(section)
            if label is None:
                return None
            if role == Qt.UserRole:
                return label
            if role == Qt.ToolTipRole:
                return self._header_tooltip(section)
            if role != Qt.DisplayRole:
                return None
            if (
                self._sort_indicator_visible
                and section == self._sort_column
                and section > 0
            ):
                arrow = "▲" if self._sort_order == Qt.AscendingOrder else "▼"
                return f"{label} {arrow}"
            return label
        return None

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.DisplayRole,
    ):  # type: ignore[override]
        """Return table data and alignment roles."""
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        if not (0 <= row < len(self._paths)):
            return None

        if role == Qt.BackgroundRole:
            if (
                self._sat_counts is not None
                and row < len(self._sat_counts)
                and int(self._sat_counts[row]) > 0
            ):
                return self.SATURATED_ROW_BRUSH
            if (
                self._low_signal_flags is not None
                and row < len(self._low_signal_flags)
                and bool(self._low_signal_flags[row])
            ):
                return self.LOW_SIGNAL_ROW_BRUSH
            return None

        if role == Qt.TextAlignmentRole:
            if col == 1:
                return int(Qt.AlignLeft | Qt.AlignVCenter)
            return int(Qt.AlignCenter)

        if role != Qt.DisplayRole:
            return None

        if col == 0:
            return str(row + 1)
        if col == 1:
            return self._paths[row]
        if col == 2:
            if (
                self._iris_positions is None
                or row >= len(self._iris_positions)
            ):
                return "-"
            value = float(self._iris_positions[row])
            return "-" if not np.isfinite(value) else f"{value:g}"
        if col == 3:
            if self._exposure_ms is None or row >= len(self._exposure_ms):
                return "-"
            value = float(self._exposure_ms[row])
            return "-" if not np.isfinite(value) else f"{value:g}"

        if (
            self._maxs is None
            or self._min_non_zero is None
            or self._sat_counts is None
            or row >= len(self._maxs)
            or row >= len(self._min_non_zero)
            or row >= len(self._sat_counts)
        ):
            return "-"

        if col == 4:
            max_value = float(self._maxs[row])
            if self._normalize_intensity and self._normalization_scale > 0.0:
                max_value /= self._normalization_scale
                return f"{max_value:.6g}"
            return str(int(self._maxs[row]))
        if col == 5:
            if self._roi_maxs is None or row >= len(self._roi_maxs):
                return "-"
            roi_max_value = float(self._roi_maxs[row])
            if not np.isfinite(roi_max_value):
                return "-"
            if self._normalize_intensity and self._normalization_scale > 0.0:
                roi_max_value /= self._normalization_scale
            return f"{roi_max_value:.6g}"
        if col == 6:
            return str(int(self._min_non_zero[row]))
        if col == 7:
            return str(int(self._sat_counts[row]))

        mean_value = float("nan")
        std_value = float("nan")
        sem_value = float("nan")
        if self._avg_mode == "topk":
            if self._avg_topk is not None and row < len(self._avg_topk):
                mean_value = float(self._avg_topk[row])
            if (
                self._avg_topk_std is not None
                and row < len(self._avg_topk_std)
            ):
                std_value = float(self._avg_topk_std[row])
            if (
                self._avg_topk_sem is not None
                and row < len(self._avg_topk_sem)
            ):
                sem_value = float(self._avg_topk_sem[row])
        elif self._avg_mode == "roi":
            if self._avg_roi is not None and row < len(self._avg_roi):
                mean_value = float(self._avg_roi[row])
            if self._avg_roi_std is not None and row < len(self._avg_roi_std):
                std_value = float(self._avg_roi_std[row])
            if self._avg_roi_sem is not None and row < len(self._avg_roi_sem):
                sem_value = float(self._avg_roi_sem[row])

        if self._normalize_intensity and self._normalization_scale > 0.0:
            mean_value /= self._normalization_scale
            std_value /= self._normalization_scale
            sem_value /= self._normalization_scale

        if col in (8, 9, 10):
            mean_text, std_text, sem_text = format_metric_triplet(
                mean_value,
                std_value,
                sem_value,
                self._rounding_mode,
            )
            if col == 8:
                return mean_text
            if col == 9:
                return std_text
            return sem_text
        if col == 11:
            if self._dn_per_ms is None or row >= len(self._dn_per_ms):
                return "-"
            dn_per_ms = float(self._dn_per_ms[row])
            if not np.isfinite(dn_per_ms):
                return "-"
            if self._normalize_intensity and self._normalization_scale > 0.0:
                dn_per_ms /= self._normalization_scale
            return f"{dn_per_ms:.6g}"

        return None

    def set_average_header(self, header_text: str) -> None:
        """Set dynamic label for mean-value column."""
        if self._avg_header == header_text:
            return
        self._avg_header = header_text
        self.headerDataChanged.emit(Qt.Horizontal, 8, 8)

    def set_std_header(self, header_text: str) -> None:
        """Set dynamic label for uncertainty column."""
        if self._std_header == header_text:
            return
        self._std_header = header_text
        self.headerDataChanged.emit(Qt.Horizontal, 9, 9)

    def set_sem_header(self, header_text: str) -> None:
        """Set dynamic label for standard-error column."""
        if self._sem_header == header_text:
            return
        self._sem_header = header_text
        self.headerDataChanged.emit(Qt.Horizontal, 10, 10)

    def set_dn_per_ms_header(self, header_text: str) -> None:
        """Set dynamic label for DN-per-millisecond column."""
        if self._dn_per_ms_header == header_text:
            return
        self._dn_per_ms_header = header_text
        self.headerDataChanged.emit(Qt.Horizontal, 11, 11)

    def set_sort_indicator(
        self,
        column: int,
        order: Qt.SortOrder,
        visible: bool,
    ) -> None:
        """Store sort state to render theme-friendly header arrows."""
        changed = (
            self._sort_column != column
            or self._sort_order != order
            or self._sort_indicator_visible != visible
        )
        if not changed:
            return
        self._sort_column = column
        self._sort_order = order
        self._sort_indicator_visible = visible
        self.headerDataChanged.emit(Qt.Horizontal, 0, len(self.HEADERS) - 1)

    def set_intensity_normalization(
        self,
        enabled: bool,
        scale: float,
    ) -> None:
        """Configure optional normalization for intensity metric columns."""
        norm_enabled = bool(enabled)
        norm_scale = scale if scale > 0.0 else 1.0
        changed = (
            self._normalize_intensity != norm_enabled
            or not np.isclose(
                self._normalization_scale,
                norm_scale,
                rtol=0.0,
                atol=1e-12,
            )
        )
        if not changed:
            return
        self._normalize_intensity = norm_enabled
        self._normalization_scale = norm_scale
        if not self._paths:
            return
        top_left = self.index(0, 4)
        bottom_right = self.index(len(self._paths) - 1, 11)
        self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])

    def set_rounding_mode(self, mode: str) -> None:
        """Set rounding mode for mean/std/stderr display columns."""
        normalized = mode if mode in {"off", "std", "stderr"} else "off"
        if self._rounding_mode == normalized:
            return
        self._rounding_mode = normalized
        if not self._paths:
            return
        top_left = self.index(0, 8)
        bottom_right = self.index(len(self._paths) - 1, 11)
        self.dataChanged.emit(
            top_left,
            bottom_right,
            [Qt.DisplayRole],
        )

    def clear(self) -> None:
        """Clear model content and restore default headers/mode."""
        if not self._paths:
            self._avg_mode = "none"
            self._iris_positions = None
            self._exposure_ms = None
            self._maxs = None
            self._roi_maxs = None
            self._min_non_zero = None
            self._sat_counts = None
            self._avg_topk = None
            self._avg_topk_std = None
            self._avg_topk_sem = None
            self._low_signal_flags = None
            self._avg_roi = None
            self._avg_roi_std = None
            self._avg_roi_sem = None
            self._dn_per_ms = None
            self.set_average_header("Average Metric")
            self.set_std_header("Std")
            self.set_sem_header("Std Err")
            self.set_dn_per_ms_header("DN/ms")
            return

        self.beginResetModel()
        self._paths = []
        self._iris_positions = None
        self._exposure_ms = None
        self._maxs = None
        self._roi_maxs = None
        self._min_non_zero = None
        self._sat_counts = None
        self._low_signal_flags = None
        self._avg_topk = None
        self._avg_topk_std = None
        self._avg_topk_sem = None
        self._avg_roi = None
        self._avg_roi_std = None
        self._avg_roi_sem = None
        self._dn_per_ms = None
        self._avg_mode = "none"
        self._avg_header = "Average Metric"
        self._std_header = "Std"
        self._sem_header = "Std Err"
        self._dn_per_ms_header = "DN/ms"
        self.endResetModel()

    @staticmethod
    def _diff_mask_int(
        previous: Optional[np.ndarray],
        current: Optional[np.ndarray],
        n_rows: int,
    ) -> np.ndarray:
        if n_rows <= 0:
            return np.zeros(0, dtype=bool)
        if previous is None or current is None:
            return np.ones(n_rows, dtype=bool)
        if len(previous) != n_rows or len(current) != n_rows:
            return np.ones(n_rows, dtype=bool)
        return np.asarray(previous, dtype=np.int64) != np.asarray(
            current,
            dtype=np.int64,
        )

    @staticmethod
    def _diff_mask_float(
        previous: Optional[np.ndarray],
        current: Optional[np.ndarray],
        n_rows: int,
    ) -> np.ndarray:
        if n_rows <= 0:
            return np.zeros(0, dtype=bool)
        if previous is None or current is None:
            return np.ones(n_rows, dtype=bool)
        if len(previous) != n_rows or len(current) != n_rows:
            return np.ones(n_rows, dtype=bool)
        prev_arr = np.asarray(previous, dtype=np.float64)
        curr_arr = np.asarray(current, dtype=np.float64)
        return ~np.isclose(
            prev_arr,
            curr_arr,
            rtol=0.0,
            atol=1e-12,
            equal_nan=True,
        )

    def _emit_changes_for_mask(
        self,
        column: int,
        mask: np.ndarray,
        *,
        roles: Optional[list[int]] = None,
    ) -> None:
        if mask.size == 0 or not np.any(mask):
            return

        emit_roles = roles or [Qt.DisplayRole]
        start = -1
        for row, changed in enumerate(mask):
            if changed and start < 0:
                start = row
            elif not changed and start >= 0:
                self.dataChanged.emit(
                    self.index(start, column),
                    self.index(row - 1, column),
                    emit_roles,
                )
                start = -1
        if start >= 0:
            self.dataChanged.emit(
                self.index(start, column),
                self.index(len(mask) - 1, column),
                emit_roles,
            )

    def _emit_row_role_changes_for_mask(
        self,
        mask: np.ndarray,
        roles: list[int],
    ) -> None:
        """Emit dataChanged for full-row role updates on contiguous ranges."""
        if mask.size == 0 or not np.any(mask):
            return

        start = -1
        last_col = len(self.HEADERS) - 1
        for row, changed in enumerate(mask):
            if changed and start < 0:
                start = row
            elif not changed and start >= 0:
                self.dataChanged.emit(
                    self.index(start, 0),
                    self.index(row - 1, last_col),
                    roles,
                )
                start = -1
        if start >= 0:
            self.dataChanged.emit(
                self.index(start, 0),
                self.index(len(mask) - 1, last_col),
                roles,
            )

    def update_metrics(
        self,
        *,
        paths: list[str],
        iris_positions: np.ndarray,
        exposure_ms: np.ndarray,
        maxs: np.ndarray,
        roi_maxs: Optional[np.ndarray],
        min_non_zero: np.ndarray,
        sat_counts: np.ndarray,
        low_signal_flags: Optional[np.ndarray],
        avg_mode: str,
        avg_topk: Optional[np.ndarray],
        avg_topk_std: Optional[np.ndarray],
        avg_topk_sem: Optional[np.ndarray],
        avg_roi: Optional[np.ndarray],
        avg_roi_std: Optional[np.ndarray],
        avg_roi_sem: Optional[np.ndarray],
        dn_per_ms: Optional[np.ndarray],
    ) -> str:
        """Update metric arrays and emit minimal `dataChanged` ranges.

        Parameters
        ----------
        paths : list[str]
            Ordered list of image paths.
        iris_positions : numpy.ndarray
            Per-image iris-position metadata values.
        exposure_ms : numpy.ndarray
            Per-image exposure values in milliseconds.
        maxs : numpy.ndarray
            Per-image max intensity values.
        roi_maxs : numpy.ndarray or None
            Per-image maximum intensity values within the applied ROI.
        min_non_zero : numpy.ndarray
            Per-image minimum non-zero values.
        sat_counts : numpy.ndarray
            Per-image saturated pixel counts.
        low_signal_flags : numpy.ndarray or None
            Per-image low-signal flags based on the applied low threshold.
        avg_mode : str
            Active averaging mode (``"none"``, ``"topk"``, ``"roi"``).
        avg_topk : numpy.ndarray or None
            Top-k mean values.
        avg_topk_std : numpy.ndarray or None
            Top-k standard deviations.
        avg_topk_sem : numpy.ndarray or None
            Top-k standard errors.
        avg_roi : numpy.ndarray or None
            ROI mean values.
        avg_roi_std : numpy.ndarray or None
            ROI standard deviations.
        avg_roi_sem : numpy.ndarray or None
            ROI standard errors.
        dn_per_ms : numpy.ndarray or None
            Per-image DN-per-millisecond values from active averaging metric.

        Returns
        -------
        str
            One of ``"reset"`` or ``"updated"``.
        """
        row_changed = len(paths) != len(self._paths)
        path_changed = not row_changed and self._paths != paths
        if row_changed or path_changed:
            self.beginResetModel()
            self._paths = paths
            self._iris_positions = iris_positions
            self._exposure_ms = exposure_ms
            self._maxs = maxs
            self._roi_maxs = roi_maxs
            self._min_non_zero = min_non_zero
            self._sat_counts = sat_counts
            self._low_signal_flags = low_signal_flags
            self._avg_mode = avg_mode
            self._avg_topk = avg_topk
            self._avg_topk_std = avg_topk_std
            self._avg_topk_sem = avg_topk_sem
            self._avg_roi = avg_roi
            self._avg_roi_std = avg_roi_std
            self._avg_roi_sem = avg_roi_sem
            self._dn_per_ms = dn_per_ms
            self.endResetModel()
            return "reset"

        old_count = len(self._paths)

        old_iris_positions = self._iris_positions
        old_exposure_ms = self._exposure_ms
        old_maxs = self._maxs
        old_roi_maxs = self._roi_maxs
        old_min_non_zero = self._min_non_zero
        old_sat_counts = self._sat_counts
        old_low_signal_flags = self._low_signal_flags
        old_avg_mode = self._avg_mode
        old_avg_topk = self._avg_topk
        old_avg_topk_std = self._avg_topk_std
        old_avg_topk_sem = self._avg_topk_sem
        old_avg_roi = self._avg_roi
        old_avg_roi_std = self._avg_roi_std
        old_avg_roi_sem = self._avg_roi_sem
        old_dn_per_ms = self._dn_per_ms

        self._paths = paths
        self._iris_positions = iris_positions
        self._exposure_ms = exposure_ms
        self._maxs = maxs
        self._roi_maxs = roi_maxs
        self._min_non_zero = min_non_zero
        self._sat_counts = sat_counts
        self._low_signal_flags = low_signal_flags
        self._avg_mode = avg_mode
        self._avg_topk = avg_topk
        self._avg_topk_std = avg_topk_std
        self._avg_topk_sem = avg_topk_sem
        self._avg_roi = avg_roi
        self._avg_roi_std = avg_roi_std
        self._avg_roi_sem = avg_roi_sem
        self._dn_per_ms = dn_per_ms

        n_rows = len(self._paths)
        if n_rows == 0:
            return "updated"

        self._emit_changes_for_mask(
            2,
            self._diff_mask_float(
                old_iris_positions,
                self._iris_positions,
                n_rows,
            ),
        )
        self._emit_changes_for_mask(
            3,
            self._diff_mask_float(
                old_exposure_ms,
                self._exposure_ms,
                n_rows,
            ),
        )
        self._emit_changes_for_mask(
            4,
            self._diff_mask_int(old_maxs, self._maxs, n_rows),
        )
        self._emit_changes_for_mask(
            5,
            self._diff_mask_float(old_roi_maxs, self._roi_maxs, n_rows),
        )
        self._emit_changes_for_mask(
            6,
            self._diff_mask_int(old_min_non_zero, self._min_non_zero, n_rows),
        )
        sat_mask = self._diff_mask_int(
            old_sat_counts,
            self._sat_counts,
            n_rows,
        )
        if old_low_signal_flags is None and self._low_signal_flags is None:
            low_signal_mask = np.zeros(n_rows, dtype=bool)
        else:
            low_signal_mask = self._diff_mask_int(
                old_low_signal_flags,
                self._low_signal_flags,
                n_rows,
            )
        self._emit_changes_for_mask(7, sat_mask, roles=[Qt.DisplayRole])
        self._emit_row_role_changes_for_mask(
            sat_mask | low_signal_mask,
            [Qt.BackgroundRole],
        )

        if old_avg_mode != self._avg_mode:
            mean_mask = np.ones(n_rows, dtype=bool)
            std_mask = np.ones(n_rows, dtype=bool)
            sem_mask = np.ones(n_rows, dtype=bool)
        elif self._avg_mode == "topk":
            mean_mask = self._diff_mask_float(
                old_avg_topk,
                self._avg_topk,
                n_rows,
            )
            std_mask = self._diff_mask_float(
                old_avg_topk_std,
                self._avg_topk_std,
                n_rows,
            )
            sem_mask = self._diff_mask_float(
                old_avg_topk_sem,
                self._avg_topk_sem,
                n_rows,
            )
        elif self._avg_mode == "roi":
            mean_mask = self._diff_mask_float(
                old_avg_roi,
                self._avg_roi,
                n_rows,
            )
            std_mask = self._diff_mask_float(
                old_avg_roi_std,
                self._avg_roi_std,
                n_rows,
            )
            sem_mask = self._diff_mask_float(
                old_avg_roi_sem,
                self._avg_roi_sem,
                n_rows,
            )
        else:
            mean_mask = np.zeros(n_rows, dtype=bool)
            std_mask = np.zeros(n_rows, dtype=bool)
            sem_mask = np.zeros(n_rows, dtype=bool)

        self._emit_changes_for_mask(8, mean_mask)
        self._emit_changes_for_mask(9, std_mask)
        self._emit_changes_for_mask(10, sem_mask)
        self._emit_changes_for_mask(
            11,
            self._diff_mask_float(old_dn_per_ms, self._dn_per_ms, n_rows),
        )
        return "updated"


class MetricsSortProxyModel(QtCore.QSortFilterProxyModel):
    """Proxy model that provides tri-state sorting and custom comparisons."""

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        """Return display/alignment roles, overriding row-number column."""
        if index.isValid() and index.column() == 0:
            if role == Qt.DisplayRole:
                return str(index.row() + 1)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter)
        return super().data(index, role)

    @staticmethod
    def _numeric_value(value: object) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip()
        if text in {"", "-"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # type: ignore[override]
        """Compare rows for sorting by column-specific rules."""
        source = self.sourceModel()
        if source is None:
            return super().lessThan(left, right)

        column = left.column()
        left_value = source.data(left, Qt.DisplayRole)
        right_value = source.data(right, Qt.DisplayRole)

        if column == 1:
            left_text = Path(str(left_value or "")).name.lower()
            right_text = Path(str(right_value or "")).name.lower()
            if left_text == right_text:
                return str(left_value or "").lower() < str(right_value or "").lower()
            return left_text < right_text

        if column in {2, 3, 4, 5, 6, 7, 8, 9, 10, 11}:
            left_num = self._numeric_value(left_value)
            right_num = self._numeric_value(right_value)
            if left_num is None and right_num is None:
                return str(left_value or "") < str(right_value or "")
            if left_num is None:
                return False
            if right_num is None:
                return True
            return left_num < right_num

        return super().lessThan(left, right)
