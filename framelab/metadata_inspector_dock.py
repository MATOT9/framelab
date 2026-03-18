"""Persistent metadata inspector dock for shell-level metadata editing."""

from __future__ import annotations

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

from .dock_title_bar import DockTitleBar, should_use_custom_dock_title_bar
from .metadata_inspector_panel import MetadataInspectorPanel
from .ui_density import DensityTokens, comfortable_density_tokens


class MetadataInspectorDock(qtw.QDockWidget):
    """Right-side dock exposing metadata inspection and local editing."""

    PANEL_STATE_KEY = "metadata.inspector_dock"
    SPLITTER_STATE_KEY = "metadata.inspector_splitter.v1"

    def __init__(self, host_window: qtw.QWidget) -> None:
        super().__init__("Metadata Inspector", host_window)
        self._host_window = host_window
        self._density_tokens = comfortable_density_tokens()

        self.setObjectName("MetadataInspectorDock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setFeatures(
            qtw.QDockWidget.DockWidgetClosable
            | qtw.QDockWidget.DockWidgetMovable
            | qtw.QDockWidget.DockWidgetFloatable,
        )
        window_icon = host_window.windowIcon()
        if window_icon.isNull():
            window_icon = self.style().standardIcon(qtw.QStyle.SP_FileDialogDetailedView)
        self.setWindowIcon(window_icon)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        if should_use_custom_dock_title_bar():
            self.setTitleBarWidget(DockTitleBar(self))

        self._panel = MetadataInspectorPanel(
            host_window,
            show_header=False,
            advanced_mode=False,
            splitter_state_key=self.SPLITTER_STATE_KEY,
            parent=self,
        )
        self._panel.setObjectName("MetadataInspectorDockContent")
        self._panel.setAttribute(Qt.WA_StyledBackground, True)
        self._panel.setAutoFillBackground(True)
        self._summary_strip = self._panel._summary_strip
        self._breadcrumb = self._panel._breadcrumb
        self._node_path_label = self._panel._node_path_label
        self._effective_table = self._panel._effective_table
        self._local_table = self._panel._local_table
        self._group_status_panel = self._panel._group_status_panel
        self._group_status_layout = self._panel._group_status_layout
        self._advanced_button = self._panel._advanced_button
        self._add_field_button = self._panel._add_field_button
        self._add_group_button = self._panel._add_group_button
        self._apply_template_button = self._panel._apply_template_button
        self._promote_field_button = self._panel._promote_field_button
        self._add_local_row = self._panel._add_local_row
        self._add_ad_hoc_group = self._panel._add_ad_hoc_group
        self._apply_template = self._panel._apply_template
        self._promote_selected_field = self._panel._promote_selected_field
        self._save_local_metadata = self._panel._save_local_metadata
        self.setWidget(self._panel)
        self.visibilityChanged.connect(self._on_visibility_changed)
        self.apply_density(self._density_tokens)
        self.sync_from_host()

    def apply_density(self, tokens: DensityTokens) -> None:
        """Apply active density tokens to the dock widget."""

        self._density_tokens = tokens
        if hasattr(self._panel, "apply_density"):
            self._panel.apply_density(tokens)

    def sync_from_host(self) -> None:
        """Refresh the inspector from the host metadata/workflow state."""

        self._panel.sync_from_host()

    def reveal(self) -> None:
        """Show and focus the dock."""

        self.show()
        self.raise_()

    def _on_visibility_changed(self, visible: bool) -> None:
        """Persist dock visibility using the host panel-state store."""

        remember = getattr(self._host_window, "_remember_panel_state", None)
        if callable(remember):
            remember(self.PANEL_STATE_KEY, bool(visible))
