"""Event signature analysis plugin."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import QSignalBlocker, Qt

from ....mpl_canvas import FigureCanvasQTAgg
from ....mpl_config import ensure_matplotlib_config_dir
from .._base import (
    AnalysisContext,
    AnalysisPlugin,
    AnalysisPreparationJob,
    AnalysisRecord,
)
from .._registry import register_analysis_plugin

ensure_matplotlib_config_dir()

try:
    from matplotlib.figure import Figure

    MATPLOTLIB_AVAILABLE = FigureCanvasQTAgg is not None
except Exception:
    Figure = None  # type: ignore[assignment]
    MATPLOTLIB_AVAILABLE = False


class _SortableItem(qtw.QTableWidgetItem):
    """Table item with numeric sort support."""

    def __init__(self, text: str, sort_value: object) -> None:
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, qtw.QTableWidgetItem):
            return super().__lt__(other)
        left = getattr(self, "sort_value", None)
        right = getattr(other, "sort_value", None)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            left_float = float(left)
            right_float = float(right)
            left_finite = np.isfinite(left_float)
            right_finite = np.isfinite(right_float)
            if left_finite and right_finite:
                return left_float < right_float
            if left_finite:
                return True
            if right_finite:
                return False
        if left is not None and right is not None:
            return str(left).lower() < str(right).lower()
        return super().__lt__(other)


@dataclass(frozen=True, slots=True)
class _PreparedEventRecord:
    """Plugin-ready row data independent of presentation controls."""

    ordinal: int
    image_name: str
    frame_index: float
    elapsed_time: float | None
    max_pixel: float | None
    roi_topk_mean: float | None


@dataclass(frozen=True, slots=True)
class _PreparedEventSignature:
    """Prepared Event Signature data keyed by scientific inputs."""

    data_signature: str
    records: tuple[_PreparedEventRecord, ...]


def _signature_payload(value: object) -> object:
    """Return a JSON-stable representation for Event Signature cache keys."""

    if isinstance(value, dict):
        return {
            str(key): _signature_payload(payload)
            for key, payload in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_signature_payload(item) for item in value]
    if isinstance(value, np.generic):
        return _signature_payload(value.item())
    if isinstance(value, float):
        if math.isnan(value):
            return {"__float__": "nan"}
        if math.isinf(value):
            return {"__float__": "inf" if value > 0 else "-inf"}
        return float(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _stable_signature(payload: object) -> str:
    """Return one stable cache signature for Event Signature inputs."""

    serialized = json.dumps(
        _signature_payload(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.blake2b(serialized.encode("utf-8"), digest_size=16).hexdigest()


@register_analysis_plugin
class EventSignatureAnalysisPlugin(AnalysisPlugin):
    """Plot per-frame intensity signatures for event-like acquisitions."""

    plugin_id = "event_signature"
    display_name = "Event Signature"
    dependencies: tuple[str, ...] = ()
    required_metric_families = ("static_scan",)
    optional_metric_families = ("roi_topk",)
    run_action_label = "Build Signature"
    description = (
        "Plot max-pixel or ROI Top-K values against frame index or elapsed time."
    )

    _X_AXIS_OPTIONS = (
        ("Frame Index", "frame_index"),
        ("elapsed time [s]", "elapsed_time_s"),
    )
    _Y_AXIS_OPTIONS = (
        ("Max Pixel", "max_pixel"),
        ("ROI Top-K", "roi_topk_mean"),
    )
    _X_LABELS = {
        "frame_index": "Frame Index",
        "elapsed_time_s": "elapsed time [s]",
    }
    _Y_LABELS = {
        "max_pixel": "Max Pixel",
        "roi_topk_mean": "ROI Top-K",
    }

    def __init__(self) -> None:
        self._context: Optional[AnalysisContext] = None
        self._root: Optional[qtw.QWidget] = None
        self._controls_panel: Optional[qtw.QWidget] = None
        self._workspace_widget: Optional[qtw.QWidget] = None
        self._x_axis_combo: Optional[qtw.QComboBox] = None
        self._y_axis_combo: Optional[qtw.QComboBox] = None
        self._table: Optional[qtw.QTableWidget] = None
        self._figure = None
        self._axes = None
        self._canvas = None
        self._fallback_plot_label: Optional[qtw.QLabel] = None
        self._theme_mode = "dark"
        self._plot_points: list[tuple[float, float]] = []
        self._prepared_cache: dict[str, _PreparedEventSignature] = {}
        self._prepared_records: tuple[_PreparedEventRecord, ...] = ()
        self._prepared_data_signature: str | None = None
        self._last_presentation_signature: tuple[str, str, int, int] | None = None
        self._analysis_dirty = True

    def create_widget(self, parent: qtw.QWidget) -> qtw.QWidget:
        """Create a compact fallback widget for legacy host layouts."""

        root = qtw.QWidget(parent)
        self._root = root
        layout = qtw.QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        controls = self.create_controls_widget(root)
        workspace = self.create_workspace_widget(root)
        if controls is not None:
            layout.addWidget(controls, 0)
        if workspace is not None:
            layout.addWidget(workspace, 1)
        return root

    def create_controls_widget(
        self,
        parent: qtw.QWidget,
    ) -> qtw.QWidget | None:
        """Create plugin controls for host side-rail layouts."""

        panel = qtw.QFrame(parent)
        self._controls_panel = panel
        panel.setObjectName("SubtlePanel")
        panel.setSizePolicy(qtw.QSizePolicy.Preferred, qtw.QSizePolicy.Expanding)
        layout = qtw.QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        form = qtw.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self._x_axis_combo = qtw.QComboBox(panel)
        for label, key in self._X_AXIS_OPTIONS:
            self._x_axis_combo.addItem(label, key)
        self._x_axis_combo.setToolTip("Select the independent variable.")
        form.addRow(self._label("X Axis"), self._x_axis_combo)

        self._y_axis_combo = qtw.QComboBox(panel)
        for label, key in self._Y_AXIS_OPTIONS:
            self._y_axis_combo.addItem(label, key)
        self._y_axis_combo.setToolTip("Select the intensity metric.")
        form.addRow(self._label("Y Axis"), self._y_axis_combo)

        layout.addLayout(form)
        layout.addStretch(1)

        self._x_axis_combo.currentIndexChanged.connect(self._on_controls_changed)
        self._y_axis_combo.currentIndexChanged.connect(self._on_controls_changed)
        self._sync_x_axis_options()
        return panel

    def create_workspace_widget(
        self,
        parent: qtw.QWidget,
    ) -> qtw.QWidget | None:
        """Create plugin workspace with result table and plot."""

        workspace = qtw.QWidget(parent)
        self._workspace_widget = workspace
        layout = qtw.QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = qtw.QSplitter(Qt.Horizontal, workspace)
        splitter.setChildrenCollapsible(False)

        self._table = qtw.QTableWidget(0, 5, splitter)
        self._table.setHorizontalHeaderLabels(
            ["#", "Image", "Frame Index", "elapsed time [s]", "Value"],
        )
        self._table.setEditTriggers(qtw.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(qtw.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, qtw.QHeaderView.Stretch)
        header.setSectionResizeMode(2, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, qtw.QHeaderView.ResizeToContents)
        splitter.addWidget(self._table)

        plot_panel = qtw.QWidget(splitter)
        plot_panel.setObjectName("ImagePanel")
        plot_layout = qtw.QVBoxLayout(plot_panel)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)
        if MATPLOTLIB_AVAILABLE:
            self._figure = Figure(figsize=(6.5, 4.0), dpi=100)
            self._axes = self._figure.add_subplot(111)
            self._canvas = FigureCanvasQTAgg(self._figure)
            plot_layout.addWidget(self._canvas, 1)
        else:
            self._fallback_plot_label = qtw.QLabel(
                "matplotlib is not installed.\nInstall it to display plots.",
                plot_panel,
            )
            self._fallback_plot_label.setObjectName("MutedLabel")
            self._fallback_plot_label.setAlignment(Qt.AlignCenter)
            self._fallback_plot_label.setWordWrap(True)
            plot_layout.addWidget(self._fallback_plot_label, 1)
        splitter.addWidget(plot_panel)
        splitter.setSizes([420, 720])
        layout.addWidget(splitter, 1)

        self._refresh()
        return workspace

    def on_context_changed(self, context: AnalysisContext) -> None:
        """Store host context without running plugin analysis."""

        self._context = context
        self._sync_x_axis_options()
        self._analysis_dirty = True

    def run_analysis(self, context: AnalysisContext) -> None:
        """Build the explicit event-signature table and plot."""

        self._context = context
        self._sync_x_axis_options()
        data_signature = self._event_signature_data_signature(context)
        prepared = self._prepared_cache.get(data_signature)
        if prepared is None:
            prepared = self._prepare_from_snapshot(
                data_signature,
                self._snapshot_context_records(context),
            )
            self._prepared_cache[data_signature] = prepared
        self._use_prepared_signature(prepared)
        self._refresh()
        self._analysis_dirty = False

    def prepare_analysis(
        self,
        context: AnalysisContext,
    ) -> AnalysisPreparationJob | None:
        """Return background preparation when plugin-ready data is not cached."""

        self._context = context
        self._sync_x_axis_options()
        data_signature = self._event_signature_data_signature(context)
        if data_signature in self._prepared_cache:
            return None
        snapshot = self._snapshot_context_records(context)
        return AnalysisPreparationJob(
            label="Preparing Event Signature",
            prepare=lambda: self._prepare_from_snapshot(data_signature, snapshot),
        )

    def apply_prepared_analysis(self, prepared: object) -> None:
        """Apply prepared Event Signature records on the UI thread."""

        if not isinstance(prepared, _PreparedEventSignature):
            raise TypeError("Unexpected Event Signature preparation result.")
        self._prepared_cache[prepared.data_signature] = prepared
        self._use_prepared_signature(prepared)
        self._refresh()
        self._analysis_dirty = False

    def set_theme(self, mode: str) -> None:
        """Update plot colors for the host theme."""

        self._theme_mode = str(mode or "dark")
        self._draw_plot()

    @staticmethod
    def _label(text: str) -> qtw.QLabel:
        label = qtw.QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    @staticmethod
    def _finite_float(value: object) -> float | None:
        try:
            number = float(value)
        except Exception:
            return None
        if not np.isfinite(number):
            return None
        return float(number)

    @staticmethod
    def _frame_index_for_record(record: AnalysisRecord, fallback: int) -> float:
        value = EventSignatureAnalysisPlugin._finite_float(
            record.metadata.get("frame_index"),
        )
        return float(fallback if value is None else value)

    def _has_elapsed_time(self) -> bool:
        context = self._context
        if context is None:
            return False
        return any(
            self._finite_float(record.metadata.get("elapsed_time_s")) is not None
            for record in context.records
        )

    def _current_data(self, combo: qtw.QComboBox | None, fallback: str) -> str:
        if combo is None:
            return fallback
        value = combo.currentData()
        return fallback if value is None else str(value)

    def _sync_x_axis_options(self) -> None:
        if self._x_axis_combo is None:
            return
        has_elapsed = self._has_elapsed_time()
        current_key = self._current_data(self._x_axis_combo, "frame_index")
        allowed = (
            self._X_AXIS_OPTIONS
            if has_elapsed
            else (("Frame Index", "frame_index"),)
        )
        existing = tuple(
            (
                self._x_axis_combo.itemText(index),
                str(self._x_axis_combo.itemData(index)),
            )
            for index in range(self._x_axis_combo.count())
        )
        if existing != allowed:
            blocker = QSignalBlocker(self._x_axis_combo)
            self._x_axis_combo.clear()
            for label, key in allowed:
                self._x_axis_combo.addItem(label, key)
            del blocker
        if current_key == "elapsed_time_s" and not has_elapsed:
            current_key = "frame_index"
        index = self._x_axis_combo.findData(current_key)
        if index < 0:
            index = 0
        if self._x_axis_combo.currentIndex() != index:
            blocker = QSignalBlocker(self._x_axis_combo)
            self._x_axis_combo.setCurrentIndex(index)
            del blocker

    def _on_controls_changed(self, _index: int | None = None) -> None:
        self._sync_x_axis_options()
        self._analysis_dirty = True

    @classmethod
    def _snapshot_context_records(
        cls,
        context: AnalysisContext,
    ) -> tuple[tuple[int, str, float, float | None, float | None, float | None], ...]:
        """Return immutable consumed fields from the analysis context."""

        rows: list[tuple[int, str, float, float | None, float | None, float | None]] = []
        for row, record in enumerate(context.records):
            frame_index = cls._frame_index_for_record(record, row)
            rows.append(
                (
                    row + 1,
                    Path(record.path).name,
                    frame_index,
                    cls._finite_float(record.metadata.get("elapsed_time_s")),
                    cls._finite_float(record.metadata.get("max_pixel")),
                    cls._finite_float(record.metadata.get("roi_topk_mean")),
                ),
            )
        return tuple(rows)

    @classmethod
    def _event_signature_data_signature(cls, context: AnalysisContext) -> str:
        """Return a signature for only the data consumed by this plugin."""

        statuses = {
            family: {
                "state": context.metric_family_status(family).state,
                "message": context.metric_family_status(family).message,
            }
            for family in ("static_scan", "roi_topk")
        }
        return _stable_signature(
            {
                "records": cls._snapshot_context_records(context),
                "metric_family_statuses": statuses,
            },
        )

    @staticmethod
    def _prepare_from_snapshot(
        data_signature: str,
        snapshot: tuple[
            tuple[int, str, float, float | None, float | None, float | None],
            ...,
        ],
    ) -> _PreparedEventSignature:
        """Build plugin-ready records from an immutable context snapshot."""

        records = tuple(
            _PreparedEventRecord(
                ordinal=ordinal,
                image_name=image_name,
                frame_index=frame_index,
                elapsed_time=elapsed_time,
                max_pixel=max_pixel,
                roi_topk_mean=roi_topk_mean,
            )
            for (
                ordinal,
                image_name,
                frame_index,
                elapsed_time,
                max_pixel,
                roi_topk_mean,
            ) in snapshot
        )
        return _PreparedEventSignature(
            data_signature=data_signature,
            records=records,
        )

    def _use_prepared_signature(self, prepared: _PreparedEventSignature) -> None:
        """Install prepared records for the next projection refresh."""

        self._prepared_records = prepared.records
        self._prepared_data_signature = prepared.data_signature

    def _x_value_for_record(
        self,
        record: _PreparedEventRecord,
        x_mode: str,
    ) -> float | None:
        if x_mode == "elapsed_time_s":
            return record.elapsed_time
        return record.frame_index

    def _y_value_for_record(
        self,
        record: _PreparedEventRecord,
        y_mode: str,
    ) -> float | None:
        if y_mode == "roi_topk_mean":
            return record.roi_topk_mean
        return record.max_pixel

    @staticmethod
    def _format_value(value: float | None, *, precision: int = 6) -> str:
        if value is None or not np.isfinite(value):
            return "-"
        return f"{float(value):.{precision}g}"

    def _build_rows(self) -> list[tuple[int, str, float, float | None, float, float]]:
        if not self._prepared_records:
            return []
        x_mode = self._current_data(self._x_axis_combo, "frame_index")
        y_mode = self._current_data(self._y_axis_combo, "max_pixel")
        rows: list[tuple[int, str, float, float | None, float, float]] = []
        for record in self._prepared_records:
            x_value = self._x_value_for_record(record, x_mode)
            y_value = self._y_value_for_record(record, y_mode)
            if x_value is None or y_value is None:
                continue
            rows.append(
                (
                    record.ordinal,
                    record.image_name,
                    record.frame_index,
                    record.elapsed_time,
                    x_value,
                    y_value,
                ),
            )
        return rows

    def _refresh(self) -> None:
        self._last_presentation_signature = self._presentation_signature()
        rows = self._build_rows()
        self._plot_points = [(row[4], row[5]) for row in rows]
        self._populate_table(rows)
        self._draw_plot()

    def _presentation_signature(self) -> tuple[str, str, int, int]:
        """Return the current presentation-only signature."""

        if self._last_presentation_signature is None:
            return (
                self._current_data(self._x_axis_combo, "frame_index"),
                self._current_data(self._y_axis_combo, "max_pixel"),
                0,
                int(Qt.AscendingOrder.value),
            )
        sort_column = 0
        sort_order = int(Qt.AscendingOrder.value)
        if self._table is not None:
            header = self._table.horizontalHeader()
            sort_column = int(header.sortIndicatorSection())
            if sort_column < 0:
                sort_column = 0
            sort_order = int(header.sortIndicatorOrder().value)
        return (
            self._current_data(self._x_axis_combo, "frame_index"),
            self._current_data(self._y_axis_combo, "max_pixel"),
            sort_column,
            sort_order,
        )

    def _populate_table(
        self,
        rows: list[tuple[int, str, float, float | None, float, float]],
    ) -> None:
        if self._table is None:
            return
        table = self._table
        sort_column = 0
        sort_order = Qt.AscendingOrder
        if self._last_presentation_signature is not None:
            sort_column = self._last_presentation_signature[2]
            sort_order = Qt.SortOrder(self._last_presentation_signature[3])
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for row_idx, (ordinal, image_name, frame_index, elapsed_time, _x, y) in enumerate(rows):
            values = [
                (str(ordinal), ordinal),
                (image_name, image_name),
                (self._format_value(frame_index), frame_index),
                (self._format_value(elapsed_time, precision=9), elapsed_time),
                (self._format_value(y), y),
            ]
            for col_idx, (text, sort_value) in enumerate(values):
                item = _SortableItem(text, sort_value)
                item.setTextAlignment(
                    (Qt.AlignLeft if col_idx == 1 else Qt.AlignCenter)
                    | Qt.AlignVCenter,
                )
                table.setItem(row_idx, col_idx, item)
        table.setSortingEnabled(True)
        table.sortByColumn(sort_column, sort_order)

    def _draw_plot(self) -> None:
        if self._figure is None or self._axes is None or self._canvas is None:
            return
        x_label = self._X_LABELS.get(
            self._current_data(self._x_axis_combo, "frame_index"),
            "X",
        )
        y_label = self._Y_LABELS.get(
            self._current_data(self._y_axis_combo, "max_pixel"),
            "Y",
        )
        dark = self._theme_mode == "dark"
        face = "#151a20" if dark else "#ffffff"
        axes_face = "#1f2630" if dark else "#ffffff"
        text = "#e8edf2" if dark else "#1f2328"
        grid = "#3a4654" if dark else "#d8dee6"
        line = "#57b8ff" if dark else "#006eb8"
        self._figure.patch.set_facecolor(face)
        ax = self._axes
        ax.clear()
        ax.set_facecolor(axes_face)
        ax.tick_params(colors=text)
        for spine in ax.spines.values():
            spine.set_color(grid)
        ax.set_xlabel(x_label, color=text)
        ax.set_ylabel(y_label, color=text)
        ax.grid(True, color=grid, alpha=0.55, linewidth=0.8)

        if not self._plot_points:
            ax.text(
                0.5,
                0.5,
                "No plot data",
                color=text,
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
        else:
            points = np.asarray(self._plot_points, dtype=np.float64)
            ax.plot(
                points[:, 0],
                points[:, 1],
                lw=1.4,
                c=line,
            )
            if points.shape[0] == 1:
                x = float(points[0, 0])
                y = float(points[0, 1])
                ax.set_xlim(x - 0.5, x + 0.5)
                ax.set_ylim(y - 0.5, y + 0.5)
            else:
                ax.margins(x=0.04, y=0.08)

        self._figure.tight_layout(pad=1.0)
        self._canvas.draw_idle()
