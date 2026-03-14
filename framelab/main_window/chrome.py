"""Window chrome, menus, toolbar, and theme helpers."""

from __future__ import annotations

from typing import Any, Optional

from PySide6 import QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt, QSignalBlocker, QSize

from stylesheets import DARK_THEME, LIGHT_THEME

from ..help_docs import open_help_page
from ..plugins import PAGE_IDS, enabled_plugin_manifests, load_enabled_plugins


class WindowChromeMixin:
    """Menu, toolbar, theme, and workflow-shell helpers."""

    def _apply_base_font(self) -> None:
        preferred = (
            "Aptos",
            "Arial",
            "Cantarell",
            "Helvetica Neue",
            "Inter",
            "Noto Sans",
            "Roboto",
            "Segoe UI Variable",
            "Segoe UI",
            "SF Pro Text",
            "Ubuntu",
        )
        families = QtGui.QFontDatabase.families()
        available = {name.lower(): name for name in families}
        for family in preferred:
            hit = available.get(family.lower())
            if hit:
                self.setFont(QtGui.QFont(hit, 10))
                return
        self.setFont(QtGui.QFont(self.font().family(), 10))

    @staticmethod
    def _apply_help_text(
        target: Any,
        tooltip: str,
        *,
        status: Optional[str] = None,
    ) -> None:
        text = " ".join(tooltip.split())
        status_text = " ".join((status or tooltip).split())
        if hasattr(target, "setToolTip"):
            target.setToolTip(text)
        if hasattr(target, "setStatusTip"):
            target.setStatusTip(status_text)

    def _sync_tooltip_statuses(self) -> None:
        for widget in self.findChildren(qtw.QWidget):
            tooltip = widget.toolTip().strip()
            status = widget.statusTip().strip()
            if tooltip and not status:
                widget.setStatusTip(tooltip)
            elif status and not tooltip:
                widget.setToolTip(status)
        for action in self.findChildren(QtGui.QAction):
            tooltip = action.toolTip().strip()
            status = action.statusTip().strip()
            if tooltip and not status:
                action.setStatusTip(tooltip)
            elif status and not tooltip:
                action.setToolTip(status)

    def _build_ui(self) -> None:
        self._build_menu_bar()
        self._build_toolbar()
        self._build_status_bar()

        central = qtw.QWidget(self)
        central.setObjectName("MainWindowCentral")
        central.setAutoFillBackground(True)
        root_layout = qtw.QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self.workflow_tabs = qtw.QTabWidget()
        self.workflow_tabs.setDocumentMode(True)
        self.workflow_tabs.addTab(self._build_data_page(), "1. Data")
        self.workflow_tabs.addTab(self._build_inspect_page(), "2. Measure")
        self._build_analysis_page()
        self._sync_analysis_tab_visibility()
        self.workflow_tabs.currentChanged.connect(self._on_workflow_tab_changed)
        root_layout.addWidget(self.workflow_tabs, 1)

        self.setCentralWidget(central)
        self._apply_dynamic_visibility_policy()
        self._sync_tooltip_statuses()

    def _sync_analysis_tab_visibility(self) -> None:
        """Show Analysis tab only when at least one plugin is loaded."""
        if not hasattr(self, "workflow_tabs") or not hasattr(self, "analysis_page"):
            return

        has_plugins = len(self._analysis_plugins) > 0
        tab_index = self.workflow_tabs.indexOf(self.analysis_page)
        if has_plugins and tab_index < 0:
            self.workflow_tabs.addTab(self.analysis_page, "3. Analyze")
            return

        if not has_plugins and tab_index >= 0:
            is_current = self.workflow_tabs.currentIndex() == tab_index
            self.workflow_tabs.removeTab(tab_index)
            if is_current and self.workflow_tabs.count() > 0:
                self.workflow_tabs.setCurrentIndex(0)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        open_folder_action = QtGui.QAction("Open Folder...", self)
        open_folder_action.setShortcut(QtGui.QKeySequence.Open)
        self._apply_help_text(
            open_folder_action,
            "Open a dataset folder from disk.",
            status="Choose the root folder that contains the TIFF dataset.",
        )
        open_folder_action.triggered.connect(
            lambda _checked=False: self.browse_folder(),
        )
        file_menu.addAction(open_folder_action)

        scan_action = QtGui.QAction("Scan Folder", self)
        scan_action.setShortcut(QtGui.QKeySequence("Ctrl+R"))
        self._apply_help_text(
            scan_action,
            "Scan the current dataset folder.",
            status="Rescan the current folder and refresh metadata and metrics.",
        )
        scan_action.triggered.connect(lambda _checked=False: self.load_folder())
        file_menu.addAction(scan_action)

        file_menu.addSeparator()

        export_menu = file_menu.addMenu("&Export")
        export_metrics_action = QtGui.QAction("Image Metrics Table...", self)
        export_metrics_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+E"))
        self._apply_help_text(
            export_metrics_action,
            "Export the current metrics table.",
            status="Write the displayed image metrics table to a file.",
        )
        export_metrics_action.triggered.connect(self._export_metrics_table)
        export_menu.addAction(export_metrics_action)

        file_menu.addSeparator()
        quit_action = QtGui.QAction("Quit", self)
        quit_action.setShortcut(QtGui.QKeySequence.Quit)
        self._apply_help_text(
            quit_action,
            "Close FrameLab.",
        )
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        edit_menu = menu_bar.addMenu("&Edit")
        copy_action = QtGui.QAction("Copy Selected Cells", self)
        copy_action.setShortcut(QtGui.QKeySequence.Copy)
        self._apply_help_text(
            copy_action,
            "Copy the selected table cells.",
        )
        copy_action.triggered.connect(self._copy_table_selection)
        edit_menu.addAction(copy_action)

        select_all_action = QtGui.QAction("Select All Metrics Cells", self)
        select_all_action.setShortcut(QtGui.QKeySequence.SelectAll)
        self._apply_help_text(
            select_all_action,
            "Select every visible cell in the active metrics table.",
        )
        select_all_action.triggered.connect(self._select_all_table_cells)
        edit_menu.addAction(select_all_action)

        view_menu = menu_bar.addMenu("&View")
        preview_menu = view_menu.addMenu("Preview")
        self.view_image_action = QtGui.QAction("Show Image Preview", self)
        self.view_image_action.setCheckable(True)
        self.view_image_action.setChecked(self.show_image_preview)
        self._apply_help_text(
            self.view_image_action,
            "Show or hide the image preview panel.",
        )
        self.view_image_action.triggered.connect(
            self._on_view_image_action_toggled,
        )
        preview_menu.addAction(self.view_image_action)

        self.view_histogram_action = QtGui.QAction("Show Histogram", self)
        self.view_histogram_action.setCheckable(True)
        self.view_histogram_action.setChecked(self.show_histogram_preview)
        self._apply_help_text(
            self.view_histogram_action,
            "Show or hide the histogram panel.",
        )
        self.view_histogram_action.triggered.connect(
            self._on_view_hist_action_toggled,
        )
        preview_menu.addAction(self.view_histogram_action)

        view_menu.addSeparator()
        columns_menu = view_menu.addMenu("Columns")
        self.data_columns_menu = columns_menu.addMenu("Data Table")
        self.measure_columns_menu = columns_menu.addMenu("Measure Table")
        self._build_column_visibility_menu_actions()
        columns_menu.addSeparator()
        reset_columns_action = QtGui.QAction("Reset Column Layout", self)
        self._apply_help_text(
            reset_columns_action,
            "Reset hidden and reordered columns to the default layout.",
        )
        reset_columns_action.triggered.connect(
            lambda _checked=False: self._reset_column_layout(),
        )
        columns_menu.addAction(reset_columns_action)

        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("Theme")
        theme_action_group = QtGui.QActionGroup(self)
        theme_action_group.setExclusive(True)

        self.view_theme_light_action = QtGui.QAction("Light", self)
        self.view_theme_light_action.setCheckable(True)
        self._apply_help_text(
            self.view_theme_light_action,
            "Switch the app to the light theme.",
        )
        self.view_theme_light_action.triggered.connect(
            lambda _checked=False: self._on_view_theme_selected("light"),
        )
        theme_action_group.addAction(self.view_theme_light_action)
        theme_menu.addAction(self.view_theme_light_action)

        self.view_theme_dark_action = QtGui.QAction("Dark", self)
        self.view_theme_dark_action.setCheckable(True)
        self._apply_help_text(
            self.view_theme_dark_action,
            "Switch the app to the dark theme.",
        )
        self.view_theme_dark_action.triggered.connect(
            lambda _checked=False: self._on_view_theme_selected("dark"),
        )
        theme_action_group.addAction(self.view_theme_dark_action)
        theme_menu.addAction(self.view_theme_dark_action)
        self._sync_view_theme_actions()

        self.plugins_menu = menu_bar.addMenu("&Plugins")
        self._populate_plugins_menu_entries()

        help_menu = menu_bar.addMenu("&Help")
        docs_home_action = QtGui.QAction("Documentation Home", self)
        self._apply_help_text(
            docs_home_action,
            "Open the offline documentation home page.",
        )
        docs_home_action.triggered.connect(
            lambda _checked=False: self._open_help_page("home"),
        )
        help_menu.addAction(docs_home_action)

        quick_start_action = QtGui.QAction("Quick Start", self)
        self._apply_help_text(
            quick_start_action,
            "Open the quick-start guide.",
        )
        quick_start_action.triggered.connect(
            lambda _checked=False: self._open_help_page("quick_start"),
        )
        help_menu.addAction(quick_start_action)

        user_guide_action = QtGui.QAction("User Guide", self)
        self._apply_help_text(
            user_guide_action,
            "Open the user guide landing page.",
        )
        user_guide_action.triggered.connect(
            lambda _checked=False: self._open_help_page("user_guide"),
        )
        help_menu.addAction(user_guide_action)

        developer_guide_action = QtGui.QAction("Developer Guide", self)
        self._apply_help_text(
            developer_guide_action,
            "Open the developer guide landing page.",
        )
        developer_guide_action.triggered.connect(
            lambda _checked=False: self._open_help_page("developer_guide"),
        )
        help_menu.addAction(developer_guide_action)

        plugin_guide_action = QtGui.QAction("Plugin Guide", self)
        self._apply_help_text(
            plugin_guide_action,
            "Open the plugin guide and selector documentation.",
        )
        plugin_guide_action.triggered.connect(
            lambda _checked=False: self._open_help_page("plugin_guide"),
        )
        help_menu.addAction(plugin_guide_action)

        reference_action = QtGui.QAction("Reference", self)
        self._apply_help_text(
            reference_action,
            "Open the reference documentation.",
        )
        reference_action.triggered.connect(
            lambda _checked=False: self._open_help_page("reference"),
        )
        help_menu.addAction(reference_action)

        troubleshooting_action = QtGui.QAction("Troubleshooting", self)
        self._apply_help_text(
            troubleshooting_action,
            "Open the troubleshooting guide.",
        )
        troubleshooting_action.triggered.connect(
            lambda _checked=False: self._open_help_page("troubleshooting"),
        )
        help_menu.addAction(troubleshooting_action)

        keyboard_action = QtGui.QAction("Keyboard Shortcuts", self)
        self._apply_help_text(
            keyboard_action,
            "Open the keyboard shortcut reference page.",
        )
        keyboard_action.triggered.connect(
            lambda _checked=False: self._open_help_page("keyboard_shortcuts"),
        )
        help_menu.addAction(keyboard_action)

        help_menu.addSeparator()
        about_action = QtGui.QAction("About", self)
        self._apply_help_text(
            about_action,
            "Show basic application information.",
        )
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _build_toolbar(self) -> None:
        toolbar = qtw.QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        self.toolbar_open_action = QtGui.QAction(
            self.style().standardIcon(qtw.QStyle.SP_DirOpenIcon),
            "Open Folder...",
            self,
        )
        self.toolbar_open_action.setToolTip(
            "Select the root folder that contains TIFF images.",
        )
        self.toolbar_open_action.setStatusTip(
            "Open a dataset folder, then run Scan to populate tables.",
        )
        self.toolbar_open_action.triggered.connect(
            lambda _checked=False: self.browse_folder(),
        )
        toolbar.addAction(self.toolbar_open_action)

        self.toolbar_scan_action = QtGui.QAction(
            self.style().standardIcon(qtw.QStyle.SP_BrowserReload),
            "Scan Folder",
            self,
        )
        self.toolbar_scan_action.setToolTip(
            "Rescan the current folder and refresh metrics/metadata.",
        )
        self.toolbar_scan_action.setStatusTip(
            "Reload current dataset folder and recompute displayed metrics.",
        )
        self.toolbar_scan_action.triggered.connect(
            lambda _checked=False: self.load_folder(),
        )
        toolbar.addAction(self.toolbar_scan_action)

        self.toolbar_export_action = QtGui.QAction(
            self.style().standardIcon(qtw.QStyle.SP_DialogSaveButton),
            "Export Metrics",
            self,
        )
        self.toolbar_export_action.setToolTip(
            "Export the visible image metrics table.",
        )
        self.toolbar_export_action.setStatusTip(
            "Write the current image metrics table to disk.",
        )
        self.toolbar_export_action.triggered.connect(self._export_metrics_table)
        toolbar.addAction(self.toolbar_export_action)

        self.toolbar_reload_plugins_action = QtGui.QAction(
            self.style().standardIcon(qtw.QStyle.SP_BrowserReload),
            "Reload Plugins",
            self,
        )
        self.toolbar_reload_plugins_action.setToolTip(
            "Reload the currently enabled plugins.",
        )
        self.toolbar_reload_plugins_action.setStatusTip(
            "Rebuild plugin registrations and refresh plugin menus.",
        )
        self.toolbar_reload_plugins_action.triggered.connect(
            lambda _checked=False: self._reload_all_page_plugins(),
        )
        toolbar.addAction(self.toolbar_reload_plugins_action)

        toolbar.addSeparator()

        spacer = qtw.QWidget()
        spacer.setSizePolicy(
            qtw.QSizePolicy.Expanding,
            qtw.QSizePolicy.Preferred,
        )
        toolbar.addWidget(spacer)

        self.toolbar_help_action = QtGui.QAction(
            self.style().standardIcon(qtw.QStyle.SP_DialogHelpButton),
            "Docs",
            self,
        )
        self.toolbar_help_action.setToolTip(
            "Open the offline documentation home page.",
        )
        self.toolbar_help_action.setStatusTip(
            "Open the bundled documentation landing page.",
        )
        self.toolbar_help_action.triggered.connect(
            lambda _checked=False: self._open_help_page("home"),
        )
        toolbar.addAction(self.toolbar_help_action)

    def _build_status_bar(self) -> None:
        status = qtw.QStatusBar(self)
        self.setStatusBar(status)

    def _workflow_hint_for_index(self, index: int) -> str:
        """Return concise guidance message for each workflow tab."""
        if index == 0:
            return "Step 1: choose dataset folder, configure skip rules, then scan."
        if index == 1:
            return "Step 2: tune threshold/mode, inspect preview, and verify metrics."
        return "Step 3: pick an analysis plugin and run plugin-based plots/tables."

    def _on_workflow_tab_changed(self, index: int) -> None:
        """Update contextual status hint when user changes main tab."""
        if hasattr(self, "analysis_page") and hasattr(self, "workflow_tabs"):
            analysis_index = self.workflow_tabs.indexOf(self.analysis_page)
            engaged = analysis_index >= 0 and index == analysis_index
            if self._analysis_plugin_engaged != engaged:
                self._analysis_plugin_engaged = engaged
                if not engaged:
                    self._metadata_controls_auto_expanded = False
                self._apply_dynamic_visibility_policy()
        self.context_hint = self._workflow_hint_for_index(index)
        self._set_status()

    def _copy_table_selection(self) -> None:
        """Copy selected metrics-table cells to clipboard."""
        if hasattr(self, "table"):
            self.table.copy_selection_to_clipboard()

    def _select_all_table_cells(self) -> None:
        """Select all cells in the metrics table."""
        if hasattr(self, "table"):
            self.table.selectAll()

    def _on_view_image_action_toggled(self, checked: bool) -> None:
        """Toggle image preview visibility from View menu."""
        if self.show_image_preview == checked:
            return
        self.show_image_preview = bool(checked)
        self._on_preview_visibility_changed()

    def _on_view_hist_action_toggled(self, checked: bool) -> None:
        """Toggle histogram preview visibility from View menu."""
        if self.show_histogram_preview == checked:
            return
        self.show_histogram_preview = bool(checked)
        self._on_preview_visibility_changed()

    def _build_column_visibility_menu_actions(self) -> None:
        """Build checkable View->Columns actions for optional table columns."""
        self._data_column_actions = {}
        self._measure_column_actions = {}
        if not hasattr(self, "data_columns_menu") or not hasattr(
            self,
            "measure_columns_menu",
        ):
            return

        for key, label in self.DATA_OPTIONAL_COLUMNS:
            action = QtGui.QAction(label, self)
            action.setCheckable(True)
            action.toggled.connect(
                lambda checked, column_key=key: self._on_data_column_action_toggled(
                    column_key,
                    checked,
                ),
            )
            self.data_columns_menu.addAction(action)
            self._data_column_actions[key] = action

        for key, label in self.MEASURE_OPTIONAL_COLUMNS:
            action = QtGui.QAction(label, self)
            action.setCheckable(True)
            action.toggled.connect(
                lambda checked, column_key=key: self._on_measure_column_action_toggled(
                    column_key,
                    checked,
                ),
            )
            self.measure_columns_menu.addAction(action)
            self._measure_column_actions[key] = action

    def _on_data_column_action_toggled(self, key: str, checked: bool) -> None:
        """Store manual override for one optional Data-table column."""
        self._manual_data_column_visibility[key] = bool(checked)
        self._apply_data_table_visibility()
        self._sync_column_menu_actions()

    def _on_measure_column_action_toggled(self, key: str, checked: bool) -> None:
        """Store manual override for one optional Measure-table column."""
        self._manual_measure_column_visibility[key] = bool(checked)
        self._apply_measure_table_visibility()
        self._sync_column_menu_actions()

    def _reset_column_layout(self) -> None:
        """Clear manual column overrides and restore policy-driven visibility."""
        self._manual_data_column_visibility.clear()
        self._manual_measure_column_visibility.clear()
        self._apply_dynamic_visibility_policy()

    def _sync_column_menu_actions(self) -> None:
        """Sync View->Columns checkboxes with current table visibility."""
        mode = self._current_average_mode()
        mode_has_average = mode in {"topk", "roi"}

        for key, action in self._data_column_actions.items():
            if hasattr(self, "metadata_table"):
                col = self.DATA_COLUMN_INDEX[key]
                checked = not self.metadata_table.isColumnHidden(col)
            else:
                checked = self._manual_data_column_visibility.get(key, False)
            blocker = QSignalBlocker(action)
            action.setChecked(checked)
            action.setEnabled(True)
            del blocker

        for key, action in self._measure_column_actions.items():
            if hasattr(self, "table"):
                col = self.MEASURE_COLUMN_INDEX[key]
                checked = not self.table.isColumnHidden(col)
            else:
                checked = self._manual_measure_column_visibility.get(key, False)
            enabled = key not in self.MODE_MEASURE_COLUMNS or mode_has_average
            blocker = QSignalBlocker(action)
            action.setChecked(checked)
            action.setEnabled(enabled)
            del blocker

    def _on_view_theme_selected(self, mode: str) -> None:
        """Handle theme switch request from View menu theme submenu."""
        if self._theme_mode == mode:
            return
        self._on_theme_changed(mode)

    def _sync_view_theme_actions(self) -> None:
        """Sync check state for View->Theme menu entries."""
        if not hasattr(self, "view_theme_light_action"):
            return
        is_dark = self._theme_mode == "dark"
        light_block = QSignalBlocker(self.view_theme_light_action)
        dark_block = QSignalBlocker(self.view_theme_dark_action)
        self.view_theme_light_action.setChecked(not is_dark)
        self.view_theme_dark_action.setChecked(is_dark)
        del light_block
        del dark_block

    def _open_help_page(self, page_key: str) -> None:
        """Open one bundled offline help page."""
        open_help_page(self, page_key)

    def _show_about_dialog(self) -> None:
        """Display short About dialog."""
        self._show_info(
            "About FrameLab",
            (
                "FrameLab\n\n"
                "Desktop workflow tool for image dataset scanning, measurement, "
                "plugin-driven analysis, and acquisition datacard authoring.\n\n"
                "Use Help for the bundled offline documentation set."
            ),
        )

    def _reload_enabled_plugin_classes(self) -> None:
        """Reload enabled plugin classes from manifest metadata."""
        self._page_plugin_manifests = enabled_plugin_manifests(
            self._enabled_plugin_ids,
        )
        self._page_plugin_classes = load_enabled_plugins(self._enabled_plugin_ids)

    def _plugin_classes_for_page(self, page: str) -> list[type[object]]:
        """Return loaded plugin classes for one workflow page."""
        return list(self._page_plugin_classes.get(page, ()))

    def _plugin_manifests_for_page(self, page: str) -> list[object]:
        """Return enabled plugin manifests for one workflow page."""
        return list(self._page_plugin_manifests.get(page, ()))

    def _reload_all_page_plugins(self) -> None:
        """Reload plugin classes/instances for all workflow pages."""
        self._reload_enabled_plugin_classes()
        self._load_analysis_plugins()
        self._populate_plugins_menu_entries()

    def _populate_plugins_menu_entries(self) -> None:
        """Rebuild Plugins menu with page-specific plugin submenus."""
        if not hasattr(self, "plugins_menu"):
            return
        self.plugins_menu.clear()

        reload_plugins_action = QtGui.QAction("Reload All Page Plugins", self)
        self._apply_help_text(
            reload_plugins_action,
            "Reload the currently enabled plugins.",
            status="Rebuild menus and refresh registrations for enabled plugins.",
        )
        reload_plugins_action.triggered.connect(
            lambda _checked=False: self._reload_all_page_plugins(),
        )
        self.plugins_menu.addAction(reload_plugins_action)

        page_sections = {
            "data": "Data Page",
            "measure": "Measure Page",
            "analysis": "Analyze Page",
        }
        analysis_instance_by_id = {
            plugin.plugin_id: plugin for plugin in self._analysis_plugins
        }
        for page_id in PAGE_IDS:
            page_title = page_sections[page_id]
            page_menu = self.plugins_menu.addMenu(page_title)
            plugin_classes = self._plugin_classes_for_page(page_id)
            plugin_class_by_id = {
                str(getattr(plugin_cls, "plugin_id", "")): plugin_cls
                for plugin_cls in plugin_classes
            }
            manifests = self._plugin_manifests_for_page(page_id)
            if not manifests:
                no_plugins_action = QtGui.QAction("No plugins enabled", self)
                no_plugins_action.setEnabled(False)
                page_menu.addAction(no_plugins_action)
                continue

            for manifest in manifests:
                plugin_cls = plugin_class_by_id.get(manifest.plugin_id)
                plugin_menu = page_menu.addMenu(manifest.display_name)

                if page_id != "analysis":
                    if plugin_cls is None:
                        failed_action = QtGui.QAction("Plugin failed to load", self)
                        failed_action.setEnabled(False)
                        plugin_menu.addAction(failed_action)
                        continue
                    populate_fn = getattr(plugin_cls, "populate_page_menu", None)
                    if callable(populate_fn):
                        try:
                            populate_fn(self, plugin_menu)
                        except Exception as exc:
                            failed_action = QtGui.QAction(
                                f"Failed to load actions: {exc}",
                                self,
                            )
                            failed_action.setEnabled(False)
                            plugin_menu.addAction(failed_action)
                    else:
                        placeholder = QtGui.QAction(
                            "Runtime actions for this page will appear here.",
                            self,
                        )
                        placeholder.setEnabled(False)
                        plugin_menu.addAction(placeholder)
                    continue

                analysis_instance = analysis_instance_by_id.get(manifest.plugin_id)
                if analysis_instance is None:
                    unavailable = QtGui.QAction("Plugin not active", self)
                    unavailable.setEnabled(False)
                    plugin_menu.addAction(unavailable)
                    continue

                analysis_instance.populate_menu(plugin_menu)
                if plugin_menu.isEmpty():
                    placeholder = QtGui.QAction(
                        "No runtime actions available.",
                        self,
                    )
                    placeholder.setEnabled(False)
                    plugin_menu.addAction(placeholder)
        self._sync_tooltip_statuses()

    def _apply_theme(self, mode: str) -> None:
        self._theme_mode = "dark" if mode == "dark" else "light"
        stylesheet = DARK_THEME if self._theme_mode == "dark" else LIGHT_THEME
        app = qtw.QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        else:
            self.setStyleSheet(stylesheet)
        self.histogram_widget.set_theme(self._theme_mode)
        for plugin in self._analysis_plugins:
            plugin.set_theme(self._theme_mode)
        self._update_table_columns()
        self._update_average_controls()

    def _on_theme_changed(self, mode: str) -> None:
        self._apply_theme(mode)
        self._sync_view_theme_actions()
