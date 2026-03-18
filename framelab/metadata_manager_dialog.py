"""Detached metadata manager dialog built on the shared inspector panel."""

from __future__ import annotations

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

from .metadata_inspector_panel import MetadataInspectorPanel
from .window_drag import apply_secondary_window_geometry, configure_secondary_window


class MetadataManagerDialog(qtw.QDialog):
    """Advanced metadata dialog kept secondary to the dock inspector."""

    def __init__(self, host_window: qtw.QWidget) -> None:
        super().__init__(host_window)
        self._host_window = host_window

        self.setWindowTitle("Advanced Metadata Tools")
        configure_secondary_window(self)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumSize(980, 640)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._panel = MetadataInspectorPanel(
            host_window,
            show_header=True,
            advanced_mode=True,
            parent=self,
        )
        self._panel._header.set_title("Advanced Metadata Tools")
        self._panel._header.set_subtitle(
            "Use the Metadata Inspector dock for everyday editing. This window is "
            "for governance, templates, and deeper metadata maintenance.",
        )
        layout.addWidget(self._panel, 1)

        actions = qtw.QHBoxLayout()
        actions.addStretch(1)
        close_button = qtw.QPushButton("Close")
        close_button.clicked.connect(self.close)
        actions.addWidget(close_button)
        layout.addLayout(actions)

        # Compatibility aliases so existing tests and helper code can still
        # interact with the dialog the same way.
        self._header = self._panel._header
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
        self._remove_field_button = self._panel._remove_field_button
        self._revert_button = self._panel._revert_button
        self._refresh_button = self._panel._refresh_button
        self._save_button = self._panel._save_button
        self._add_local_row = self._panel._add_local_row
        self._add_ad_hoc_group = self._panel._add_ad_hoc_group
        self._apply_template = self._panel._apply_template
        self._promote_selected_field = self._panel._promote_selected_field
        self._remove_selected_local_rows = self._panel._remove_selected_local_rows
        self._collect_local_metadata = self._panel._collect_local_metadata
        self._save_local_metadata = self._panel._save_local_metadata
        apply_secondary_window_geometry(
            self,
            preferred_size=(1180, 760),
            host_window=host_window,
        )

    def sync_from_host(self) -> None:
        """Refresh effective and local metadata from the active workflow node."""

        self._panel.sync_from_host()
