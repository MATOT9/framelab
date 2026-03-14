"""Measure-page and preview/control helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PySide6 import QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt, QModelIndex, QSignalBlocker

from ..background import BackgroundConfig, BackgroundLibrary, canonical_exposure_key
from ..formatting import format_metric_triplet
from ..metadata import extract_path_metadata
from ..processing_failures import (
    failure_reason_from_exception,
    make_processing_failure,
)
from ..ui_primitives import (
    ChipSpec,
    SummaryItem,
    build_page_header,
    build_summary_strip,
)
from ..models import MetricsSortProxyModel, MetricsTableModel
from ..widgets import (
    HistogramWidget,
    ImagePreviewLabel,
    LeftElideItemDelegate,
    MetricsTableView,
    install_large_header_resize_cursor,
    install_large_splitter_handle_cursors,
)


class InspectPageMixin:
    """Measure-page construction and preview/control helpers."""

    def _apply_measure_page_density(self, tokens) -> None:
        """Apply density tokens to shared Measure-page layouts."""

        layout = getattr(self, "_measure_page_layout", None)
        if layout is not None:
            layout.setSpacing(tokens.page_spacing)
        control_panel_layout = getattr(self, "_measure_control_panel_layout", None)
        if control_panel_layout is not None:
            control_panel_layout.setSpacing(tokens.page_spacing)
        metrics_layout = getattr(self, "_measure_metrics_layout", None)
        if metrics_layout is not None:
            self._set_uniform_layout_margins(
                metrics_layout,
                tokens.command_bar_margin_h,
                tokens.command_bar_margin_v,
            )
            metrics_layout.setSpacing(tokens.command_bar_spacing)
        for name in ("_measure_metrics_row", "_measure_topk_layout", "_measure_roi_row"):
            row_layout = getattr(self, name, None)
            if row_layout is not None:
                row_layout.setSpacing(tokens.panel_spacing)
        for name in ("_measure_table_layout", "_measure_image_panel_layout"):
            panel_layout = getattr(self, name, None)
            if panel_layout is not None:
                self._set_uniform_layout_margins(
                    panel_layout,
                    tokens.panel_margin_h,
                    tokens.panel_margin_v,
                )
                panel_layout.setSpacing(tokens.panel_spacing)
        for name in ("_measure_image_page_layout", "_measure_hist_page_layout"):
            nested_layout = getattr(self, name, None)
            if nested_layout is not None:
                nested_layout.setSpacing(tokens.panel_spacing)

    def _build_inspect_page(self) -> qtw.QWidget:
        """Build metrics inspection page (table + preview)."""
        page = qtw.QWidget()
        layout = qtw.QVBoxLayout(page)
        self._measure_page_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._measure_header = build_page_header(
            "Measurement Workstation",
            (
                "Tune metric settings, apply optional preprocessing, and "
                "inspect the active image and derived measurements."
            ),
        )
        layout.addWidget(self._measure_header)
        layout.addWidget(self._build_processing_failure_banner("Measure"))
        self._measure_summary_strip = build_summary_strip()
        layout.addWidget(self._measure_summary_strip)
        layout.addWidget(self._build_control_panel())

        splitter = qtw.QSplitter(Qt.Horizontal)
        self.measure_main_splitter = splitter
        splitter.addWidget(self._build_table_panel())
        splitter.addWidget(self._build_image_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.splitterMoved.connect(
            lambda _pos, _index: self._persist_splitter_state(
                "measure.main_splitter",
                splitter,
            )
            if hasattr(self, "_persist_splitter_state")
            else None,
        )
        install_large_splitter_handle_cursors(splitter)
        layout.addWidget(splitter, 1)
        if hasattr(self, "_restore_splitter_state"):
            self._restore_splitter_state("measure.main_splitter", splitter)
        if hasattr(self, "_policy_for_page"):
            self._apply_measure_page_visibility_policy(
                self._policy_for_page("measure"),
            )
        return page

    def _build_control_panel(self) -> qtw.QWidget:
        panel = qtw.QWidget()
        layout = qtw.QVBoxLayout(panel)
        self._measure_control_panel_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        metrics_group = qtw.QFrame()
        metrics_group.setObjectName("CommandBar")
        metrics_layout = qtw.QVBoxLayout(metrics_group)
        self._measure_metrics_layout = metrics_layout
        metrics_layout.setContentsMargins(14, 12, 14, 12)
        metrics_layout.setSpacing(8)

        metrics_title = qtw.QLabel("Primary Controls")
        metrics_title.setObjectName("SectionTitle")
        metrics_layout.addWidget(metrics_title)

        metrics_row = qtw.QHBoxLayout()
        self._measure_metrics_row = metrics_row
        metrics_row.setSpacing(8)
        thr_label = qtw.QLabel("Saturation Threshold (>=)")
        thr_label.setObjectName("SectionTitle")
        metrics_row.addWidget(thr_label)

        self.threshold_spin = qtw.QDoubleSpinBox(decimals=0)
        self.threshold_spin.setRange(0, 2**16)
        self.threshold_spin.setValue(65520)
        self.threshold_spin.setSingleStep(1)
        self.threshold_spin.setMinimumWidth(110)
        self.threshold_spin.setToolTip(
            "Pixels above this value are counted as saturated.",
        )
        metrics_row.addWidget(self.threshold_spin)

        apply_threshold_button = qtw.QPushButton("Apply")
        apply_threshold_button.setObjectName("AccentButton")
        apply_threshold_button.setToolTip(
            "Apply threshold change and refresh saturation display.",
        )
        apply_threshold_button.clicked.connect(
            lambda _checked=False: self._apply_threshold_update()
        )
        metrics_row.addWidget(apply_threshold_button)

        metrics_row.addSpacing(12)

        mode_label = qtw.QLabel("Average Mode")
        mode_label.setObjectName("SectionTitle")
        metrics_row.addWidget(mode_label)

        self.avg_mode_combo = qtw.QComboBox()
        self.avg_mode_combo.addItem("Disabled", "none")
        self.avg_mode_combo.addItem("Top-K Mean", "topk")
        self.avg_mode_combo.addItem("ROI Mean", "roi")
        self.avg_mode_combo.setToolTip(
            "Select how the average metric is computed for each image.",
        )
        self.avg_mode_combo.currentIndexChanged.connect(
            lambda _index: self._on_average_mode_changed()
        )
        metrics_row.addWidget(self.avg_mode_combo)

        self.topk_controls_widget = qtw.QWidget()
        topk_layout = qtw.QHBoxLayout(self.topk_controls_widget)
        self._measure_topk_layout = topk_layout
        topk_layout.setContentsMargins(0, 0, 0, 0)
        topk_layout.setSpacing(8)

        self.topk_label = qtw.QLabel("Top-K Count")
        self.topk_label.setObjectName("SectionTitle")
        topk_layout.addWidget(self.topk_label)

        self.avg_spin = qtw.QSpinBox()
        self.avg_spin.setRange(1, 1000000000)
        self.avg_spin.setValue(32)
        self.avg_spin.setEnabled(False)
        self.avg_spin.setMinimumWidth(90)
        self.avg_spin.setToolTip(
            "Number of highest-intensity pixels used in Top-K mode.",
        )
        topk_layout.addWidget(self.avg_spin)
        self.apply_topk_button = qtw.QPushButton("Apply Top-K Count")
        self.apply_topk_button.setObjectName("AccentButton")
        self.apply_topk_button.setEnabled(False)
        self.apply_topk_button.setToolTip(
            "Apply Top-K count and recompute metrics.",
        )
        self.apply_topk_button.clicked.connect(
            lambda _checked=False: self._apply_live_update(),
        )
        topk_layout.addWidget(self.apply_topk_button)
        metrics_row.addWidget(self.topk_controls_widget)

        metrics_row.addSpacing(12)
        self.measure_display_button = qtw.QToolButton()
        self.measure_display_button.setObjectName("DisclosureButton")
        self.measure_display_button.setPopupMode(qtw.QToolButton.InstantPopup)
        self.measure_display_button.setText("Display")
        self.measure_display_button.setToolTip(
            "Open rounding and normalization display options.",
        )
        self.measure_display_button.setMenu(
            self._build_measure_display_menu(),
        )
        metrics_row.addWidget(self.measure_display_button)
        metrics_row.addStretch(1)
        metrics_layout.addLayout(metrics_row)

        self.roi_controls_widget = qtw.QWidget()
        roi_row = qtw.QHBoxLayout(self.roi_controls_widget)
        self._measure_roi_row = roi_row
        roi_row.setContentsMargins(0, 0, 0, 0)
        roi_row.setSpacing(8)

        self.roi_tools_label = qtw.QLabel("ROI Tools")
        self.roi_tools_label.setObjectName("SectionTitle")
        roi_row.addWidget(self.roi_tools_label)

        self.apply_roi_all_button = qtw.QPushButton("Apply ROI to All Images")
        self.apply_roi_all_button.setToolTip(
            "Apply current ROI rectangle to every loaded image.",
        )
        self.apply_roi_all_button.clicked.connect(
            self._apply_roi_to_all_images,
        )
        self.apply_roi_all_button.setEnabled(False)
        roi_row.addWidget(self.apply_roi_all_button)

        self.load_roi_button = qtw.QPushButton("Load ROI...")
        self.load_roi_button.setToolTip("Load ROI rectangle from a JSON file.")
        self.load_roi_button.clicked.connect(self._load_roi_from_file)
        self.load_roi_button.setEnabled(False)
        roi_row.addWidget(self.load_roi_button)

        self.save_roi_button = qtw.QPushButton("Save ROI...")
        self.save_roi_button.setToolTip("Save current ROI rectangle to a JSON file.")
        self.save_roi_button.clicked.connect(self._save_roi_to_file)
        self.save_roi_button.setEnabled(False)
        roi_row.addWidget(self.save_roi_button)

        self.clear_roi_button = qtw.QPushButton("Clear ROI")
        self.clear_roi_button.setToolTip("Remove current ROI and ROI metrics.")
        self.clear_roi_button.clicked.connect(self._clear_roi)
        self.clear_roi_button.setEnabled(False)
        roi_row.addWidget(self.clear_roi_button)

        self.roi_apply_progress = qtw.QProgressBar()
        self.roi_apply_progress.setMinimum(0)
        self.roi_apply_progress.setMaximum(100)
        self.roi_apply_progress.setValue(0)
        self.roi_apply_progress.setFormat("ROI apply %v/%m")
        self.roi_apply_progress.setTextVisible(True)
        self.roi_apply_progress.setVisible(False)
        self.roi_apply_progress.setMinimumWidth(180)
        roi_row.addWidget(self.roi_apply_progress)
        roi_row.addStretch(1)
        metrics_layout.addWidget(self.roi_controls_widget)
        self.roi_controls_widget.setVisible(False)
        layout.addWidget(metrics_group)
        self._sync_measure_display_menu_state()
        self._refresh_measure_header_state()

        return panel

    def _build_table_panel(self) -> qtw.QWidget:
        panel = qtw.QFrame()
        panel.setObjectName("TablePanel")
        layout = qtw.QVBoxLayout(panel)
        self._measure_table_layout = layout
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = qtw.QLabel("Image Metrics")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        self.table_model = MetricsTableModel(self)
        self.table_model.set_rounding_mode(self.metrics_state.rounding_mode)
        self.table_proxy = MetricsSortProxyModel(self)
        self.table_proxy.setSourceModel(self.table_model)
        self.table_proxy.setDynamicSortFilter(True)
        self.table = MetricsTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(qtw.QAbstractItemView.SelectItems)
        self.table.setSelectionMode(qtw.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(qtw.QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollMode(qtw.QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(
            qtw.QAbstractItemView.ScrollPerPixel,
        )
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setModel(self.table_proxy)
        self.table.setItemDelegateForColumn(
            1,
            LeftElideItemDelegate(self.table),
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(qtw.QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(24)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._on_table_header_clicked)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, qtw.QHeaderView.Stretch)
        header.setSectionResizeMode(2, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(9, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(10, qtw.QHeaderView.ResizeToContents)
        install_large_header_resize_cursor(header)
        selection_model = self.table.selectionModel()
        if selection_model is not None:
            selection_model.currentChanged.connect(
                lambda _current, _previous: self.on_row_selected()
            )
            selection_model.selectionChanged.connect(
                lambda _selected, _deselected: self.on_row_selected()
            )
        layout.addWidget(self.table, 1)
        self._apply_measure_table_visibility()
        return panel

    def _source_row_from_proxy_index(
        self,
        proxy_index: QModelIndex,
    ) -> Optional[int]:
        """Map proxy index to source-row index used by metric arrays."""
        if not proxy_index.isValid():
            return None
        source_index = self.table_proxy.mapToSource(proxy_index)
        if not source_index.isValid():
            return None
        row = source_index.row()
        if 0 <= row < self.dataset_state.path_count():
            return row
        return None

    def _set_table_current_source_row(self, source_row: int) -> None:
        """Select a row in the view using a source-model row index."""
        if not (0 <= source_row < self.table_model.rowCount()):
            return
        source_index = self.table_model.index(source_row, 1)
        proxy_index = self.table_proxy.mapFromSource(source_index)
        if not proxy_index.isValid():
            source_index = self.table_model.index(source_row, 0)
            proxy_index = self.table_proxy.mapFromSource(source_index)
        if not proxy_index.isValid():
            return
        selection_model = self.table.selectionModel()
        blocker: Optional[QSignalBlocker] = None
        if selection_model is not None:
            blocker = QSignalBlocker(selection_model)
        self.table.setCurrentIndex(proxy_index)
        if blocker is not None:
            del blocker

    def _apply_table_sort(self) -> None:
        """Apply active table sort state and update header indicator."""
        if self._sort_column < 0:
            self.table_proxy.sort(-1, Qt.AscendingOrder)
            self.table_model.set_sort_indicator(-1, Qt.AscendingOrder, False)
            return
        self.table_proxy.sort(self._sort_column, self._sort_order)
        self.table_model.set_sort_indicator(
            self._sort_column,
            self._sort_order,
            True,
        )

    def _on_table_header_clicked(self, logical_index: int) -> None:
        """Cycle sort mode for a clicked table header section."""
        dataset = self.dataset_state
        if logical_index == 0:
            self._sort_column = -1
            self._sort_order = Qt.AscendingOrder
        elif self._sort_column != logical_index:
            self._sort_column = logical_index
            self._sort_order = Qt.AscendingOrder
        elif self._sort_order == Qt.AscendingOrder:
            self._sort_order = Qt.DescendingOrder
        else:
            self._sort_column = -1
            self._sort_order = Qt.AscendingOrder

        self._apply_table_sort()
        if dataset.selected_index is not None:
            self._set_table_current_source_row(dataset.selected_index)

    def _build_image_panel(self) -> qtw.QWidget:
        panel = qtw.QFrame()
        panel.setObjectName("ImagePanel")
        layout = qtw.QVBoxLayout(panel)
        self._measure_image_panel_layout = layout
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = qtw.QLabel("Preview")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        self.preview_pages = qtw.QTabWidget()
        self.preview_pages.setDocumentMode(True)
        self.preview_pages.setTabPosition(qtw.QTabWidget.North)
        self.preview_pages.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preview_pages.customContextMenuRequested.connect(
            self._show_preview_context_menu,
        )

        image_page = qtw.QWidget()
        image_layout = qtw.QVBoxLayout(image_page)
        self._measure_image_page_layout = image_layout
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(6)

        self.image_preview = ImagePreviewLabel()
        self.image_preview.roiSelected.connect(self._on_roi_selected)
        self.image_preview.setContextMenuPolicy(Qt.CustomContextMenu)
        self.image_preview.customContextMenuRequested.connect(
            self._show_preview_context_menu,
        )
        image_layout.addWidget(self.image_preview, 1)

        self.preview_help_label = qtw.QLabel(
            "Wheel to zoom, drag to pan, and double-click to reset. "
            "ROI mode uses left-drag to draw or reposition the ROI."
        )
        self.preview_help_label.setObjectName("MutedLabel")
        self.preview_help_label.setWordWrap(True)
        self.preview_help_label.setToolTip(
            "Quick interaction help for image preview.",
        )
        image_layout.addWidget(self.preview_help_label)

        hist_page = qtw.QWidget()
        hist_layout = qtw.QVBoxLayout(hist_page)
        self._measure_hist_page_layout = hist_layout
        hist_layout.setContentsMargins(0, 0, 0, 0)
        hist_layout.setSpacing(6)

        self.histogram_widget = HistogramWidget()
        self.histogram_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.histogram_widget.customContextMenuRequested.connect(
            self._show_preview_context_menu,
        )
        hist_layout.addWidget(self.histogram_widget, 1)

        self.histogram_help_label = qtw.QLabel(
            "Histogram for the selected image after active preprocessing."
        )
        self.histogram_help_label.setObjectName("MutedLabel")
        self.histogram_help_label.setWordWrap(True)
        self.histogram_help_label.setToolTip(
            "Histogram uses the currently selected image and active preprocessing.",
        )
        hist_layout.addWidget(self.histogram_help_label)

        self.preview_pages.addTab(image_page, "Image")
        self.preview_pages.addTab(hist_page, "Histogram")
        layout.addWidget(self.preview_pages, 1)

        self.info_label = qtw.QLabel("No image selected.")
        self.info_label.setObjectName("MutedLabel")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        self._update_preview_page_visibility()
        if hasattr(self, "_active_density_tokens"):
            self._apply_measure_page_density(self._active_density_tokens)
        return panel

    def _current_average_mode(self) -> str:
        mode = self.avg_mode_combo.currentData()
        return str(mode) if mode is not None else "none"

    def _build_measure_display_menu(self) -> qtw.QMenu:
        """Build compact display-options menu for the Measure top band."""

        menu = qtw.QMenu(self)
        self.measure_normalize_action = menu.addAction(
            "Normalize Intensity (0-1)",
        )
        self.measure_normalize_action.setCheckable(True)
        self.measure_normalize_action.toggled.connect(
            self._on_normalize_intensity_toggled,
        )

        rounding_menu = menu.addMenu("Rounding")
        self._measure_rounding_actions: dict[str, QtGui.QAction] = {}
        self._measure_rounding_action_group = QtGui.QActionGroup(rounding_menu)
        self._measure_rounding_action_group.setExclusive(True)
        for label, mode in (
            ("Off", "off"),
            ("1 s.d. from Std", "std"),
            ("1 s.d. from Std Err", "stderr"),
        ):
            action = rounding_menu.addAction(label)
            action.setCheckable(True)
            action.setData(mode)
            action.triggered.connect(
                lambda _checked=False, rounding_mode=mode: self._set_rounding_mode(
                    rounding_mode,
                ),
            )
            self._measure_rounding_action_group.addAction(action)
            self._measure_rounding_actions[mode] = action

        return menu

    def _sync_measure_display_menu_state(self) -> None:
        """Sync display-menu actions and button tooltip from current state."""

        metrics = self.metrics_state
        normalize_action = getattr(self, "measure_normalize_action", None)
        if normalize_action is not None:
            blocker = QSignalBlocker(normalize_action)
            normalize_action.setChecked(bool(metrics.normalize_intensity_values))
            del blocker

        rounding_mode = str(getattr(metrics, "rounding_mode", "off") or "off")
        for mode, action in getattr(self, "_measure_rounding_actions", {}).items():
            blocker = QSignalBlocker(action)
            action.setChecked(mode == rounding_mode)
            del blocker

        button = getattr(self, "measure_display_button", None)
        if button is None:
            return
        rounding_label = {
            "off": "full precision",
            "std": "Std rounding",
            "stderr": "Std err rounding",
        }.get(rounding_mode, "full precision")
        normalization_label = (
            "normalized"
            if metrics.normalize_intensity_values
            else "raw DN"
        )
        button.setToolTip(
            "Open rounding and normalization display options. "
            f"Current: {normalization_label}, {rounding_label}.",
        )

    def _apply_measure_page_visibility_policy(self, policy) -> None:
        """Apply page-specific visibility policy to Measure-page widgets."""

        if hasattr(self, "_measure_summary_strip"):
            self._measure_summary_strip.set_collapsed(not policy.show_summary_strip)
        self._set_measure_help_visibility(policy.show_measure_help_labels)

    def _set_measure_help_visibility(self, visible: bool) -> None:
        """Show contextual preview help only when both policy and preview allow it."""

        if hasattr(self, "preview_help_label"):
            self.preview_help_label.setVisible(
                bool(visible) and bool(self.show_image_preview),
            )
        if hasattr(self, "histogram_help_label"):
            self.histogram_help_label.setVisible(
                bool(visible) and bool(self.show_histogram_preview),
            )

    def _update_preview_page_visibility(self) -> None:
        show_any = self.show_image_preview or self.show_histogram_preview
        self.preview_pages.setVisible(show_any)
        if hasattr(self.preview_pages, "setTabVisible"):
            self.preview_pages.setTabVisible(0, self.show_image_preview)
            self.preview_pages.setTabVisible(1, self.show_histogram_preview)

        if not self.show_image_preview:
            self.preview_help_label.hide()
            self.image_preview.clear_image()
            self.image_preview.set_intensity_image(None)

        if not self.show_histogram_preview:
            self.histogram_help_label.hide()
            self.histogram_widget.clear_histogram()

        if not show_any:
            self.info_label.setText("Preview disabled.")
            self._set_measure_help_visibility(False)
            return

        if self.show_image_preview:
            self.preview_pages.setCurrentIndex(0)
        elif self.show_histogram_preview:
            self.preview_pages.setCurrentIndex(1)
        help_visible = True
        if hasattr(self, "_policy_for_page"):
            help_visible = self._policy_for_page("measure").show_measure_help_labels
        self._set_measure_help_visibility(help_visible)
        self._refresh_measure_header_state()

    def _show_preview_context_menu(self, pos) -> None:
        """Open preview-area context menu to toggle visible preview tabs."""
        sender_widget = self.sender()
        global_pos = QtGui.QCursor.pos()
        if isinstance(sender_widget, qtw.QWidget):
            global_pos = sender_widget.mapToGlobal(pos)

        menu = qtw.QMenu(self.preview_pages)
        image_action = menu.addAction("Show Image Preview")
        image_action.setCheckable(True)
        image_action.setChecked(self.show_image_preview)
        hist_action = menu.addAction("Show Histogram")
        hist_action.setCheckable(True)
        hist_action.setChecked(self.show_histogram_preview)
        chosen = menu.exec(global_pos)
        if chosen is None:
            return

        changed = False
        if chosen == image_action:
            new_value = image_action.isChecked()
            if self.show_image_preview != new_value:
                self.show_image_preview = new_value
                changed = True
        elif chosen == hist_action:
            new_value = hist_action.isChecked()
            if self.show_histogram_preview != new_value:
                self.show_histogram_preview = new_value
                changed = True
        if changed:
            self._on_preview_visibility_changed()

    def _on_preview_visibility_changed(self) -> None:
        dataset = self.dataset_state
        if hasattr(self, "view_image_action"):
            blocker = QSignalBlocker(self.view_image_action)
            self.view_image_action.setChecked(self.show_image_preview)
            del blocker
        if hasattr(self, "view_histogram_action"):
            blocker = QSignalBlocker(self.view_histogram_action)
            self.view_histogram_action.setChecked(self.show_histogram_preview)
            del blocker
        self._update_preview_page_visibility()
        self._update_average_controls()
        if (
            dataset.selected_index is not None
            and 0 <= dataset.selected_index < dataset.path_count()
        ):
            self._display_image(dataset.selected_index)
        if not self.show_image_preview:
            self.image_preview.clear_image()
            self.image_preview.set_intensity_image(None)
        if hasattr(self, "_apply_dynamic_visibility_policy"):
            self._apply_dynamic_visibility_policy()

    def _set_rounding_mode(self, mode: str) -> None:
        """Update scientific rounding mode from compact display controls."""

        dataset = self.dataset_state
        metrics = self.metrics_state
        metrics.rounding_mode = (
            str(mode)
            if str(mode) in {"off", "std", "stderr"}
            else "off"
        )
        self.table_model.set_rounding_mode(metrics.rounding_mode)
        if (
            dataset.selected_index is not None
            and 0 <= dataset.selected_index < dataset.path_count()
        ):
            self._display_image(dataset.selected_index)
        self._update_analysis_context()
        self._sync_measure_display_menu_state()

    def _normalization_scale(self) -> float:
        """Return positive intensity scale used for 0-1 normalization."""
        metrics = getattr(self, "metrics_state", None)
        maxs = metrics.maxs if metrics is not None else getattr(self, "maxs", None)
        if maxs is None or maxs.size == 0:
            return 1.0
        scale = float(np.max(maxs))
        return scale if scale > 0.0 else 1.0

    @staticmethod
    def _as_finite_float(value: object) -> float:
        """Convert metadata-like value to finite float or NaN."""
        try:
            number = float(value)
        except Exception:
            return float(np.nan)
        if not np.isfinite(number):
            return float(np.nan)
        return float(number)

    def _metadata_numeric_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        """Build per-row iris-position and exposure arrays from metadata."""
        dataset = self.dataset_state
        n_rows = dataset.path_count()
        iris_values = np.full(n_rows, np.nan, dtype=np.float64)
        exposure_values = np.full(n_rows, np.nan, dtype=np.float64)
        for row, path in enumerate(dataset.paths):
            metadata = dataset.metadata_for_path(path)
            iris_values[row] = self._as_finite_float(
                metadata.get("iris_position"),
            )
            exposure_values[row] = self._as_finite_float(
                metadata.get("exposure_ms"),
            )
        return (iris_values, exposure_values)

    def _compute_dn_per_ms_metrics(
        self,
        mode: str,
        exposure_ms: np.ndarray,
    ) -> tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """Compute DN/ms values and uncertainties from active average metric."""
        metrics = getattr(self, "metrics_state", None)
        if mode == "topk":
            means = metrics.avg_maxs if metrics is not None else self.avg_maxs
            stds = metrics.avg_maxs_std if metrics is not None else self.avg_maxs_std
            sems = metrics.avg_maxs_sem if metrics is not None else self.avg_maxs_sem
        elif mode == "roi":
            means = metrics.roi_means if metrics is not None else self.roi_means
            stds = metrics.roi_stds if metrics is not None else self.roi_stds
            sems = metrics.roi_sems if metrics is not None else self.roi_sems
        else:
            return (None, None, None)
        if means is None:
            return (None, None, None)

        mean_arr = np.asarray(means, dtype=np.float64)
        std_arr = (
            np.asarray(stds, dtype=np.float64)
            if stds is not None
            else np.full_like(mean_arr, np.nan, dtype=np.float64)
        )
        sem_arr = (
            np.asarray(sems, dtype=np.float64)
            if sems is not None
            else np.full_like(mean_arr, np.nan, dtype=np.float64)
        )

        dn_per_ms = np.full_like(mean_arr, np.nan, dtype=np.float64)
        dn_per_ms_std = np.full_like(mean_arr, np.nan, dtype=np.float64)
        dn_per_ms_sem = np.full_like(mean_arr, np.nan, dtype=np.float64)
        valid_mask = np.isfinite(exposure_ms) & (exposure_ms > 0.0)
        if not np.any(valid_mask):
            return (dn_per_ms, dn_per_ms_std, dn_per_ms_sem)

        dn_per_ms[valid_mask] = mean_arr[valid_mask] / exposure_ms[valid_mask]
        dn_per_ms_std[valid_mask] = std_arr[valid_mask] / exposure_ms[valid_mask]
        dn_per_ms_sem[valid_mask] = sem_arr[valid_mask] / exposure_ms[valid_mask]
        return (dn_per_ms, dn_per_ms_std, dn_per_ms_sem)

    def _format_mean_std_sem(
        self,
        mean_value: float,
        std_value: float,
        sem_value: float,
    ) -> tuple[str, str, str]:
        """Format mean/std/stderr values using active display settings."""
        metrics = getattr(self, "metrics_state", None)
        mean = mean_value
        std = std_value
        sem = sem_value
        normalize_intensity = (
            metrics.normalize_intensity_values
            if metrics is not None
            else self.normalize_intensity_values
        )
        rounding_mode = (
            metrics.rounding_mode
            if metrics is not None
            else self.rounding_mode
        )
        if normalize_intensity:
            scale = self._normalization_scale()
            if scale > 0.0:
                mean /= scale
                std /= scale
                sem /= scale
        return format_metric_triplet(
            mean,
            std,
            sem,
            rounding_mode,
        )

    def _on_normalize_intensity_toggled(self, enabled: bool) -> None:
        """Toggle normalized display for mean/std/stderr values."""
        dataset = self.dataset_state
        metrics = self.metrics_state
        metrics.normalize_intensity_values = enabled
        self.table_model.set_intensity_normalization(
            metrics.normalize_intensity_values,
            self._normalization_scale(),
        )
        if (
            dataset.selected_index is not None
            and 0 <= dataset.selected_index < dataset.path_count()
        ):
            self._display_image(dataset.selected_index)
        self._update_analysis_context()
        self._sync_measure_display_menu_state()
        self._refresh_measure_header_state()

    def _background_config_snapshot(self) -> BackgroundConfig:
        """Return immutable snapshot used by background workers."""
        background_config = self.metrics_state.background_config
        return BackgroundConfig(
            enabled=background_config.enabled,
            source_mode=background_config.source_mode,
            clip_negative=background_config.clip_negative,
            exposure_policy=background_config.exposure_policy,
            no_match_policy=background_config.no_match_policy,
        )

    def _background_source_mode(self, mode: object | None = None) -> str:
        """Normalize one configured background source mode."""
        background_config = self.metrics_state.background_config
        token = (
            str(mode).strip()
            if mode is not None
            else str(background_config.source_mode).strip()
        )
        return (
            token
            if token in {"single_file", "folder_library"}
            else "single_file"
        )

    def _update_background_input_hint(
        self,
        target: qtw.QLineEdit | None = None,
        *,
        mode: object | None = None,
    ) -> str:
        """Update and return placeholder text for one background source input."""
        placeholder = (
            "Folder containing background TIFF files..."
            if self._background_source_mode(mode) == "folder_library"
            else "Background TIFF file..."
        )
        line_edit = target
        if line_edit is None:
            candidate = getattr(self, "background_path_edit", None)
            if isinstance(candidate, qtw.QLineEdit):
                line_edit = candidate
        if line_edit is not None:
            line_edit.setPlaceholderText(placeholder)
        return placeholder

    def _update_background_controls_visibility(self) -> None:
        """Show/hide BG command widgets based on enabled state."""
        widgets = getattr(self, "_background_command_widgets", None)
        if not widgets:
            return
        visible = bool(self.metrics_state.background_config.enabled)
        for widget in widgets:
            if widget is not None:
                widget.setVisible(visible)

    def _background_status_text(self, note: str | None = None) -> str:
        """Build compact background status text for plugin and host UI."""
        metrics = self.metrics_state
        if not metrics.background_config.enabled:
            text = "BG off"
        elif metrics.background_library.global_ref is not None:
            text = "BG loaded: 1 global reference"
        elif metrics.background_library.refs_by_exposure_ms:
            text = (
                "BG loaded: "
                f"{len(metrics.background_library.refs_by_exposure_ms)} "
                "exposure references"
            )
        else:
            text = "BG on | no reference loaded (raw fallback)"

        if (
            metrics.background_config.enabled
            and self._has_loaded_data()
            and metrics.bg_total_count > 0
        ):
            text += (
                " | "
                f"{metrics.bg_unmatched_count}/{metrics.bg_total_count} "
                "unmatched (raw fallback)"
            )
        if note:
            text += f" | {note}"
        return text

    def _update_background_status_label(
        self,
        note: str | None = None,
        *,
        label: qtw.QLabel | None = None,
    ) -> str:
        """Refresh compact background status text shown in plugin UI."""
        text = self._background_status_text(note)
        target = label
        if target is None:
            candidate = getattr(self, "background_status_label", None)
            if isinstance(candidate, qtw.QLabel):
                target = candidate
        if target is not None:
            target.setText(text)
        self._refresh_measure_header_state()
        return text

    def _refresh_measure_header_state(self) -> None:
        """Refresh measure-page header chips and summary strip."""
        if not hasattr(self, "_measure_header") or not hasattr(
            self,
            "_measure_summary_strip",
        ):
            return

        dataset = self.dataset_state
        metrics = self.metrics_state
        has_data = self._has_loaded_data()
        mode = self._current_average_mode()
        mode_label = {
            "none": "Disabled",
            "topk": "Top-K",
            "roi": "ROI",
        }.get(mode, mode.title())
        selection = (
            f"{int(dataset.selected_index) + 1}/{dataset.path_count()}"
            if has_data
            and dataset.selected_index is not None
            and 0 <= dataset.selected_index < dataset.path_count()
            else "None"
        )
        if metrics.is_roi_applying:
            roi_text = "Applying"
            roi_level = "warning"
        elif metrics.roi_rect is not None and mode == "roi":
            roi_text = "Drawn"
            roi_level = "success"
        elif mode == "roi":
            roi_text = "Awaiting selection"
            roi_level = "warning"
        else:
            roi_text = "Inactive"
            roi_level = "neutral"

        pending_threshold_apply = (
            has_data
            and hasattr(self, "threshold_spin")
            and float(self.threshold_spin.value()) != float(metrics.threshold_value)
        )
        if not has_data:
            saturation_text = "None"
            saturation_level = "neutral"
            saturation_tooltip = "Load a dataset to inspect saturated-image counts."
        elif (
            metrics.is_stats_running
            and metrics.stats_update_kind == "threshold_only"
        ):
            pulse = "." * (1 + int(getattr(self, "_threshold_summary_anim_phase", 0)))
            saturation_text = f"Updating{pulse}"
            saturation_level = "info"
            saturation_tooltip = (
                "Recomputing saturated-image counts for the applied threshold."
            )
        elif pending_threshold_apply:
            saturation_text = "Awaiting apply"
            saturation_level = "warning"
            saturation_tooltip = (
                "Threshold changed in the control bar. Apply it to refresh "
                "saturated-image counts."
            )
        else:
            saturated_images = 0
            if (
                metrics.sat_counts is not None
                and len(metrics.sat_counts) == dataset.path_count()
            ):
                saturated_images = int(
                    np.count_nonzero(
                        np.asarray(metrics.sat_counts, dtype=np.int64) > 0,
                    ),
                )
            saturation_text = str(saturated_images)
            saturation_level = "error" if saturated_images > 0 else "success"
            saturation_tooltip = (
                f"{saturated_images} image(s) contain at least one saturated pixel "
                f"at threshold {float(metrics.threshold_value):g}."
            )

        dn_per_ms_ready = bool(
            metrics.dn_per_ms_values is not None
            and np.any(np.isfinite(np.asarray(metrics.dn_per_ms_values, dtype=np.float64)))
        )
        chips = [
            ChipSpec(
                "Dataset loaded" if has_data else "No dataset",
                level="success" if has_data else "neutral",
            ),
            ChipSpec(
                "Metrics updating" if metrics.is_stats_running else "Metrics idle",
                level="info" if metrics.is_stats_running else "neutral",
            ),
            ChipSpec(
                "ROI apply running",
                level="warning",
            )
            if metrics.is_roi_applying
            else ChipSpec(
                "Preview active" if (self.show_image_preview or self.show_histogram_preview) else "Preview hidden",
                level="info" if (self.show_image_preview or self.show_histogram_preview) else "neutral",
            ),
        ]
        failure_count = len(getattr(self, "_processing_failures", []))
        if failure_count > 0:
            chips.append(
                ChipSpec(
                    f"{failure_count} processing issue(s)",
                    level="error",
                    tooltip=self._processing_failure_summary_text(),
                ),
            )
        self._measure_header.set_chips(chips)
        self._measure_summary_strip.set_items(
            [
                SummaryItem(
                    "Selection",
                    selection,
                    level="success" if selection != "None" else "neutral",
                ),
                SummaryItem(
                    "Average Mode",
                    mode_label,
                    level="info" if mode != "none" else "neutral",
                ),
                SummaryItem(
                    "ROI",
                    roi_text,
                    level=roi_level,
                ),
                SummaryItem(
                    "Saturated Images",
                    saturation_text,
                    level=saturation_level,
                    tooltip=saturation_tooltip,
                ),
                SummaryItem(
                    "Display",
                    "Normalized" if metrics.normalize_intensity_values else "Raw DN",
                    level="info" if metrics.normalize_intensity_values else "neutral",
                ),
                SummaryItem(
                    "DN/ms",
                    "Ready" if dn_per_ms_ready else "Unavailable",
                    level="success" if dn_per_ms_ready else "neutral",
                ),
            ],
        )

    def _on_background_mode_changed(
        self,
        _index: int | None = None,
        *,
        mode: object | None = None,
    ) -> str:
        """Update configured background source mode without triggering recompute."""
        background_config = self.metrics_state.background_config
        if mode is None:
            combo = getattr(self, "background_mode_combo", None)
            if isinstance(combo, qtw.QComboBox):
                mode = combo.currentData()
        background_config.source_mode = self._background_source_mode(mode)
        self._update_background_input_hint(mode=background_config.source_mode)
        self._update_background_status_label()
        return background_config.source_mode

    def _on_background_enabled_toggled(self, enabled: bool) -> None:
        """Enable/disable BG subtraction; disabling reverts metrics to raw."""
        dataset = self.dataset_state
        metrics = self.metrics_state
        metrics.background_config.enabled = bool(enabled)
        self._update_background_controls_visibility()
        self._invalidate_background_cache()
        if not enabled:
            if self._has_loaded_data():
                metrics.bg_applied_mask = np.zeros(dataset.path_count(), dtype=bool)
                metrics.bg_total_count = dataset.path_count()
                metrics.bg_unmatched_count = 0
                self._apply_live_update()
            self._update_background_status_label()
            self._set_status()
            return

        if self._has_loaded_data():
            metrics.bg_total_count = dataset.path_count()
            if (
                metrics.bg_applied_mask is None
                or len(metrics.bg_applied_mask) != dataset.path_count()
            ):
                metrics.bg_applied_mask = np.zeros(dataset.path_count(), dtype=bool)
            metrics.bg_unmatched_count = int(
                metrics.bg_total_count - np.count_nonzero(metrics.bg_applied_mask),
            )
        self._update_background_status_label()
        self._set_status()

    def _browse_background_source(
        self,
        *,
        parent: qtw.QWidget | None = None,
        mode: object | None = None,
        initial_text: str | None = None,
    ) -> str | None:
        """Open dialog to choose one background file or folder source."""
        metrics = self.metrics_state
        resolved_mode = self._background_source_mode(mode)
        if initial_text is None:
            candidate = getattr(self, "background_path_edit", None)
            if isinstance(candidate, qtw.QLineEdit):
                initial_text = candidate.text().strip()
        initial = initial_text or metrics.background_source_text or str(Path.home())
        dialog_parent = parent or self

        if resolved_mode == "folder_library":
            dialog = qtw.QFileDialog(
                dialog_parent,
                "Select background folder",
                initial,
            )
            dialog.setFileMode(qtw.QFileDialog.Directory)
            dialog.setOption(qtw.QFileDialog.ShowDirsOnly, True)
            dialog.setOption(qtw.QFileDialog.DontUseNativeDialog, True)
            if not dialog.exec():
                return None
            selected = dialog.selectedFiles()
            if not selected:
                return None
            metrics.background_source_text = selected[0]
            target = getattr(self, "background_path_edit", None)
            if isinstance(target, qtw.QLineEdit):
                target.setText(selected[0])
            return selected[0]

        dialog = qtw.QFileDialog(dialog_parent, "Select background TIFF", initial)
        dialog.setFileMode(qtw.QFileDialog.ExistingFile)
        dialog.setNameFilters(
            [
                "TIFF files (*.tif *.tiff *.TIF *.TIFF)",
                "All files (*)",
            ]
        )
        dialog.setOption(qtw.QFileDialog.DontUseNativeDialog, True)
        if not dialog.exec():
            return None
        selected = dialog.selectedFiles()
        if not selected:
            return None
        metrics.background_source_text = selected[0]
        target = getattr(self, "background_path_edit", None)
        if isinstance(target, qtw.QLineEdit):
            target.setText(selected[0])
        return selected[0]

    def _load_single_background_reference(self, source_path: Path) -> bool:
        """Load one TIFF as global background reference."""
        metrics = self.metrics_state
        if not source_path.is_file():
            if hasattr(self, "_record_processing_failures"):
                self._record_processing_failures(
                    [
                        make_processing_failure(
                            stage="background",
                            path=source_path,
                            reason="Invalid background file.",
                        ),
                    ],
                    replace_stage="background",
                )
            self._show_error(
                "Invalid background file",
                "Select a valid TIFF file.",
            )
            return False
        try:
            ref_image = self._read_2d_image(source_path).astype(
                np.float64,
                copy=False,
            )
        except Exception as exc:
            if hasattr(self, "_record_processing_failures"):
                self._record_processing_failures(
                    [
                        make_processing_failure(
                            stage="background",
                            path=source_path,
                            reason=failure_reason_from_exception(exc),
                        ),
                    ],
                    replace_stage="background",
                )
            self._show_error(
                "Background load failed",
                f"Could not read background TIFF:\n{exc}",
            )
            return False

        metrics.background_library = BackgroundLibrary(global_ref=ref_image.copy())
        if hasattr(self, "_record_processing_failures"):
            self._record_processing_failures([], replace_stage="background")
        return True

    def _load_folder_background_references(self, folder: Path) -> bool:
        """Load folder-based per-exposure background references."""
        metrics = self.metrics_state
        if not folder.is_dir():
            self._show_error(
                "Invalid background folder",
                "Select a valid folder containing TIFF files.",
            )
            return False

        files = self._find_tiffs(folder, apply_skip_patterns=False)
        if not files:
            self._show_error(
                "No TIFF files",
                "No TIFF background files were found in this folder.",
            )
            return False

        grouped: dict[float, list[np.ndarray]] = {}
        shape_by_key: dict[float, tuple[int, int]] = {}
        label_by_key: dict[float, str] = {}
        skipped_no_exposure = 0
        skipped_unreadable = 0
        skipped_shape = 0
        failures: list[object] = []

        for file_path in files:
            metadata = extract_path_metadata(
                str(file_path),
                metadata_source=self.dataset_state.metadata_source_mode,
            )
            key = canonical_exposure_key(metadata.get("exposure_ms"))
            if key is None:
                skipped_no_exposure += 1
                failures.append(
                    make_processing_failure(
                        stage="background",
                        path=file_path,
                        reason="No exposure metadata available.",
                    ),
                )
                continue
            try:
                img = self._read_2d_image(file_path).astype(
                    np.float64,
                    copy=False,
                )
            except Exception as exc:
                skipped_unreadable += 1
                failures.append(
                    make_processing_failure(
                        stage="background",
                        path=file_path,
                        reason=failure_reason_from_exception(exc),
                    ),
                )
                continue

            shape = (int(img.shape[0]), int(img.shape[1]))
            if key in shape_by_key and shape_by_key[key] != shape:
                skipped_shape += 1
                failures.append(
                    make_processing_failure(
                        stage="background",
                        path=file_path,
                        reason=(
                            "Shape mismatch for exposure-specific background "
                            "reference."
                        ),
                    ),
                )
                continue
            shape_by_key[key] = shape
            grouped.setdefault(key, []).append(img.copy())
            label_by_key[key] = f"{key:g} ms"

        if hasattr(self, "_record_processing_failures"):
            self._record_processing_failures(
                failures,
                replace_stage="background",
            )

        if not grouped:
            message = (
                "No valid exposure-matched background references found."
            )
            self._show_error("Background load failed", message)
            return False

        refs_by_exposure: dict[float, np.ndarray] = {}
        for key, images in grouped.items():
            if len(images) == 1:
                refs_by_exposure[key] = images[0]
                continue
            stack = np.stack(images, axis=0)
            refs_by_exposure[key] = np.median(stack, axis=0)

        metrics.background_library = BackgroundLibrary(
            global_ref=None,
            refs_by_exposure_ms=refs_by_exposure,
            label_by_exposure_ms=label_by_key,
        )

        skipped_total = skipped_no_exposure + skipped_unreadable + skipped_shape
        if skipped_total > 0:
            self._set_status(
                (
                    "Background loaded with "
                    f"{skipped_total} skipped file(s)"
                ),
            )
        return True

    def _load_background_reference(
        self,
        *,
        source_text: str | None = None,
        mode: object | None = None,
    ) -> bool:
        """Load background reference(s) from one selected source path."""
        dataset = self.dataset_state
        metrics = self.metrics_state
        if source_text is None:
            candidate = getattr(self, "background_path_edit", None)
            if isinstance(candidate, qtw.QLineEdit):
                source_text = candidate.text().strip()
        source_text = (source_text or "").strip()
        if not source_text:
            self._show_error(
                "Missing background source",
                "Choose a background file or folder first.",
            )
            return False

        source_path = Path(source_text).expanduser()
        metrics.background_source_text = str(source_path)
        resolved_mode = self._background_source_mode(mode)
        metrics.background_config.source_mode = resolved_mode

        if resolved_mode == "folder_library":
            loaded = self._load_folder_background_references(source_path)
        else:
            loaded = self._load_single_background_reference(source_path)

        if not loaded:
            self._update_background_status_label()
            return False

        self._invalidate_background_cache()
        if self._has_loaded_data():
            metrics.bg_total_count = dataset.path_count()
            if metrics.background_config.enabled:
                self._apply_live_update()
            else:
                self._update_background_status_label()
                if dataset.selected_index is not None:
                    self._display_image(dataset.selected_index)
        else:
            self._update_background_status_label()
        self._set_status("Background reference loaded")
        return True

    def _clear_background_reference(self) -> None:
        """Clear loaded background references."""
        dataset = self.dataset_state
        metrics = self.metrics_state
        metrics.background_library.clear()
        self._invalidate_background_cache()
        if self._has_loaded_data():
            metrics.bg_total_count = dataset.path_count()
            metrics.bg_unmatched_count = (
                dataset.path_count() if metrics.background_config.enabled else 0
            )
            metrics.bg_applied_mask = np.zeros(dataset.path_count(), dtype=bool)
            if metrics.background_config.enabled:
                self._apply_live_update()
            elif dataset.selected_index is not None:
                self._display_image(dataset.selected_index)
        self._update_background_status_label("cleared")
        self._set_status("Background reference cleared")

    def _update_measure_contextual_controls_visibility(self) -> None:
        """Show Measure controls only when the active mode makes them relevant."""

        mode = self._current_average_mode()
        topk_enabled = mode == "topk"
        self.topk_controls_widget.setVisible(topk_enabled)
        self.avg_spin.setEnabled(topk_enabled)
        self.apply_topk_button.setEnabled(topk_enabled)
        roi_enabled = mode == "roi"
        self.roi_controls_widget.setVisible(roi_enabled)
        self.image_preview.set_roi_mode(
            roi_enabled and self.show_image_preview,
        )
        metrics = self.metrics_state
        roi_job_running = metrics.is_roi_applying or (
            self._roi_apply_thread is not None
            and self._roi_apply_thread.isRunning()
        )
        roi_action_enabled = (
            roi_enabled
            and self._has_loaded_data()
            and metrics.roi_rect is not None
            and not roi_job_running
        )
        self.apply_roi_all_button.setEnabled(
            roi_action_enabled
        )
        self.load_roi_button.setEnabled(
            roi_enabled and self._has_loaded_data() and not roi_job_running
        )
        self.save_roi_button.setEnabled(
            roi_action_enabled
        )
        self.clear_roi_button.setEnabled(
            roi_action_enabled
        )
        self.roi_apply_progress.setVisible(metrics.is_roi_applying and roi_enabled)
        self._refresh_measure_header_state()

    def _update_average_controls(self) -> None:
        """Compatibility wrapper for measure contextual-control updates."""

        self._update_measure_contextual_controls_visibility()
