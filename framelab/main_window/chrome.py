"""Window chrome, menus, toolbar, and theme helpers."""

from __future__ import annotations

import sys
from dataclasses import replace
from typing import Any, Optional

from PySide6 import QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt, QSignalBlocker, QSize

from ..ebus.dialogs import (
    open_ebus_compare_dialog,
    open_ebus_datacard_wizard,
    open_ebus_inspect_dialog,
)
from ..stylesheets import (
    DARK_THEME,
    LIGHT_THEME,
    build_dark_theme,
    build_light_theme,
)

from ..help_docs import open_help_page
from ..metadata_manager_dialog import MetadataManagerDialog
from ..metadata_inspector_dock import MetadataInspectorDock
from ..native import backend as native_backend
from ..preferences_dialog import PreferencesDialog
from ..plugins import PAGE_IDS, enabled_plugin_manifests, load_enabled_plugins
from ..ui_settings import UiPreferences
from ..workflow_explorer_dock import WorkflowExplorerDock
from ..workflow_selection_dialog import WorkflowSelectionDialog
from ..workflow_manager_dialog import WorkflowManagerDialog
from ..workflow_widgets import WorkflowBreadcrumbBar


class WindowChromeMixin:
    """Menu, toolbar, theme, and workflow-shell helpers."""

    @staticmethod
    def _set_uniform_layout_margins(
        layout: qtw.QLayout | None,
        horizontal: int,
        vertical: int,
    ) -> None:
        """Apply symmetric horizontal/vertical margins to a layout."""

        if layout is None:
            return
        layout.setContentsMargins(horizontal, vertical, horizontal, vertical)

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

    def _trigger_browse_folder_action(self, _checked: bool = False) -> None:
        """Open the dataset-folder chooser from one QAction signal."""

        self.browse_folder()

    def _trigger_scan_folder_action(self, _checked: bool = False) -> None:
        """Start a dataset scan from one QAction signal."""

        self.load_folder()

    def _build_ui(self) -> None:
        dock_options = self.dockOptions() | qtw.QMainWindow.AllowNestedDocks | qtw.QMainWindow.AllowTabbedDocks
        if sys.platform.startswith("win"):
            dock_options &= ~qtw.QMainWindow.AnimatedDocks
        else:
            dock_options |= qtw.QMainWindow.AnimatedDocks
        self.setDockOptions(dock_options)
        self._build_menu_bar()
        self._build_toolbar()
        self._build_status_bar()

        central = qtw.QWidget(self)
        central.setObjectName("MainWindowCentral")
        central.setAutoFillBackground(True)
        root_layout = qtw.QVBoxLayout(central)
        self._root_layout = root_layout
        tokens = getattr(self, "_active_density_tokens", None)
        if tokens is not None:
            self._set_uniform_layout_margins(
                root_layout,
                tokens.root_margin,
                tokens.root_margin,
            )
            root_layout.setSpacing(tokens.page_spacing)
        else:
            root_layout.setContentsMargins(12, 12, 12, 12)
            root_layout.setSpacing(10)

        self.workflow_tabs = qtw.QTabWidget()
        self.workflow_tabs.setDocumentMode(True)
        context_row = qtw.QWidget()
        context_layout = qtw.QHBoxLayout(context_row)
        context_layout.setContentsMargins(0, 0, 0, 0)
        context_layout.setSpacing(8)
        self._workflow_context_row = context_row
        self._workflow_context_row_layout = context_layout
        self._workflow_context_breadcrumb = WorkflowBreadcrumbBar(compact=True)
        context_layout.addWidget(self._workflow_context_breadcrumb, 1)
        root_layout.addWidget(context_row, 0)
        self.workflow_tabs.addTab(self._build_data_page(), "1. Data")
        self.workflow_tabs.addTab(self._build_inspect_page(), "2. Measure")
        self._build_analysis_page()
        self._sync_analysis_tab_visibility()
        self.workflow_tabs.currentChanged.connect(self._on_workflow_tab_changed)
        root_layout.addWidget(self.workflow_tabs, 1)

        self.setCentralWidget(central)
        self._build_workflow_explorer_dock()
        self._build_metadata_inspector_dock()
        self._refresh_workflow_shell_context()
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
        open_workspace_action = QtGui.QAction("Open Workspace File...", self)
        open_workspace_action.setShortcut(QtGui.QKeySequence.Open)
        self._apply_help_text(
            open_workspace_action,
            "Open a saved FrameLab workspace document.",
            status="Restore workflow, scan, ROI, background, and UI state from a .framelab file.",
        )
        open_workspace_action.triggered.connect(self._open_workspace_document_from_dialog)
        file_menu.addAction(open_workspace_action)
        self.file_open_workspace_action = open_workspace_action

        save_workspace_action = QtGui.QAction("Save Workspace", self)
        save_workspace_action.setShortcut(QtGui.QKeySequence.Save)
        self._apply_help_text(
            save_workspace_action,
            "Save the current FrameLab workspace document.",
            status="Write the current reopenable session state to the active .framelab file.",
        )
        save_workspace_action.triggered.connect(
            lambda _checked=False: self._save_workspace_document(),
        )
        file_menu.addAction(save_workspace_action)
        self.file_save_workspace_action = save_workspace_action

        save_workspace_as_action = QtGui.QAction("Save Workspace As...", self)
        save_workspace_as_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+S"))
        self._apply_help_text(
            save_workspace_as_action,
            "Save the current session to a new FrameLab workspace document.",
            status="Choose where to write a .framelab workspace file for the current session.",
        )
        save_workspace_as_action.triggered.connect(
            lambda _checked=False: self._save_workspace_document_as(),
        )
        file_menu.addAction(save_workspace_as_action)
        self.file_save_workspace_as_action = save_workspace_as_action

        file_menu.addSeparator()

        open_workflow_action = QtGui.QAction("Open Workflow...", self)
        open_workflow_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+O"))
        self._apply_help_text(
            open_workflow_action,
            "Choose the active workflow profile and workspace root.",
            status="Open the workflow selector for workspace/profile context.",
        )
        open_workflow_action.triggered.connect(self._open_workflow_selection_dialog)
        file_menu.addAction(open_workflow_action)
        self.file_open_workflow_action = open_workflow_action

        open_folder_action = QtGui.QAction("Open Folder...", self)
        self._apply_help_text(
            open_folder_action,
            "Open a dataset folder from disk.",
            status="Choose the root folder that contains the TIFF dataset.",
        )
        open_folder_action.triggered.connect(self._trigger_browse_folder_action)
        file_menu.addAction(open_folder_action)
        self.file_open_folder_action = open_folder_action

        scan_action = QtGui.QAction("Scan Folder", self)
        scan_action.setShortcut(QtGui.QKeySequence("Ctrl+R"))
        self._apply_help_text(
            scan_action,
            "Scan the current dataset folder.",
            status="Rescan the current folder and refresh metadata and metrics.",
        )
        scan_action.triggered.connect(self._trigger_scan_folder_action)
        file_menu.addAction(scan_action)
        self.file_scan_scope_action = scan_action

        clear_workflow_action = QtGui.QAction("Clear Workflow Context", self)
        self._apply_help_text(
            clear_workflow_action,
            "Return to manual folder mode and clear the active workflow context.",
        )
        clear_workflow_action.triggered.connect(
            lambda _checked=False: self.set_workflow_context(None, None),
        )
        file_menu.addAction(clear_workflow_action)
        self.file_clear_workflow_action = clear_workflow_action

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

        edit_menu.addSeparator()
        preferences_action = QtGui.QAction("Preferences...", self)
        preferences_action.setShortcut(QtGui.QKeySequence.Preferences)
        self._apply_help_text(
            preferences_action,
            "Open application appearance and workspace preferences.",
        )
        preferences_action.triggered.connect(self._open_preferences_dialog)
        edit_menu.addAction(preferences_action)
        self.edit_preferences_action = preferences_action

        edit_menu.addSeparator()
        advanced_menu = edit_menu.addMenu("Advanced")
        self.edit_advanced_menu = advanced_menu

        workflow_manager_action = QtGui.QAction("Workflow Tools (Advanced)...", self)
        self._apply_help_text(
            workflow_manager_action,
            "Open advanced workflow tools for rebinding, validation, and troubleshooting.",
        )
        workflow_manager_action.triggered.connect(self._open_workflow_manager_dialog)
        advanced_menu.addAction(workflow_manager_action)
        self.edit_workflow_manager_action = workflow_manager_action

        metadata_manager_action = QtGui.QAction("Advanced Metadata Tools...", self)
        self._apply_help_text(
            metadata_manager_action,
            "Open advanced metadata tools for governance, template, and detailed maintenance work.",
        )
        metadata_manager_action.triggered.connect(self._open_metadata_manager_dialog)
        advanced_menu.addAction(metadata_manager_action)
        self.edit_metadata_manager_action = metadata_manager_action

        ebus_tools_menu = advanced_menu.addMenu("eBUS Config Tools")
        self.edit_ebus_tools_menu = ebus_tools_menu

        inspect_ebus_action = QtGui.QAction("Inspect eBUS Config File...", self)
        self._apply_help_text(
            inspect_ebus_action,
            "Open a standalone eBUS config file for read-only inspection.",
        )
        inspect_ebus_action.triggered.connect(
            lambda _checked=False: open_ebus_inspect_dialog(self),
        )
        ebus_tools_menu.addAction(inspect_ebus_action)
        self.edit_ebus_inspect_action = inspect_ebus_action

        compare_ebus_action = QtGui.QAction("Compare eBUS Configs...", self)
        self._apply_help_text(
            compare_ebus_action,
            "Compare two or more raw or effective eBUS sources.",
        )
        compare_ebus_action.triggered.connect(
            lambda _checked=False: open_ebus_compare_dialog(self),
        )
        ebus_tools_menu.addAction(compare_ebus_action)
        self.edit_ebus_compare_action = compare_ebus_action

        if "acquisition_datacard_wizard" in getattr(
            self,
            "_enabled_plugin_ids",
            frozenset(),
        ):
            ebus_tools_menu.addSeparator()
            ebus_wizard_action = QtGui.QAction("Open Datacard Wizard", self)
            self._apply_help_text(
                ebus_wizard_action,
                "Open the datacard wizard to author acquisition metadata and any eBUS-backed fields that the catalog marks as overridable.",
            )
            ebus_wizard_action.triggered.connect(
                lambda _checked=False: open_ebus_datacard_wizard(self),
            )
            ebus_tools_menu.addAction(ebus_wizard_action)
            self.edit_ebus_open_wizard_action = ebus_wizard_action

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
        self._view_menu = view_menu
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
        self._main_toolbar = toolbar

        self.toolbar_workflow_action = QtGui.QAction(
            self.style().standardIcon(qtw.QStyle.SP_FileDialogContentsView),
            "Open Workflow...",
            self,
        )
        self.toolbar_workflow_action.setToolTip(
            "Select the active workflow workspace and profile.",
        )
        self.toolbar_workflow_action.setStatusTip(
            "Open the workflow selector for workspace/profile context.",
        )
        self.toolbar_workflow_action.triggered.connect(
            self._open_workflow_selection_dialog,
        )
        toolbar.addAction(self.toolbar_workflow_action)

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
        self.toolbar_open_action.triggered.connect(self._trigger_browse_folder_action)
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
        self.toolbar_scan_action.triggered.connect(self._trigger_scan_folder_action)
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

        self.toolbar_preferences_action = QtGui.QAction(
            self.style().standardIcon(qtw.QStyle.SP_FileDialogDetailedView),
            "Preferences",
            self,
        )
        self.toolbar_preferences_action.setToolTip(
            "Open application preferences.",
        )
        self.toolbar_preferences_action.setStatusTip(
            "Adjust appearance and workspace defaults.",
        )
        self.toolbar_preferences_action.triggered.connect(self._open_preferences_dialog)
        toolbar.addAction(self.toolbar_preferences_action)

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

    def _build_workflow_explorer_dock(self) -> None:
        """Create the persistent left workflow explorer dock."""

        dock = WorkflowExplorerDock(self)
        dock.setMinimumWidth(280)
        self._workflow_explorer_dock = dock
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        visible_override = self._visibility_user_overrides().get(
            WorkflowExplorerDock.PANEL_STATE_KEY,
        )
        blocker = QSignalBlocker(dock)
        dock.setVisible(True if visible_override is None else bool(visible_override))
        del blocker
        self.resizeDocks([dock], [320], Qt.Horizontal)

        if hasattr(self, "_view_menu"):
            toggle_action = dock.toggleViewAction()
            toggle_action.setText("Workflow Explorer")
            toggle_action.setIcon(
                self.style().standardIcon(qtw.QStyle.SP_FileDialogListView),
            )
            toggle_action.setShortcut(QtGui.QKeySequence("Ctrl+Shift+W"))
            toggle_action.setShortcutContext(Qt.ApplicationShortcut)
            self._apply_help_text(
                toggle_action,
                "Show or hide the Workflow Explorer dock.",
                status="Toggle the primary workflow-navigation dock.",
            )
            self._view_menu.addAction(toggle_action)
            toggle_action.setChecked(not dock.isHidden())
            toggle_action.toggled.connect(
                lambda _checked=False: self._sync_workflow_context_row_visibility(),
            )
            self.view_workflow_explorer_action = toggle_action
            self.toolbar_workflow_explorer_action = toggle_action

        toolbar = getattr(self, "_main_toolbar", None)
        if (
            toolbar is not None
            and hasattr(self, "toolbar_open_action")
            and hasattr(self, "view_workflow_explorer_action")
        ):
            toolbar.insertAction(
                self.toolbar_open_action,
                self.view_workflow_explorer_action,
            )
        self._sync_workflow_context_row_visibility()

    def _build_metadata_inspector_dock(self) -> None:
        """Create the persistent right metadata inspector dock."""

        dock = MetadataInspectorDock(self)
        dock.setMinimumWidth(340)
        self._metadata_inspector_dock = dock
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

        visible_override = self._visibility_user_overrides().get(
            MetadataInspectorDock.PANEL_STATE_KEY,
        )
        blocker = QSignalBlocker(dock)
        dock.setVisible(False if visible_override is None else bool(visible_override))
        del blocker
        self.resizeDocks([dock], [380], Qt.Horizontal)

        if hasattr(self, "_view_menu"):
            toggle_action = dock.toggleViewAction()
            toggle_action.setText("Metadata Inspector")
            self._view_menu.addAction(toggle_action)
            toggle_action.setChecked(not dock.isHidden())
            self.view_metadata_inspector_action = toggle_action

    def _workflow_hint_for_index(self, index: int) -> str:
        """Return concise guidance message for each workflow tab."""
        if index == 0:
            return "Step 1: choose dataset folder, configure skip rules, then scan."
        if index == 1:
            return "Step 2: tune threshold/mode, inspect preview, and verify metrics."
        return "Step 3: pick an analysis plugin and run plugin-based plots/tables."

    def _on_workflow_tab_changed(self, index: int) -> None:
        """Update contextual status hint when user changes main tab."""
        self._pending_workflow_tab_index = int(index)
        timer = getattr(self, "_workflow_tab_settle_timer", None)
        if timer is not None:
            timer.start()
        else:
            self._flush_pending_workflow_tab_change()
        self.context_hint = self._workflow_hint_for_index(index)
        if hasattr(self, "_schedule_workspace_document_dirty_state_refresh"):
            self._schedule_workspace_document_dirty_state_refresh()
        else:
            self._refresh_workspace_document_dirty_state()
        self._set_status()

    def _flush_pending_workflow_tab_change(self) -> None:
        """Apply one settled main-tab transition after rapid tab switching stops."""

        if not hasattr(self, "workflow_tabs"):
            return
        index = self.workflow_tabs.currentIndex()
        self._pending_workflow_tab_index = None

        engaged = False
        if hasattr(self, "analysis_page"):
            analysis_index = self.workflow_tabs.indexOf(self.analysis_page)
            engaged = analysis_index >= 0 and index == analysis_index
        if self._analysis_plugin_engaged != engaged:
            self._analysis_plugin_engaged = engaged

        self._apply_dynamic_visibility_policy()
        if engaged and hasattr(self, "_restore_visible_analysis_layout"):
            self._restore_visible_analysis_layout()
        if engaged and hasattr(self, "_flush_dirty_analysis_context_if_visible"):
            self._flush_dirty_analysis_context_if_visible()

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
        mode_has_average = mode in {"topk", "roi", "roi_topk"}
        roi_mode_active = mode in {"roi", "roi_topk"}

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
            enabled = (
                (key not in self.MODE_MEASURE_COLUMNS or mode_has_average)
                and (key not in self.ROI_MODE_MEASURE_COLUMNS or roi_mode_active)
            )
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
        stylesheet = self._current_theme_stylesheet()
        app = qtw.QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        else:
            self.setStyleSheet(stylesheet)
        self._apply_density_to_shared_primitives()
        self.histogram_widget.set_theme(self._theme_mode)
        for plugin in self._analysis_plugins:
            plugin.set_theme(self._theme_mode)
        self._update_table_columns()
        self._update_average_controls()

    def _apply_density(self) -> None:
        """Reapply density-sensitive chrome without changing the theme mode."""

        stylesheet = self._current_theme_stylesheet()
        app = qtw.QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        else:
            self.setStyleSheet(stylesheet)
        self._apply_density_to_shared_primitives()
        self._sync_tooltip_statuses()

    def _current_theme_stylesheet(self) -> str:
        """Return the active theme stylesheet using the current density tokens."""

        tokens = getattr(self, "_active_density_tokens", None)
        if tokens is None:
            return DARK_THEME if self._theme_mode == "dark" else LIGHT_THEME
        if self._theme_mode == "dark":
            return build_dark_theme(tokens)
        return build_light_theme(tokens)

    def _apply_density_to_shared_primitives(self) -> None:
        """Apply active density tokens to layouts and shared primitives."""

        tokens = getattr(self, "_active_density_tokens", None)
        if tokens is None:
            return
        if hasattr(self, "_root_layout"):
            self._set_uniform_layout_margins(
                self._root_layout,
                tokens.root_margin,
                tokens.root_margin,
            )
            self._root_layout.setSpacing(tokens.page_spacing)
        if hasattr(self, "_apply_processing_banner_density"):
            self._apply_processing_banner_density(tokens)
        dock = getattr(self, "_workflow_explorer_dock", None)
        if dock is not None and hasattr(dock, "apply_density"):
            dock.apply_density(tokens)
        dock = getattr(self, "_metadata_inspector_dock", None)
        if dock is not None and hasattr(dock, "apply_density"):
            dock.apply_density(tokens)
        if hasattr(self, "_workflow_context_row_layout"):
            self._workflow_context_row_layout.setSpacing(tokens.panel_spacing)
        if hasattr(self, "_apply_data_page_density"):
            self._apply_data_page_density(tokens)
        if hasattr(self, "_apply_measure_page_density"):
            self._apply_measure_page_density(tokens)
        if hasattr(self, "_apply_analysis_page_density"):
            self._apply_analysis_page_density(tokens)
        compact_headers = tokens.title_pt < 20
        for header_name in ("_data_header", "_measure_header", "_analysis_header"):
            header = getattr(self, header_name, None)
            if header is None:
                continue
            if hasattr(header, "apply_density"):
                header.apply_density(tokens)
            if hasattr(header, "set_compact_chip_mode"):
                header.set_compact_chip_mode(compact_headers)
        for strip_name in (
            "_data_summary_strip",
            "_measure_summary_strip",
            "_analysis_summary_strip",
        ):
            strip = getattr(self, strip_name, None)
            if strip is not None and hasattr(strip, "apply_density"):
                strip.apply_density(tokens)

    def _on_theme_changed(self, mode: str) -> None:
        self._apply_theme(mode)
        self._sync_view_theme_actions()

    def _current_ui_preferences(self) -> UiPreferences:
        """Return the current effective UI preferences."""

        return replace(
            self.ui_preferences,
            theme_mode=self._theme_mode,
            show_image_preview=bool(self.show_image_preview),
            show_histogram_preview=bool(self.show_histogram_preview),
        )

    def _preview_preferences_updated(self, prefs: UiPreferences) -> None:
        """Apply live preference preview without persisting changes."""

        self._apply_ui_preferences(prefs, persist=False)

    def _on_preferences_updated(self, prefs: UiPreferences) -> None:
        """Apply and persist preferences from the dialog."""

        self._apply_ui_preferences(prefs, persist=True)

    def _apply_ui_preferences(
        self,
        prefs: UiPreferences,
        *,
        persist: bool,
    ) -> None:
        """Apply UI preference changes to the live window."""

        previous = self._current_ui_preferences()
        self.ui_preferences = replace(prefs)
        native_backend.configure_raw_runtime(
            use_mmap_for_raw=self.ui_preferences.use_mmap_for_raw,
            enable_raw_simd=self.ui_preferences.enable_raw_simd,
        )

        theme_changed = previous.theme_mode != prefs.theme_mode
        preview_changed = (
            previous.show_image_preview != prefs.show_image_preview
            or previous.show_histogram_preview != prefs.show_histogram_preview
        )

        if theme_changed:
            self._apply_theme(prefs.theme_mode)
        else:
            self._sync_view_theme_actions()

        if preview_changed:
            self.show_image_preview = prefs.show_image_preview
            self.show_histogram_preview = prefs.show_histogram_preview
            self._on_preview_visibility_changed()
        else:
            self._apply_dynamic_visibility_policy()

        if persist:
            self.ui_state_snapshot.preferences = replace(self.ui_preferences)
            self._save_ui_state()

    def _open_preferences_dialog(self) -> None:
        """Open the Preferences dialog and apply accepted changes."""

        snapshot = replace(
            self.ui_state_snapshot,
            preferences=self._current_ui_preferences(),
        )
        dialog = PreferencesDialog(snapshot, self)
        dialog.preferences_changed.connect(self._preview_preferences_updated)
        if dialog.exec() == qtw.QDialog.Accepted:
            self._on_preferences_updated(dialog.current_preferences())

    def _refresh_workflow_shell_context(self) -> None:
        """Sync the shell breadcrumb row with the current workflow context."""

        if not hasattr(self, "_workflow_context_breadcrumb"):
            return
        controller = getattr(self, "workflow_state_controller", None)
        profile = controller.profile if controller is not None else None
        active_node = controller.active_node() if controller is not None else None
        ancestry = (
            controller.ancestry_for(active_node.node_id)
            if controller is not None and active_node is not None
            else ()
        )
        nodes = tuple(
            (
                node.display_name,
                f"{node.type_id.replace('_', ' ').title()}: {node.folder_path}",
            )
            for node in ancestry
        )
        self._workflow_context_breadcrumb.set_breadcrumb(
            profile_label=profile.display_name if profile is not None else None,
            context_label=(
                controller.anchor_summary_label()
                if controller is not None and controller.is_partial_workspace()
                else None
            ),
            nodes=nodes,
            empty_text="No workflow selected",
        )
        has_workflow = bool(profile is not None)
        if hasattr(self, "file_clear_workflow_action"):
            self.file_clear_workflow_action.setEnabled(has_workflow)
        self._sync_scope_action_labels()
        self._sync_workflow_context_row_visibility()

    def _sync_workflow_context_row_visibility(self) -> None:
        """Show the fallback workflow breadcrumb only when the explorer is hidden."""

        row = getattr(self, "_workflow_context_row", None)
        if row is None:
            return
        toggle_action = getattr(self, "view_workflow_explorer_action", None)
        if isinstance(toggle_action, QtGui.QAction) and toggle_action.isCheckable():
            show_row = not toggle_action.isChecked()
        else:
            dock = getattr(self, "_workflow_explorer_dock", None)
            show_row = dock is None or dock.isHidden()
        row.setVisible(show_row)

    def _sync_scope_action_labels(self) -> None:
        """Keep folder/scope affordances subordinate to workflow context."""

        controller = getattr(self, "workflow_state_controller", None)
        active_node = controller.active_node() if controller is not None else None
        has_workflow = active_node is not None
        scope_name = active_node.display_name if active_node is not None else "current folder"

        workflow_button_text = "Switch Workflow..." if has_workflow else "Open Workflow..."
        if hasattr(self, "toolbar_workflow_action"):
            self.toolbar_workflow_action.setText(workflow_button_text)
            self.toolbar_workflow_action.setToolTip(
                "Switch the active workflow workspace and profile."
                if has_workflow
                else "Choose the active workflow profile and workspace root.",
            )
        if hasattr(self, "file_open_workflow_action"):
            self.file_open_workflow_action.setText(workflow_button_text)

        open_text = "Browse Scope Folder..." if has_workflow else "Open Folder..."
        open_tooltip = (
            f"Choose a folder for the selected workflow scope ({scope_name})."
            if has_workflow
            else "Open a dataset folder from disk."
        )
        open_status = (
            "Choose a folder to align or temporarily override the selected workflow scope."
            if has_workflow
            else "Choose the root folder that contains the TIFF dataset."
        )
        scan_text = "Scan Selected Scope" if has_workflow else "Scan Folder"
        scan_tooltip = (
            f"Scan data for the selected workflow scope ({scope_name})."
            if has_workflow
            else "Scan the current dataset folder."
        )
        scan_status = (
            "Scan the folder currently implied by the selected workflow node."
            if has_workflow
            else "Rescan the current folder and refresh metadata and metrics."
        )
        for action_name in ("file_open_folder_action", "toolbar_open_action"):
            action = getattr(self, action_name, None)
            if action is None:
                continue
            action.setText(open_text)
            action.setToolTip(open_tooltip)
            action.setStatusTip(open_status)
        for action_name in ("file_scan_scope_action", "toolbar_scan_action"):
            action = getattr(self, action_name, None)
            if action is None:
                continue
            action.setText(scan_text)
            action.setToolTip(scan_tooltip)
            action.setStatusTip(scan_status)

        label = getattr(self, "_data_scope_label", None)
        if label is not None:
            label.setText("Scope" if has_workflow else "Dataset")
        folder_edit = getattr(self, "folder_edit", None)
        if folder_edit is not None:
            folder_edit.setPlaceholderText(
                "Selected workflow node folder"
                if has_workflow
                else "Select folder containing TIFF files",
            )
            folder_edit.setToolTip(
                f"Current selected workflow scope: {scope_name}."
                if has_workflow
                else "Root folder to scan recursively for TIFF images.",
            )
        browse_button = getattr(self, "_data_browse_button", None)
        if browse_button is not None:
            browse_button.setText("Browse Scope..." if has_workflow else "Browse Folder...")
            browse_button.setToolTip(open_tooltip)
        load_button = getattr(self, "_data_load_button", None)
        if load_button is not None:
            load_button.setText(scan_text)
            load_button.setToolTip(scan_tooltip)

    def _open_workflow_selection_dialog(self) -> None:
        """Open the dedicated workflow selector dialog."""

        dialog = WorkflowSelectionDialog(self)
        dialog.exec()
        self._refresh_workflow_shell_context()

    def _reveal_metadata_inspector_dock(self) -> None:
        """Show and focus the persistent metadata inspector dock."""

        dock = getattr(self, "_metadata_inspector_dock", None)
        if dock is None:
            return
        if hasattr(dock, "reveal"):
            dock.reveal()
            return
        dock.show()
        dock.raise_()

    def _open_workflow_manager_dialog(self) -> None:
        """Open or focus the non-modal workflow manager dialog."""

        dialog = getattr(self, "_workflow_manager_dialog", None)
        if isinstance(dialog, WorkflowManagerDialog):
            dialog.sync_from_host()
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return

        dialog = WorkflowManagerDialog(self)
        setattr(self, "_workflow_manager_dialog", dialog)
        dialog.destroyed.connect(
            lambda _obj=None, host=self: setattr(host, "_workflow_manager_dialog", None),
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _open_metadata_manager_dialog(self) -> None:
        """Open or focus the non-modal metadata manager dialog."""

        dialog = getattr(self, "_metadata_manager_dialog", None)
        if isinstance(dialog, MetadataManagerDialog):
            dialog.sync_from_host()
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return

        dialog = MetadataManagerDialog(self)
        setattr(self, "_metadata_manager_dialog", dialog)
        dialog.destroyed.connect(
            lambda _obj=None, host=self: setattr(host, "_metadata_manager_dialog", None),
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
