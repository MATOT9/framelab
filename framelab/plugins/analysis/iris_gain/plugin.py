"""Gain-vs-iris analysis profile plugin."""

from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

from .._base import AnalysisContext, AnalysisPlugin
from .._registry import register_analysis_plugin
from ...registry import PluginUiCapabilities
from ._analysis import IrisGainAnalysisMixin
from ._plotting import IrisGainPlotMixin
from ._shared import _CurveSeries, _FitHoverItem, _FitSeries, _ResultTableWidget
from ._ui import IrisGainUiMixin


@register_analysis_plugin
class IrisGainAnalysisPlugin(
    IrisGainUiMixin,
    IrisGainPlotMixin,
    IrisGainAnalysisMixin,
    AnalysisPlugin,
):
    """Scatter/curve analysis for iris and exposure trends."""

    plugin_id = "iris_gain_vs_exposure"
    display_name = "Intensity Trend Explorer"
    dependencies: tuple[str, ...] = ()
    ui_capabilities = PluginUiCapabilities(
        reveal_data_columns=(
            "iris_pos",
            "exposure_ms",
            "exposure_source",
            "group",
        ),
        reveal_measure_columns=("iris_pos", "exposure_ms"),
        show_metadata_controls=True,
        metadata_group_fields=("iris_position", "exposure_ms"),
    )
    description = (
        "Explore intensity trends versus iris position or exposure with "
        "uncertainty-aware overlays."
    )
    _Y_AXIS_OPTIONS: tuple[tuple[str, str], ...] = (
        ("Intensity Gain (first ref)", "gain"),
        ("Intensity Gain (last ref)", "gain_last"),
        ("Mean Intensity", "mean"),
        ("Intensity Rate", "dn_per_ms"),
        ("Peak Intensity", "max_pixel"),
    )
    _PLOT_X_LABELS = {
        "iris": "Iris Position",
        "exposure": "Exposure [ms]",
    }
    _TABLE_X_LABELS = {
        "iris": "Iris Pos",
        "exposure": "Exposure",
    }
    _Y_LABELS = {
        "gain": "Intensity Gain",
        "gain_last": "Intensity Gain (last ref)",
        "mean": "Mean Intensity",
        "dn_per_ms": "Intensity Rate",
        "max_pixel": "Peak Intensity",
    }

    def __init__(self) -> None:
        self._context: Optional[AnalysisContext] = None
        self._root: Optional[qtw.QWidget] = None
        self._controls_panel: Optional[qtw.QWidget] = None
        self._workspace_widget: Optional[qtw.QWidget] = None
        self._workspace_splitter: Optional[qtw.QSplitter] = None
        self._plot_hint_label: Optional[qtw.QLabel] = None
        self._control_signals_bound = False
        self._x_axis_combo: Optional[qtw.QComboBox] = None
        self._y_axis_combo: Optional[qtw.QComboBox] = None
        self._error_bar_combo: Optional[qtw.QComboBox] = None
        self._round_sd_checkbox: Optional[qtw.QCheckBox] = None
        self._gain_last_align_checkbox: Optional[qtw.QCheckBox] = None
        self._trend_line_combo: Optional[qtw.QComboBox] = None
        self._show_lines_checkbox: Optional[qtw.QCheckBox] = None
        self._table: Optional[_ResultTableWidget] = None
        self._figure = None
        self._axes = None
        self._canvas = None
        self._fallback_plot_label: Optional[qtw.QLabel] = None
        self._theme_mode = "dark"
        self._plot_series: list[_CurveSeries] = []
        self._plot_x_label = "X"
        self._plot_y_label = "Y"
        self._plot_x_mode = "iris"
        self._plot_y_mode = "gain"
        self._plot_err_mode = "off"
        self._plot_overlay_mode = "off"
        self._plot_hide_raw_series = False
        self._plot_fit_enabled = False
        self._plot_fit_series: list[_FitSeries] = []
        self._curve_visibility: dict[str, bool] = {}
        self._curve_artists: dict[str, object] = {}
        self._plot_points: list[
            tuple[
                str,
                np.ndarray,
                np.ndarray,
                np.ndarray,
                np.ndarray,
            ]
        ] = []
        self._fit_plot_points: list[tuple[str, np.ndarray, np.ndarray]] = []
        self._fit_hover_items: list[_FitHoverItem] = []
        self._legend_pick_map: dict[int, str] = {}
        self._legend_handle_by_label: dict[str, object] = {}
        self._legend_text_by_label: dict[str, object] = {}
        self._hover_annotation = None
        self._fit_stats_annotation = None
        self._table_sort_column = -1
        self._table_sort_order = Qt.AscendingOrder
        self._table_x_header = "X"
        self._table_y_header = "Y"
        self._table_base_headers = [
            "Curve #",
            "Curve",
            "N",
            "X",
            "Y",
        ]
        self._is_plot_panning = False
        self._plot_pan_state: Optional[
            tuple[float, float, tuple[float, float], tuple[float, float]]
        ] = None

    @classmethod
    def _plot_x_label_for_mode(cls, x_mode: str) -> str:
        """Return plot X-axis label for a mode key."""
        return cls._PLOT_X_LABELS.get(x_mode, "X")

    @classmethod
    def _table_x_label_for_mode(cls, x_mode: str) -> str:
        """Return result-table X-axis label for a mode key."""
        return cls._TABLE_X_LABELS.get(x_mode, "X")

    @classmethod
    def _y_label_for_mode(cls, y_mode: str) -> str:
        """Return plot/result-table Y-axis label for a mode key."""
        return cls._Y_LABELS.get(y_mode, "Y")
