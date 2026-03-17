"""Analysis-page construction and plugin orchestration."""

from __future__ import annotations

from typing import Optional

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt, QSignalBlocker

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
from ..widgets import install_large_splitter_handle_cursors


class AnalysisPageMixin:
    """Analysis-page construction and active plugin coordination."""

    def _analysis_page_is_active(self) -> bool:
        """Return whether the Analyze tab is currently selected."""

        if not hasattr(self, "workflow_tabs"):
            return False
        return (
            self.workflow_tabs.currentWidget() is getattr(self, "analysis_page", None)
        )

    def _apply_analysis_page_density(self, tokens) -> None:
        """Apply density tokens to shared Analysis-page layouts."""

        layout = getattr(self, "_analysis_page_layout", None)
        if layout is not None:
            layout.setSpacing(tokens.page_spacing)
        selector_layout = getattr(self, "_analysis_selector_layout", None)
        if selector_layout is not None:
            self._set_uniform_layout_margins(
                selector_layout,
                tokens.panel_margin_h,
                tokens.panel_margin_v,
            )
            selector_layout.setSpacing(tokens.panel_spacing)
        for name in (
            "_analysis_side_rail_layout",
            "_analysis_selector_actions_layout",
        ):
            nested_layout = getattr(self, name, None)
            if nested_layout is not None:
                nested_layout.setSpacing(tokens.panel_spacing)

    def _build_analysis_page(self) -> qtw.QWidget:
        """Build analysis page powered by plugin registry."""
        page = qtw.QWidget()
        self.analysis_page = page
        layout = qtw.QVBoxLayout(page)
        self._analysis_page_layout = layout
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

        main_splitter = qtw.QSplitter(Qt.Horizontal)
        self.analysis_main_splitter = main_splitter
        main_splitter.setChildrenCollapsible(False)

        side_rail = qtw.QWidget()
        side_rail.setMinimumWidth(180)
        side_layout = qtw.QVBoxLayout(side_rail)
        self._analysis_side_rail_layout = side_layout
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(10)
        side_layout.setAlignment(Qt.AlignTop)

        selector_panel = qtw.QFrame()
        selector_panel.setSizePolicy(
            qtw.QSizePolicy.Preferred,
            qtw.QSizePolicy.Maximum,
        )
        selector_panel.setObjectName("CommandBar")
        selector_layout = qtw.QVBoxLayout(selector_panel)
        self._analysis_selector_layout = selector_layout
        selector_layout.setContentsMargins(12, 10, 12, 10)
        selector_layout.setSpacing(8)
        profile_label = qtw.QLabel("Analysis Plugin")
        profile_label.setObjectName("SectionTitle")
        selector_layout.addWidget(profile_label)
        self.analysis_profile_combo = qtw.QComboBox()
        self.analysis_profile_combo.currentIndexChanged.connect(
            self._on_analysis_profile_changed,
        )
        self.analysis_profile_combo.setToolTip(
            "Select the active analysis plugin.",
        )
        selector_layout.addWidget(self.analysis_profile_combo)

        selector_actions = qtw.QVBoxLayout()
        self._analysis_selector_actions_layout = selector_actions
        selector_actions.setSpacing(8)
        self.analysis_plugin_controls_toggle = qtw.QToolButton()
        self.analysis_plugin_controls_toggle.setObjectName("DisclosureButton")
        self.analysis_plugin_controls_toggle.setToolButtonStyle(
            Qt.ToolButtonTextBesideIcon
        )
        self.analysis_plugin_controls_toggle.setSizePolicy(
            qtw.QSizePolicy.Expanding,
            qtw.QSizePolicy.Fixed,
        )
        self.analysis_plugin_controls_toggle.setArrowType(Qt.RightArrow)
        self.analysis_plugin_controls_toggle.setCheckable(True)
        self.analysis_plugin_controls_toggle.setChecked(False)
        self.analysis_plugin_controls_toggle.setText("Plugin Controls (Show)")
        self.analysis_plugin_controls_toggle.setToolTip(
            "Expand/collapse plugin-specific analysis controls.",
        )
        self.analysis_plugin_controls_toggle.toggled.connect(
            self._on_analysis_plugin_controls_toggled,
        )
        selector_actions.addWidget(self.analysis_plugin_controls_toggle)
        refresh_button = qtw.QPushButton("Refresh Context")
        refresh_button.setSizePolicy(
            qtw.QSizePolicy.Expanding,
            qtw.QSizePolicy.Fixed,
        )
        refresh_button.setToolTip(
            "Push latest metrics/metadata into the active plugin.",
        )
        refresh_button.clicked.connect(
            lambda _checked=False: self._update_analysis_context(force_push=True),
        )
        selector_actions.addWidget(refresh_button)
        selector_layout.addLayout(selector_actions)
        side_layout.addWidget(selector_panel)

        self.analysis_controls_stack = qtw.QStackedWidget()
        self.analysis_controls_stack.setSizePolicy(
            qtw.QSizePolicy.Preferred,
            qtw.QSizePolicy.Maximum,
        )
        side_layout.addWidget(self.analysis_controls_stack)
        side_layout.addStretch(1)

        self.analysis_workspace_stack = qtw.QStackedWidget()
        self.analysis_stack = self.analysis_workspace_stack
        main_splitter.addWidget(side_rail)
        main_splitter.addWidget(self.analysis_workspace_stack)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 4)
        main_splitter.splitterMoved.connect(
            lambda _pos, _index: self._persist_splitter_state(
                self._analysis_main_splitter_key(),
                main_splitter,
            )
            if hasattr(self, "_persist_splitter_state")
            else None,
        )
        install_large_splitter_handle_cursors(main_splitter)
        layout.addWidget(main_splitter, 1)
        self._load_analysis_plugins()
        self._refresh_analysis_summary()
        self._restore_or_default_analysis_main_splitter()
        if hasattr(self, "_policy_for_page"):
            self._apply_analysis_page_visibility_policy(
                self._policy_for_page("analysis"),
            )
        if hasattr(self, "_active_density_tokens"):
            self._apply_analysis_page_density(self._active_density_tokens)
        return page

    def _load_analysis_plugins(self) -> None:
        """Instantiate analysis plugins and add them to the UI stack."""
        self._analysis_plugins = []
        self._analysis_host_controls_available: list[bool] = []
        self.analysis_profile_combo.clear()
        for stack_name in ("analysis_controls_stack", "analysis_workspace_stack"):
            stack = getattr(self, stack_name, None)
            if stack is None:
                continue
            while stack.count() > 0:
                widget = stack.widget(0)
                stack.removeWidget(widget)
                widget.deleteLater()

        plugin_classes = self._plugin_classes_for_page("analysis")
        if not plugin_classes:
            placeholder = qtw.QLabel("No analysis plugins enabled.")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setObjectName("MutedLabel")
            self.analysis_workspace_stack.addWidget(placeholder)
            controls_placeholder = qtw.QLabel("No plugin-specific controls.")
            controls_placeholder.setAlignment(Qt.AlignCenter)
            controls_placeholder.setObjectName("MutedLabel")
            self.analysis_controls_stack.addWidget(controls_placeholder)
            self.analysis_profile_combo.addItem("None", "none")
            self._sync_analysis_tab_visibility()
            self._populate_plugins_menu_entries()
            self._apply_dynamic_visibility_policy()
            self._refresh_analysis_summary()
            return

        for plugin_cls in plugin_classes:
            plugin = plugin_cls()
            controls_widget = plugin.create_controls_widget(
                self.analysis_controls_stack,
            )
            has_host_controls = controls_widget is not None
            workspace_widget = plugin.create_workspace_widget(
                self.analysis_workspace_stack,
            )
            if workspace_widget is None:
                workspace_widget = plugin.create_widget(self.analysis_workspace_stack)
            if controls_widget is None:
                controls_widget = self._build_analysis_controls_placeholder(
                    plugin.display_name,
                )
            self.analysis_controls_stack.addWidget(controls_widget)
            plugin.set_theme(self._theme_mode)
            self._analysis_plugins.append(plugin)
            self._analysis_host_controls_available.append(has_host_controls)
            self.analysis_workspace_stack.addWidget(workspace_widget)
            self.analysis_profile_combo.addItem(
                plugin.display_name,
                plugin.plugin_id,
            )
            self._bind_analysis_workspace_splitter(plugin)
            self._restore_active_analysis_workspace_splitter(plugin)

        self._sync_analysis_host_views(0)
        self._sync_analysis_tab_visibility()
        self._populate_plugins_menu_entries()
        self._analysis_context_delivered_generation_by_plugin.clear()
        self._invalidate_analysis_context(refresh_visible_plugin=True)
        self._apply_dynamic_visibility_policy()
        self._refresh_analysis_summary()

    def _on_analysis_profile_changed(self, index: int) -> None:
        """Switch active analysis profile in the stacked widget."""
        if not (0 <= index < self.analysis_workspace_stack.count()):
            return
        self._sync_analysis_host_views(index)
        if self._analysis_page_is_active():
            self._ensure_analysis_context_current()
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

    def _analysis_plugin_supports_control_collapse(self) -> bool:
        """Return whether the active plugin exposes a collapsible controls band."""

        index = (
            self.analysis_profile_combo.currentIndex()
            if hasattr(self, "analysis_profile_combo")
            else -1
        )
        if 0 <= index < len(getattr(self, "_analysis_host_controls_available", [])):
            if self._analysis_host_controls_available[index]:
                return True
        plugin = self._current_analysis_plugin()
        if plugin is None or not hasattr(plugin, "has_collapsible_controls"):
            return False
        try:
            return bool(plugin.has_collapsible_controls())
        except Exception:
            return False

    def _set_analysis_plugin_controls_expanded(self, expanded: bool) -> None:
        """Show or hide plugin controls while keeping the workspace visible."""

        supports_collapse = self._analysis_plugin_supports_control_collapse()
        index = (
            self.analysis_profile_combo.currentIndex()
            if hasattr(self, "analysis_profile_combo")
            else -1
        )
        host_controls_available = (
            0 <= index < len(getattr(self, "_analysis_host_controls_available", []))
            and self._analysis_host_controls_available[index]
        )
        controls_stack = getattr(self, "analysis_controls_stack", None)
        if controls_stack is not None:
            controls_stack.setVisible(
                bool(host_controls_available) and bool(expanded),
            )
        plugin = self._current_analysis_plugin()
        if supports_collapse and plugin is not None and not host_controls_available:
            try:
                plugin.set_controls_collapsed(not expanded)
            except Exception:
                supports_collapse = False

        toggle = getattr(self, "analysis_plugin_controls_toggle", None)
        if toggle is None:
            return
        blocker = QSignalBlocker(toggle)
        toggle.setVisible(supports_collapse)
        toggle.setEnabled(supports_collapse)
        toggle.setChecked(bool(expanded) if supports_collapse else False)
        toggle.setArrowType(
            Qt.DownArrow
            if supports_collapse and expanded
            else Qt.RightArrow
        )
        toggle.setText(
            "Plugin Controls (Hide)"
            if supports_collapse and expanded
            else "Plugin Controls (Show)"
        )
        del blocker

    def _build_analysis_controls_placeholder(self, plugin_name: str) -> qtw.QWidget:
        """Return a muted placeholder when a plugin has no split controls widget."""

        label = qtw.QLabel(
            f"{plugin_name} keeps its controls inside the workspace view.",
        )
        label.setObjectName("MutedLabel")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        return label

    @staticmethod
    def _analysis_main_splitter_key() -> str:
        """Return UI-state key used for the top-level Analysis splitter."""

        return "analysis.main_splitter.v3"

    def _analysis_workspace_splitter_key(self, plugin: AnalysisPlugin) -> str:
        """Return UI-state key used for one plugin workspace splitter."""

        return f"analysis.workspace_splitter.v6.{plugin.plugin_id}"

    def _has_persisted_analysis_splitter_state(self, key: str) -> bool:
        """Return whether splitter sizes are available for the given key."""

        if not getattr(self, "ui_preferences", None):
            return False
        if not self.ui_preferences.restore_panel_states:
            return False
        snapshot = getattr(self, "ui_state_snapshot", None)
        if snapshot is None:
            return False
        return bool(snapshot.splitter_sizes.get(key))

    def _restore_or_default_analysis_main_splitter(self) -> None:
        """Apply saved or default starting sizes to the Analysis host splitter."""

        splitter = getattr(self, "analysis_main_splitter", None)
        if splitter is None:
            return
        key = self._analysis_main_splitter_key()
        if (
            self._has_persisted_analysis_splitter_state(key)
            and hasattr(self, "_restore_splitter_state")
        ):
            self._restore_splitter_state(key, splitter)
            return
        total_width = splitter.width()
        if total_width <= 0:
            total_width = splitter.sizeHint().width()
        if total_width <= 0:
            splitter.setSizes([320, 980])
            return
        left_width = min(300, max(180, int(total_width * 0.25)))
        right_width = max(total_width - left_width, left_width + 1)
        splitter.setSizes([left_width, right_width])

    def _restore_visible_analysis_layout(self) -> None:
        """Reapply active Analysis splitter sizes after the page becomes visible."""

        self._restore_or_default_analysis_main_splitter()
        self._restore_active_analysis_workspace_splitter()

    def _bind_analysis_workspace_splitter(self, plugin: AnalysisPlugin) -> None:
        """Persist per-plugin workspace splitter movement when available."""

        if not hasattr(self, "_persist_splitter_state"):
            return
        splitter = plugin.workspace_splitter()
        if splitter is None:
            return
        key = self._analysis_workspace_splitter_key(plugin)
        splitter.splitterMoved.connect(
            lambda _pos, _index, splitter=splitter, key=key: (
                self._persist_splitter_state(key, splitter)
            ),
        )
        install_large_splitter_handle_cursors(splitter)

    def _restore_active_analysis_workspace_splitter(
        self,
        plugin: AnalysisPlugin | None = None,
    ) -> None:
        """Restore persisted splitter state for the active plugin workspace."""

        active = plugin or self._current_analysis_plugin()
        if active is None or not hasattr(self, "_restore_splitter_state"):
            return
        splitter = active.workspace_splitter()
        if splitter is None:
            return
        key = self._analysis_workspace_splitter_key(active)
        if self._has_persisted_analysis_splitter_state(key):
            self._restore_splitter_state(key, splitter)
        else:
            self._set_equal_analysis_workspace_split(splitter)
            return

        sizes = splitter.sizes()
        if self._analysis_workspace_split_is_pathological(sizes):
            self._set_equal_analysis_workspace_split(splitter)
            if hasattr(self, "_persist_splitter_state"):
                self._persist_splitter_state(key, splitter)
            return

    @staticmethod
    def _analysis_workspace_split_is_pathological(sizes: list[int]) -> bool:
        """Return whether a restored table/plot split is too unbalanced."""

        if len(sizes) != 2:
            return True
        total = max(int(sizes[0]) + int(sizes[1]), 0)
        if total <= 0:
            return True
        left_ratio = int(sizes[0]) / total
        right_ratio = int(sizes[1]) / total
        return left_ratio < 0.4 or right_ratio < 0.4

    @staticmethod
    def _set_equal_analysis_workspace_split(splitter: object | None) -> None:
        """Set the Analysis table/plot workspace to an equal-width split."""

        if splitter is None or not hasattr(splitter, "setSizes") or not hasattr(
            splitter,
            "size",
        ):
            return
        total_width = max(int(splitter.size().width()), 0)
        if total_width > 0:
            left_width = max(total_width // 2, 1)
            splitter.setSizes([left_width, max(total_width - left_width, 1)])
            return
        splitter.setSizes([1, 1])

    def _sync_analysis_host_views(self, index: int) -> None:
        """Keep analysis side-rail and workspace stacks aligned."""

        if hasattr(self, "analysis_controls_stack"):
            self.analysis_controls_stack.setCurrentIndex(index)
        if hasattr(self, "analysis_workspace_stack"):
            self.analysis_workspace_stack.setCurrentIndex(index)
        plugin = self._current_analysis_plugin()
        if plugin is not None:
            self._restore_active_analysis_workspace_splitter(plugin)

    def _apply_analysis_page_visibility_policy(self, policy) -> None:
        """Apply page-specific visibility policy to Analysis-page widgets."""

        if hasattr(self, "_analysis_summary_strip"):
            self._analysis_summary_strip.set_collapsed(not policy.show_summary_strip)
        self._set_analysis_plugin_controls_expanded(
            not policy.collapse_analysis_plugin_controls,
        )
        plugin = self._current_analysis_plugin()
        if plugin is not None and hasattr(plugin, "set_secondary_help_visible"):
            try:
                plugin.set_secondary_help_visible(policy.show_plot_help_labels)
            except Exception:
                pass

    def _on_analysis_plugin_controls_toggled(self, checked: bool) -> None:
        """Persist user disclosure choice for plugin controls."""

        if not self._analysis_plugin_supports_control_collapse():
            return
        if hasattr(self, "_remember_panel_state"):
            self._remember_panel_state(
                "analysis.plugin_controls",
                bool(checked),
            )
        if hasattr(self, "_apply_dynamic_visibility_policy"):
            self._apply_dynamic_visibility_policy()
            return
        self._set_analysis_plugin_controls_expanded(bool(checked))

    def _apply_dynamic_visibility_policy(self) -> None:
        """Apply policy-driven visibility to metadata controls and tables."""
        if hasattr(self, "_apply_density_policy"):
            self._apply_density_policy()
        if hasattr(self, "_apply_visibility_policy"):
            self._apply_visibility_policy()
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

    def _invalidate_analysis_context(
        self,
        *,
        refresh_visible_plugin: bool = True,
    ) -> None:
        """Mark analysis context dirty and refresh lazily when needed."""

        self._analysis_context_dirty = True
        if refresh_visible_plugin and self._analysis_page_is_active():
            timer = getattr(self, "_analysis_context_refresh_timer", None)
            if timer is not None:
                timer.start()
            else:
                self._ensure_analysis_context_current()
            return
        self._refresh_analysis_summary()

    def _flush_dirty_analysis_context_if_visible(self) -> None:
        """Rebuild analysis context only when the Analyze page is visible."""

        if not self._analysis_page_is_active():
            return
        self._ensure_analysis_context_current()

    def _ensure_analysis_context_current(
        self,
        *,
        force_push: bool = False,
        force_rebuild: bool = False,
    ) -> AnalysisContext | None:
        """Ensure the active analysis plugin has the latest prepared context."""

        if not self._analysis_plugins:
            self._refresh_analysis_summary()
            return None

        if (
            force_rebuild
            or self._analysis_context_dirty
            or self._analysis_context_cache is None
        ):
            context = self._build_analysis_context()
            self._analysis_context_cache = context
            self._analysis_context_dirty = False
            self._analysis_context_generation += 1
        else:
            context = self._analysis_context_cache

        plugin = self._current_analysis_plugin()
        if plugin is not None:
            delivered_generation = self._analysis_context_delivered_generation_by_plugin.get(
                plugin.plugin_id,
            )
            should_push = (
                force_push
                or delivered_generation != self._analysis_context_generation
            )
            if should_push:
                try:
                    plugin.on_context_changed(context)
                except Exception:
                    pass
                else:
                    self._analysis_context_delivered_generation_by_plugin[
                        plugin.plugin_id
                    ] = self._analysis_context_generation

        self._refresh_analysis_summary()
        return context

    def _update_analysis_context(
        self,
        *,
        force_push: bool = False,
        force_rebuild: bool = False,
    ) -> None:
        """Compatibility wrapper for pushing context into the active plugin."""

        timer = getattr(self, "_analysis_context_refresh_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._ensure_analysis_context_current(
            force_push=force_push,
            force_rebuild=force_rebuild,
        )

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
                    "Scope",
                    dataset.scope_summary_value() if dataset is not None else "None",
                    level=(
                        "info"
                        if dataset is not None and dataset.scope_snapshot.root is not None
                        else "neutral"
                    ),
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
