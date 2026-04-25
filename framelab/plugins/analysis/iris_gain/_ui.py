"""UI construction and control wiring for the iris gain plugin."""

from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import QSignalBlocker, Qt

from .._base import AnalysisContext
from ._shared import (
    Figure,
    FigureCanvasQTAgg,
    MATPLOTLIB_AVAILABLE,
    _ResultTableWidget,
)


class _ResizeAwarePanel(qtw.QWidget):
    """Panel wrapper that reruns plot layout after Qt resizes settle."""

    def __init__(
        self,
        parent: qtw.QWidget | None = None,
        *,
        resize_callback=None,
    ) -> None:
        super().__init__(parent)
        self._resize_callback = resize_callback

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        callback = self._resize_callback
        if not callable(callback):
            return
        QtCore.QTimer.singleShot(0, callback)


class IrisGainUiMixin:
    """Widget construction and control-state helpers."""

    def create_widget(self, parent: qtw.QWidget) -> qtw.QWidget:
        """Create legacy plugin widget with controls above workspace."""

        root = qtw.QWidget(parent)
        layout = qtw.QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls_panel = self.create_controls_widget(root)
        if controls_panel is not None:
            layout.addWidget(controls_panel)
        workspace_widget = self.create_workspace_widget(root)
        if workspace_widget is not None:
            layout.addWidget(workspace_widget, 1)

        self._root = root
        self._finalize_widget_state()
        return root

    def create_controls_widget(
        self,
        parent: qtw.QWidget,
    ) -> qtw.QWidget | None:
        """Create plugin controls surface for host side-rail layouts."""

        controls_panel = qtw.QFrame(parent)
        self._controls_panel = controls_panel
        controls_panel.setObjectName("SubtlePanel")
        controls_panel.setSizePolicy(
            qtw.QSizePolicy.Preferred,
            qtw.QSizePolicy.Expanding,
        )
        controls_layout = qtw.QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setSpacing(8)

        axes_form = qtw.QFormLayout()
        axes_form.setContentsMargins(0, 0, 0, 0)
        axes_form.setHorizontalSpacing(10)
        axes_form.setVerticalSpacing(8)

        self._x_axis_combo = qtw.QComboBox()
        self._x_axis_combo.addItem("Iris Position", "iris")
        self._x_axis_combo.addItem("Exposure", "exposure")
        self._x_axis_combo.setToolTip("Select the independent variable.")
        axes_form.addRow(self._make_title_label("X Axis"), self._x_axis_combo)

        self._y_axis_combo = qtw.QComboBox()
        for label, key in self._Y_AXIS_OPTIONS:
            self._y_axis_combo.addItem(label, key)
        self._y_axis_combo.setToolTip("Select the dependent metric to plot.")
        axes_form.addRow(self._make_title_label("Y Axis"), self._y_axis_combo)

        self._error_bar_combo = qtw.QComboBox()
        self._error_bar_combo.addItem("Off", "off")
        self._error_bar_combo.addItem("Std", "std")
        self._error_bar_combo.addItem("Std Err", "stderr")
        self._error_bar_combo.setToolTip(
            "Select uncertainty used for plot error bars. "
            "If display rounding is enabled, this also sets the rounding source.",
        )
        axes_form.addRow(
            self._make_title_label("Error Bars"),
            self._error_bar_combo,
        )
        controls_layout.addLayout(axes_form)
        controls_layout.addSpacing(6)

        display_form = qtw.QFormLayout()
        display_form.setContentsMargins(0, 0, 0, 0)
        display_form.setHorizontalSpacing(10)
        display_form.setVerticalSpacing(8)

        self._trend_line_combo = qtw.QComboBox()
        self._trend_line_combo.addItem("Off", "off")
        self._trend_line_combo.addItem("Linear fit", "linear_fit")
        self._trend_line_combo.addItem("Mean by X", "mean_x")
        self._trend_line_combo.setToolTip(
            "Overlay either a global linear fit or a mean-by-X trend line.",
        )
        display_form.addRow(
            self._make_title_label("Trend"),
            self._trend_line_combo,
        )
        controls_layout.addLayout(display_form)

        self._round_sd_checkbox = qtw.QCheckBox("Round Display to 1 s.d.")
        self._round_sd_checkbox.setChecked(False)
        self._round_sd_checkbox.setToolTip(
            "Display-only rounding: rounds Y value and uncertainty to 1 "
            "significant digit using the uncertainty source selected in "
            "Error Bars (Std or Std Err).",
        )
        controls_layout.addWidget(self._round_sd_checkbox)

        self._gain_last_align_checkbox = qtw.QCheckBox("Align First Point to 1")
        self._gain_last_align_checkbox.setChecked(False)
        self._gain_last_align_checkbox.setToolTip(
            "Display-only for Intensity Gain (last ref): multiply plotted "
            "Y values by a constant so the first point is 1.",
        )
        controls_layout.addWidget(self._gain_last_align_checkbox)

        self._show_lines_checkbox = qtw.QCheckBox("Show Series Lines")
        self._show_lines_checkbox.setChecked(True)
        self._show_lines_checkbox.setToolTip(
            "When disabled, only points are shown for raw series.",
        )
        controls_layout.addWidget(self._show_lines_checkbox)
        controls_layout.addStretch(1)
        self._finalize_widget_state()
        return controls_panel

    def create_workspace_widget(
        self,
        parent: qtw.QWidget,
    ) -> qtw.QWidget | None:
        """Create plugin workspace surface for host side-rail layouts."""

        workspace_widget = qtw.QWidget(parent)
        self._workspace_widget = workspace_widget
        layout = qtw.QVBoxLayout(workspace_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = qtw.QSplitter(Qt.Horizontal)
        self._workspace_splitter = splitter
        splitter.setChildrenCollapsible(False)

        table_panel = qtw.QWidget()
        table_panel.setObjectName("TablePanel")
        table_layout = qtw.QVBoxLayout(table_panel)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        self._table = _ResultTableWidget()
        self._table.setRowCount(0)
        self._table.setColumnCount(len(self._table_base_headers))
        self._table.setHorizontalHeaderLabels(self._table_base_headers)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._on_table_header_clicked)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(qtw.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(qtw.QAbstractItemView.SelectItems)
        self._table.setSelectionMode(qtw.QAbstractItemView.ExtendedSelection)
        self._table.setSortingEnabled(False)
        self._configure_result_table_columns()
        self._apply_result_table_header_tooltips()
        table_layout.addWidget(self._table, 1)
        splitter.addWidget(table_panel)

        plot_panel = _ResizeAwarePanel(
            resize_callback=self._apply_plot_layout,
        )
        plot_panel.setObjectName("ImagePanel")
        plot_panel.setMinimumWidth(560)
        plot_layout = qtw.QVBoxLayout(plot_panel)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)
        plot_hint_text = (
            "Right-click plot for view actions: reset view, show all curves, "
            "or copy plot."
        )
        plot_panel.setToolTip(plot_hint_text)
        plot_panel.setStatusTip(plot_hint_text)
        if (
            MATPLOTLIB_AVAILABLE
            and Figure is not None
            and FigureCanvasQTAgg is not None
        ):
            self._figure = Figure(figsize=(5.2, 3.0), dpi=100)
            self._axes = self._figure.add_subplot(111)
            self._canvas = FigureCanvasQTAgg(
                self._figure,
                resize_callback=self._apply_plot_layout,
            )
            self._canvas.setMinimumWidth(560)
            self._canvas.setSizePolicy(
                qtw.QSizePolicy.Expanding,
                qtw.QSizePolicy.Expanding,
            )
            self._canvas.updateGeometry()
            self._canvas.setToolTip(plot_hint_text)
            self._canvas.setStatusTip(plot_hint_text)
            plot_layout.addWidget(self._canvas, 1)
        else:
            self._fallback_plot_label = qtw.QLabel(
                "matplotlib is not installed.\nInstall it to display plots.",
            )
            self._fallback_plot_label.setObjectName("MutedLabel")
            self._fallback_plot_label.setAlignment(Qt.AlignCenter)
            self._fallback_plot_label.setWordWrap(True)
            plot_layout.addWidget(self._fallback_plot_label, 1)

        plot_hint = qtw.QLabel(plot_hint_text)
        self._plot_hint_label = plot_hint
        plot_hint.setObjectName("MutedLabel")
        plot_hint.setWordWrap(True)
        plot_hint.setToolTip(plot_hint_text)
        plot_hint.setStatusTip(plot_hint_text)
        plot_layout.addWidget(plot_hint)
        splitter.addWidget(plot_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([360, 680])
        splitter.splitterMoved.connect(lambda _pos, _index: self._apply_plot_layout())
        layout.addWidget(splitter, 1)
        self._connect_plot_interactions()
        self._finalize_widget_state()
        return workspace_widget

    def _finalize_widget_state(self) -> None:
        """Finish UI wiring after controls/workspace widgets exist."""

        if not getattr(self, "_control_signals_bound", False):
            if self._x_axis_combo is not None:
                self._x_axis_combo.currentIndexChanged.connect(
                    self._on_x_axis_changed,
                )
            if self._y_axis_combo is not None:
                self._y_axis_combo.currentIndexChanged.connect(
                    self._on_controls_changed,
                )
            if self._error_bar_combo is not None:
                self._error_bar_combo.currentIndexChanged.connect(
                    self._on_controls_changed,
                )
            if self._round_sd_checkbox is not None:
                self._round_sd_checkbox.toggled.connect(
                    self._on_controls_changed,
                )
            if self._gain_last_align_checkbox is not None:
                self._gain_last_align_checkbox.toggled.connect(
                    self._on_controls_changed,
                )
            if self._trend_line_combo is not None:
                self._trend_line_combo.currentIndexChanged.connect(
                    self._on_controls_changed,
                )
            if self._show_lines_checkbox is not None:
                self._show_lines_checkbox.toggled.connect(
                    self._on_controls_changed,
                )
            self._control_signals_bound = True
        self._sync_y_axis_combo_for_x_mode()
        self._update_control_state()

    def has_collapsible_controls(self) -> bool:
        """Return whether the plugin has a distinct controls panel."""

        return self._controls_panel is not None

    def set_controls_collapsed(self, collapsed: bool) -> None:
        """Show or hide the plugin controls panel."""

        if self._controls_panel is not None:
            self._controls_panel.setVisible(not bool(collapsed))

    def set_secondary_help_visible(self, visible: bool) -> None:
        """Show or hide the compact plot hint line."""

        if self._plot_hint_label is not None:
            self._plot_hint_label.setVisible(bool(visible))

    def workspace_splitter(self) -> qtw.QSplitter | None:
        """Return the plugin workspace splitter for state persistence."""

        return self._workspace_splitter

    @staticmethod
    def _make_title_label(text: str) -> qtw.QLabel:
        """Create a bold section label for a control row."""
        label = qtw.QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _copy_result_table_selection(self) -> None:
        """Copy selected result-table cells to clipboard."""
        if self._table is None:
            return
        self._table.copy_selection_to_clipboard()

    def populate_menu(self, menu: qtw.QMenu) -> None:
        """Add plugin-specific menu actions to the host Plugins menu."""
        update_action = menu.addAction(self.run_action_label)
        update_action.triggered.connect(
            lambda _checked=False: self._run_analysis(),
        )
        reset_view_action = menu.addAction("Reset Plot View")
        reset_view_action.triggered.connect(
            lambda _checked=False: self._reset_plot_view(),
        )
        show_all_curves_action = menu.addAction("Show All Curves")
        show_all_curves_action.triggered.connect(
            lambda _checked=False: self._show_all_curves(),
        )
        menu.addSeparator()
        copy_table_action = menu.addAction("Copy Table Selection")
        copy_table_action.triggered.connect(
            lambda _checked=False: self._copy_result_table_selection(),
        )
        copy_plot_action = menu.addAction("Copy Plot Image")
        copy_plot_action.triggered.connect(
            lambda _checked=False: self._copy_plot_to_clipboard(),
        )
        export_plot_action = menu.addAction("Export Plot...")
        export_plot_action.setEnabled(self._figure is not None)
        export_plot_action.triggered.connect(
            lambda _checked=False: self._export_plot_dialog(),
        )

    def set_theme(self, mode: str) -> None:
        """Set plugin plot theme and redraw current content."""
        self._theme_mode = mode if mode == "dark" else "light"
        self._update_plot(
            self._plot_series,
            self._plot_x_label,
            self._plot_y_label,
            self._plot_err_mode,
            self._plot_fit_series,
            self._plot_fit_enabled,
            self._plot_overlay_mode,
        )

    def on_context_changed(self, context: AnalysisContext) -> None:
        """Store host context without running plugin analysis."""
        self._context = context
        self._update_control_state()
        self._analysis_dirty = True

    def run_analysis(self, context: AnalysisContext) -> None:
        """Run the explicit trend computation action."""
        self._context = context
        self._update_control_state()
        self._run_analysis()
        self._analysis_dirty = False

    def _on_x_axis_changed(self, _index: int) -> None:
        """Handle X-axis change and keep Y-axis choices valid."""
        self._sync_y_axis_combo_for_x_mode()
        self._on_controls_changed()

    def _on_controls_changed(self, _index: int | None = None) -> None:
        """Mark local controls dirty until the next explicit run."""
        self._update_control_state()
        self._analysis_dirty = True

    def _allowed_y_axis_options(
        self,
        x_mode: str,
    ) -> tuple[tuple[str, str], ...]:
        """Return Y-axis choices allowed for the selected X-axis mode."""
        if x_mode == "exposure":
            return tuple(
                (label, key)
                for label, key in self._Y_AXIS_OPTIONS
                if key != "dn_per_ms"
            )
        return self._Y_AXIS_OPTIONS

    def _sync_y_axis_combo_for_x_mode(self) -> None:
        """Update Y-axis combo options based on selected X-axis."""
        if self._x_axis_combo is None or self._y_axis_combo is None:
            return

        x_mode = self._current_data(self._x_axis_combo, "iris")
        allowed_options = self._allowed_y_axis_options(x_mode)
        current_key = self._current_data(self._y_axis_combo, "gain")
        existing_options = tuple(
            (
                self._y_axis_combo.itemText(index),
                str(self._y_axis_combo.itemData(index)),
            )
            for index in range(self._y_axis_combo.count())
        )
        if existing_options != allowed_options:
            blocker = QSignalBlocker(self._y_axis_combo)
            self._y_axis_combo.clear()
            for label, key in allowed_options:
                self._y_axis_combo.addItem(label, key)
            del blocker

        index = self._y_axis_combo.findData(current_key)
        if index < 0:
            fallback_key = "mean" if x_mode == "exposure" else "gain"
            index = self._y_axis_combo.findData(fallback_key)
        if index < 0 and self._y_axis_combo.count() > 0:
            index = 0
        if index >= 0:
            blocker = QSignalBlocker(self._y_axis_combo)
            self._y_axis_combo.setCurrentIndex(index)
            del blocker

        if x_mode == "exposure":
            self._y_axis_combo.setToolTip(
                "Select the dependent metric to plot. "
                "Intensity Rate is unavailable when X Axis is Exposure.",
            )
        else:
            self._y_axis_combo.setToolTip(
                "Select the dependent metric to plot.",
            )

    def _update_control_state(self) -> None:
        """Update enable/disable states for dependent controls."""
        if self._error_bar_combo is None:
            return
        self._sync_y_axis_combo_for_x_mode()
        self._error_bar_combo.setEnabled(True)
        err_mode = self._current_data(self._error_bar_combo, "off")
        y_mode = self._current_data(self._y_axis_combo, "gain")
        x_mode = self._current_data(self._x_axis_combo, "iris")
        lock_mean_x_trend = x_mode == "iris" and y_mode in {"gain", "gain_last"}
        if self._trend_line_combo is not None:
            if lock_mean_x_trend:
                trend_index = self._trend_line_combo.findData("mean_x")
                if (
                    trend_index >= 0
                    and self._trend_line_combo.currentIndex() != trend_index
                ):
                    blocker = QSignalBlocker(self._trend_line_combo)
                    self._trend_line_combo.setCurrentIndex(trend_index)
                    del blocker
                self._trend_line_combo.setEnabled(False)
                self._trend_line_combo.setToolTip(
                    "Locked to Mean by X for Gain vs Iris analysis.",
                )
            else:
                self._trend_line_combo.setEnabled(True)
                self._trend_line_combo.setToolTip(
                    "Overlay either a global linear fit or a mean-by-X trend line.",
                )
        if self._round_sd_checkbox is not None:
            self._round_sd_checkbox.setEnabled(err_mode != "off")
        if self._gain_last_align_checkbox is not None:
            is_gain_last = y_mode == "gain_last"
            self._gain_last_align_checkbox.setVisible(is_gain_last)
            self._gain_last_align_checkbox.setEnabled(is_gain_last)
        if self._show_lines_checkbox is not None:
            overlay = self._current_data(self._trend_line_combo, "off")
            is_off = overlay == "off"
            self._show_lines_checkbox.setEnabled(is_off)
            self._show_lines_checkbox.setVisible(is_off)
    def _connect_plot_interactions(self) -> None:
        """Attach matplotlib interaction callbacks for plot gestures."""
        if self._canvas is None:
            return
        self._canvas.mpl_connect("scroll_event", self._on_plot_scroll)
        self._canvas.mpl_connect("button_press_event", self._on_plot_press)
        self._canvas.mpl_connect("button_release_event", self._on_plot_release)
        self._canvas.mpl_connect("motion_notify_event", self._on_plot_motion)
        self._canvas.mpl_connect("pick_event", self._on_plot_pick)
        self._canvas.mpl_connect("axes_leave_event", self._on_plot_leave_axes)

    def _update_table_header_labels(self) -> None:
        """Render custom sort arrows in headers to match the app theme."""
        if self._table is None:
            return
        labels: list[str] = []
        for col, label in enumerate(self._table_base_headers):
            if col == self._table_sort_column:
                arrow = "▲" if self._table_sort_order == Qt.AscendingOrder else "▼"
                labels.append(f"{label} {arrow}")
            else:
                labels.append(label)
        self._table.setHorizontalHeaderLabels(labels)
        self._apply_result_table_header_tooltips()

    def _configure_result_table_columns(self) -> None:
        """Apply resize policy for current result-table column count."""
        if self._table is None:
            return
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in range(self._table.columnCount()):
            mode = (
                qtw.QHeaderView.Stretch
                if column == 1
                else qtw.QHeaderView.ResizeToContents
            )
            header.setSectionResizeMode(column, mode)

    def _apply_result_table_header_tooltips(self) -> None:
        """Attach concise per-column tooltips to result-table headers."""
        if self._table is None:
            return
        tip_by_header = {
            "Curve #": "Curve index in the current plot result.",
            "Curve": "Curve/series label.",
            "N": "Number of samples contributing to this datapoint.",
            self._table_x_header: f"{self._table_x_header} value for this row.",
            self._table_y_header: f"{self._table_y_header} value for this row.",
            "Std": "Standard deviation at this datapoint.",
            "Std Err": "Standard error at this datapoint.",
            "Abs Unc": (
                "Absolute uncertainty of the datapoint (propagated from the "
                "selected error source)."
            ),
            "Δ [%]": "Relative uncertainty: (selected error / value) * 100.",
        }
        for column, label in enumerate(self._table_base_headers):
            item = self._table.horizontalHeaderItem(column)
            if item is not None:
                item.setToolTip(tip_by_header.get(label, ""))

    def _apply_result_table_sort(self) -> None:
        """Apply tri-state sort state on the analysis result table."""
        if self._table is None:
            return
        if self._table_sort_column < 0:
            self._table.setSortingEnabled(False)
            self._update_table_header_labels()
            return
        self._table.setSortingEnabled(True)
        self._table.sortItems(self._table_sort_column, self._table_sort_order)
        self._update_table_header_labels()

    def _on_table_header_clicked(self, logical_index: int) -> None:
        """Cycle table sort state: ascending, descending, then unsorted."""
        if logical_index < 0:
            return
        if self._table_sort_column != logical_index:
            self._table_sort_column = logical_index
            self._table_sort_order = Qt.AscendingOrder
            self._apply_result_table_sort()
            return
        if self._table_sort_order == Qt.AscendingOrder:
            self._table_sort_order = Qt.DescendingOrder
            self._apply_result_table_sort()
            return

        self._table_sort_column = -1
        self._table_sort_order = Qt.AscendingOrder
        self._run_analysis()
