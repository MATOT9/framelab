"""Analysis-page construction and plugin orchestration."""

from __future__ import annotations

from typing import Optional

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

from ..analysis_context import AnalysisContextController
from ..dataset_state import DatasetStateController
from ..metrics_state import MetricsPipelineController
from ..plugins import PluginUiCapabilities
from ..plugins.analysis import (
    AnalysisContext,
    AnalysisPlugin,
)
from ..ui_primitives import (
    ChipSpec,
    SummaryItem,
    build_page_header,
    build_summary_strip,
)


class AnalysisPageMixin:
    """Analysis-page construction and active plugin coordination."""

    def _build_analysis_page(self) -> qtw.QWidget:
        """Build analysis page powered by plugin registry."""
        page = qtw.QWidget()
        self.analysis_page = page
        layout = qtw.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._analysis_header = build_page_header(
            "Analysis Surface",
            (
                "Choose an analysis plugin and inspect its results with the "
                "current measurement and metadata context."
            ),
        )
        layout.addWidget(self._analysis_header)
        self._analysis_summary_strip = build_summary_strip()
        layout.addWidget(self._analysis_summary_strip)

        control_panel = qtw.QFrame()
        control_panel.setObjectName("CommandBar")
        control_layout = qtw.QVBoxLayout(control_panel)
        control_layout.setContentsMargins(14, 12, 14, 12)
        control_layout.setSpacing(10)

        profile_group = qtw.QFrame()
        profile_group.setObjectName("SubtlePanel")
        profile_layout = qtw.QHBoxLayout(profile_group)
        profile_layout.setContentsMargins(12, 10, 12, 10)
        profile_layout.setSpacing(8)
        profile_label = qtw.QLabel("Analysis Plugin")
        profile_label.setObjectName("SectionTitle")
        profile_layout.addWidget(profile_label)
        self.analysis_profile_combo = qtw.QComboBox()
        self.analysis_profile_combo.currentIndexChanged.connect(
            self._on_analysis_profile_changed,
        )
        self.analysis_profile_combo.setToolTip(
            "Select the active analysis plugin.",
        )
        profile_layout.addWidget(self.analysis_profile_combo, 1)
        refresh_button = qtw.QPushButton("Refresh Context")
        refresh_button.setObjectName("AccentButton")
        refresh_button.setToolTip(
            "Push latest metrics/metadata into the active plugin.",
        )
        refresh_button.clicked.connect(
            lambda _checked=False: self._update_analysis_context(),
        )
        profile_layout.addWidget(refresh_button)
        reload_button = qtw.QPushButton("Reload Plugins")
        reload_button.setToolTip(
            "Reload the currently enabled plugins from the plugin folder.",
        )
        reload_button.clicked.connect(
            lambda _checked=False: self._reload_all_page_plugins(),
        )
        profile_layout.addWidget(reload_button)
        control_layout.addWidget(profile_group)
        layout.addWidget(control_panel)

        self.analysis_stack = qtw.QStackedWidget()
        layout.addWidget(self.analysis_stack, 1)
        self._load_analysis_plugins()
        self._refresh_analysis_summary()
        return page

    def _load_analysis_plugins(self) -> None:
        """Instantiate analysis plugins and add them to the UI stack."""
        self._analysis_plugins = []
        self.analysis_profile_combo.clear()
        while self.analysis_stack.count() > 0:
            widget = self.analysis_stack.widget(0)
            self.analysis_stack.removeWidget(widget)
            widget.deleteLater()

        plugin_classes = self._plugin_classes_for_page("analysis")
        if not plugin_classes:
            placeholder = qtw.QLabel("No analysis plugins enabled.")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setObjectName("MutedLabel")
            self.analysis_stack.addWidget(placeholder)
            self.analysis_profile_combo.addItem("None", "none")
            self._sync_analysis_tab_visibility()
            self._populate_plugins_menu_entries()
            self._apply_dynamic_visibility_policy()
            self._refresh_analysis_summary()
            return

        for plugin_cls in plugin_classes:
            plugin = plugin_cls()
            widget = plugin.create_widget(self.analysis_stack)
            plugin.set_theme(self._theme_mode)
            self._analysis_plugins.append(plugin)
            self.analysis_stack.addWidget(widget)
            self.analysis_profile_combo.addItem(
                plugin.display_name,
                plugin.plugin_id,
            )

        self.analysis_stack.setCurrentIndex(0)
        self._sync_analysis_tab_visibility()
        self._populate_plugins_menu_entries()
        self._update_analysis_context()
        self._apply_dynamic_visibility_policy()
        self._refresh_analysis_summary()

    def _on_analysis_profile_changed(self, index: int) -> None:
        """Switch active analysis profile in the stacked widget."""
        if not (0 <= index < self.analysis_stack.count()):
            return
        self.analysis_stack.setCurrentIndex(index)
        self._populate_plugins_menu_entries()
        self._apply_dynamic_visibility_policy()
        self._refresh_analysis_summary()

    def _current_analysis_plugin(self) -> Optional[AnalysisPlugin]:
        """Return currently selected analysis plugin instance, if available."""
        if not hasattr(self, "analysis_profile_combo"):
            return None
        index = self.analysis_profile_combo.currentIndex()
        if not (0 <= index < len(self._analysis_plugins)):
            return None
        return self._analysis_plugins[index]

    def _active_plugin_capabilities(self) -> PluginUiCapabilities:
        """Return active plugin UI capabilities once plugin flow is engaged."""
        if not self._analysis_plugin_engaged:
            return PluginUiCapabilities()
        plugin = self._current_analysis_plugin()
        if plugin is None:
            return PluginUiCapabilities()
        caps = getattr(plugin, "ui_capabilities", PluginUiCapabilities())
        if isinstance(caps, PluginUiCapabilities):
            return caps
        return PluginUiCapabilities()

    def _apply_dynamic_visibility_policy(self) -> None:
        """Apply policy-driven visibility to metadata controls and tables."""
        self._apply_grouping_field_visibility()
        self._update_metadata_controls_visibility()
        self._apply_data_table_visibility()
        self._apply_measure_table_visibility()
        self._sync_column_menu_actions()

    def _apply_measure_table_visibility(self) -> None:
        """Apply Measure-table visibility policy (core + mode + plugin)."""
        if not hasattr(self, "table"):
            return
        caps = self._active_plugin_capabilities()
        mode = self._current_average_mode()
        mode_has_average = mode in {"topk", "roi"}
        visible: set[str] = set(self.BASE_VISIBLE_MEASURE_COLUMNS)
        if mode_has_average:
            visible.update(self.MODE_MEASURE_COLUMNS)
        visible.update(caps.reveal_measure_columns)

        for key, override in self._manual_measure_column_visibility.items():
            if override:
                visible.add(key)
            else:
                visible.discard(key)

        if not mode_has_average:
            visible.difference_update(self.MODE_MEASURE_COLUMNS)

        for key, column in self.MEASURE_COLUMN_INDEX.items():
            self.table.setColumnHidden(column, key not in visible)

    def _build_analysis_context(self) -> AnalysisContext:
        """Build current dataset context for analysis plugins."""
        controller = getattr(self, "analysis_context_controller", None)
        if controller is None:
            dataset = DatasetStateController()
            dataset.set_loaded_dataset(
                None,
                getattr(self, "paths", []),
            )
            dataset.set_path_metadata(
                getattr(self, "path_metadata", {}),
            )
            metrics = MetricsPipelineController()
            for attr in (
                "maxs",
                "min_non_zero",
                "sat_counts",
                "dn_per_ms_values",
                "dn_per_ms_stds",
                "dn_per_ms_sems",
                "avg_maxs",
                "avg_maxs_std",
                "avg_maxs_sem",
                "roi_means",
                "roi_stds",
                "roi_sems",
                "_bg_applied_mask",
            ):
                target = "bg_applied_mask" if attr == "_bg_applied_mask" else attr
                setattr(metrics, target, getattr(self, attr, None))
            metrics.normalize_intensity_values = bool(
                getattr(self, "normalize_intensity_values", False),
            )
            metrics.background_config = getattr(self, "background_config")
            controller = AnalysisContextController(
                dataset,
                metrics,
                background_reference_label_resolver=self._background_reference_label_for_path,
            )

        return controller.build_context(
            mode=self._current_average_mode(),
            normalization_scale=self._normalization_scale(),
        )

    def _update_analysis_context(self) -> None:
        """Push current dataset context to all loaded analysis plugins."""
        if not self._analysis_plugins:
            self._refresh_analysis_summary()
            return
        context = self._build_analysis_context()
        for plugin in self._analysis_plugins:
            try:
                plugin.on_context_changed(context)
            except Exception:
                continue
        self._refresh_analysis_summary()

    def _refresh_analysis_summary(self) -> None:
        """Refresh analysis-page header chips and context summary strip."""
        if not hasattr(self, "_analysis_header") or not hasattr(
            self,
            "_analysis_summary_strip",
        ):
            return
        plugin = self._current_analysis_plugin()
        plugin_name = plugin.display_name if plugin is not None else "None"
        has_plugins = bool(self._analysis_plugins)
        mode = self._current_average_mode()
        metrics = getattr(self, "metrics_state", None)
        dataset = getattr(self, "dataset_state", None)
        metadata_source_mode = (
            dataset.metadata_source_mode
            if dataset is not None
            else getattr(self, "metadata_source_mode", "json")
        )
        record_count = (
            dataset.path_count()
            if dataset is not None
            else len(getattr(self, "paths", []))
        )
        mode_label = {
            "none": "Disabled",
            "topk": "Top-K",
            "roi": "ROI",
        }.get(mode, mode.title())
        self._analysis_header.set_chips(
            [
                ChipSpec(
                    "Plugins active" if has_plugins else "No analysis plugins",
                    level="success" if has_plugins else "warning",
                ),
                ChipSpec(
                    "Dataset loaded" if self._has_loaded_data() else "No dataset",
                    level="success" if self._has_loaded_data() else "neutral",
                ),
            ],
        )
        self._analysis_summary_strip.set_items(
            [
                SummaryItem(
                    "Active Plugin",
                    plugin_name,
                    level="info" if has_plugins else "neutral",
                ),
                SummaryItem(
                    "Records",
                    str(record_count),
                    level="success" if self._has_loaded_data() else "neutral",
                ),
                SummaryItem(
                    "Metric Mode",
                    mode_label,
                    level="info" if mode != "none" else "neutral",
                ),
                SummaryItem(
                    "Metadata",
                    "JSON" if metadata_source_mode == "json" else "Path",
                    level="info" if metadata_source_mode == "json" else "neutral",
                ),
                SummaryItem(
                    "Background",
                    "Enabled"
                    if (
                        metrics.background_config.enabled
                        if metrics is not None
                        else self.background_config.enabled
                    )
                    else "Off",
                    level="success"
                    if (
                        metrics.background_config.enabled
                        if metrics is not None
                        else self.background_config.enabled
                    )
                    else "neutral",
                ),
                SummaryItem(
                    "Normalization",
                    "On"
                    if (
                        metrics.normalize_intensity_values
                        if metrics is not None
                        else self.normalize_intensity_values
                    )
                    else "Off",
                    level="info"
                    if (
                        metrics.normalize_intensity_values
                        if metrics is not None
                        else self.normalize_intensity_values
                    )
                    else "neutral",
                ),
            ],
        )
