"""Measure-page plugin for background correction authoring."""

from __future__ import annotations

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import QSignalBlocker

from ..registry import register_page_plugin
from ...ui_primitives import SummaryItem, build_page_header, build_summary_strip
from ...window_drag import enable_window_content_drag


class BackgroundCorrectionDialog(qtw.QDialog):
    """Dialog for configuring background correction on the Measure page."""

    def __init__(self, host_window: qtw.QWidget) -> None:
        super().__init__(host_window)
        self._host_window = host_window

        self.setWindowTitle("Background Correction")
        self.setModal(True)
        self.resize(900, 360)
        self.setMinimumSize(760, 320)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._header = build_page_header(
            "Background Correction",
            (
                "Load one global reference TIFF or an exposure-matched "
                "library and control whether subtraction is active."
            ),
        )
        layout.addWidget(self._header)

        self._summary_strip = build_summary_strip()
        layout.addWidget(self._summary_strip)

        panel = qtw.QFrame()
        panel.setObjectName("CommandBar")
        panel_layout = qtw.QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(8)

        top_row = qtw.QHBoxLayout()
        top_row.setSpacing(8)
        self._enable_checkbox = qtw.QCheckBox("Enable Background Subtraction")
        self._enable_checkbox.setToolTip(
            "Subtract the loaded background reference before metric computation.",
        )
        self._enable_checkbox.toggled.connect(self._on_enabled_toggled)
        top_row.addWidget(self._enable_checkbox)

        self._mode_label = qtw.QLabel("Reference Mode")
        self._mode_label.setObjectName("SectionTitle")
        top_row.addWidget(self._mode_label)

        self._mode_combo = qtw.QComboBox()
        self._mode_combo.addItem("Single File", "single_file")
        self._mode_combo.addItem("Folder Library", "folder_library")
        self._mode_combo.setToolTip(
            "Use one global background image or exposure-matched library.",
        )
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        top_row.addWidget(self._mode_combo)
        top_row.addStretch(1)
        panel_layout.addLayout(top_row)

        self._source_row = qtw.QWidget()
        source_layout = qtw.QHBoxLayout(self._source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(8)

        self._source_edit = qtw.QLineEdit()
        self._source_edit.setToolTip(
            "Path to the background TIFF file or folder source.",
        )
        source_layout.addWidget(self._source_edit, 1)

        self._browse_button = qtw.QPushButton("Browse Source...")
        self._browse_button.setToolTip("Browse for one background file or folder.")
        self._browse_button.clicked.connect(self._browse_source)
        source_layout.addWidget(self._browse_button)

        self._load_button = qtw.QPushButton("Load Background")
        self._load_button.setObjectName("AccentButton")
        self._load_button.setToolTip(
            "Load background reference data from the selected source.",
        )
        self._load_button.clicked.connect(self._load_reference)
        source_layout.addWidget(self._load_button)

        self._clear_button = qtw.QPushButton("Clear Background")
        self._clear_button.setToolTip("Clear loaded background references.")
        self._clear_button.clicked.connect(self._clear_reference)
        source_layout.addWidget(self._clear_button)
        panel_layout.addWidget(self._source_row)

        self._status_label = qtw.QLabel("")
        self._status_label.setObjectName("MutedLabel")
        self._status_label.setWordWrap(True)
        panel_layout.addWidget(self._status_label)

        layout.addWidget(panel)
        layout.addStretch(1)

        close_row = qtw.QHBoxLayout()
        close_row.addStretch(1)
        self._close_button = qtw.QPushButton("Close")
        self._close_button.clicked.connect(self.accept)
        close_row.addWidget(self._close_button)
        layout.addLayout(close_row)

        enable_window_content_drag(self)
        self._sync_from_host()

    def _current_mode(self) -> str:
        """Return the current normalized source mode from the mode combo."""
        return self._host_window._background_source_mode(
            self._mode_combo.currentData(),
        )

    def _reference_summary(self) -> tuple[str, str]:
        """Return summary text and level for loaded references."""
        library = self._host_window.background_library
        if library.global_ref is not None:
            return ("Global", "success")
        if library.refs_by_exposure_ms:
            count = len(library.refs_by_exposure_ms)
            suffix = "ref" if count == 1 else "refs"
            return (f"{count} exposure {suffix}", "success")
        if self._host_window.background_config.enabled:
            return ("None", "warning")
        return ("None", "neutral")

    def _coverage_summary(self) -> tuple[str, str]:
        """Return coverage text and level based on loaded dataset state."""
        host = self._host_window
        if not host.background_config.enabled:
            return ("Off", "neutral")
        if not host.background_library.has_any_reference():
            return ("Raw fallback", "warning")
        if host._bg_total_count > 0 and host._bg_unmatched_count > 0:
            matched = max(0, host._bg_total_count - host._bg_unmatched_count)
            return (f"Partial {matched}/{host._bg_total_count}", "warning")
        return ("Ready", "success")

    def _set_command_visibility(self, enabled: bool) -> None:
        """Show source-loading controls only when correction is enabled."""
        self._mode_label.setVisible(enabled)
        self._mode_combo.setVisible(enabled)
        self._source_row.setVisible(enabled)

    def _refresh_summary(self) -> None:
        """Refresh the dialog summary strip from host state."""
        host = self._host_window
        mode = host._background_source_mode()
        mode_text = (
            "Folder Library" if mode == "folder_library" else "Single File"
        )
        references_text, references_level = self._reference_summary()
        coverage_text, coverage_level = self._coverage_summary()
        dataset_text = (
            f"{len(host.paths)} images"
            if getattr(host, "paths", None)
            else "No dataset"
        )
        self._summary_strip.set_items(
            [
                SummaryItem(
                    "Correction",
                    "Enabled" if host.background_config.enabled else "Off",
                    level="success" if host.background_config.enabled else "neutral",
                ),
                SummaryItem(
                    "Reference Mode",
                    mode_text,
                    level="info" if host.background_config.enabled else "neutral",
                ),
                SummaryItem(
                    "References",
                    references_text,
                    level=references_level,
                ),
                SummaryItem(
                    "Coverage",
                    coverage_text,
                    level=coverage_level,
                ),
                SummaryItem(
                    "Dataset",
                    dataset_text,
                    level="success" if getattr(host, "paths", None) else "neutral",
                ),
            ],
        )

    def _sync_from_host(self, note: str | None = None) -> None:
        """Sync dialog controls from host-owned background state."""
        host = self._host_window
        mode = host._background_source_mode()
        with QSignalBlocker(self._enable_checkbox):
            self._enable_checkbox.setChecked(bool(host.background_config.enabled))
        with QSignalBlocker(self._mode_combo):
            index = self._mode_combo.findData(mode)
            self._mode_combo.setCurrentIndex(max(0, index))
        self._source_edit.setText(str(getattr(host, "_background_source_text", "")))
        host._update_background_input_hint(self._source_edit, mode=mode)
        host._update_background_status_label(note, label=self._status_label)
        self._set_command_visibility(bool(host.background_config.enabled))
        self._refresh_summary()

    def _on_enabled_toggled(self, enabled: bool) -> None:
        """Apply enabled-state changes through the host runtime."""
        self._host_window._on_background_enabled_toggled(enabled)
        self._sync_from_host()

    def _on_mode_changed(self, _index: int) -> None:
        """Update the source mode and placeholder text."""
        self._host_window._on_background_mode_changed(mode=self._current_mode())
        self._sync_from_host()

    def _browse_source(self) -> None:
        """Browse for a new background source path."""
        selected = self._host_window._browse_background_source(
            parent=self,
            mode=self._current_mode(),
            initial_text=self._source_edit.text().strip(),
        )
        if selected:
            self._source_edit.setText(selected)

    def _load_reference(self) -> None:
        """Load one background reference source into the host runtime."""
        self._host_window._load_background_reference(
            source_text=self._source_edit.text().strip(),
            mode=self._current_mode(),
        )
        self._sync_from_host()

    def _clear_reference(self) -> None:
        """Clear the current background references from the host runtime."""
        self._host_window._clear_background_reference()
        self._sync_from_host()


class BackgroundCorrectionPlugin:
    """Runtime plugin entrypoint for Measure-page background correction."""

    plugin_id = "background_correction"
    display_name = "Background Correction"

    @staticmethod
    def populate_page_menu(host_window: qtw.QWidget, menu: qtw.QMenu) -> None:
        """Populate runtime actions for the background correction tool."""
        open_action = menu.addAction("Open Background Correction...")
        open_action.setToolTip(
            "Configure and load background subtraction references for measurement.",
        )
        open_action.setStatusTip(open_action.toolTip())
        open_action.triggered.connect(
            lambda _checked=False: BackgroundCorrectionPlugin.open_dialog(
                host_window,
            ),
        )

    @staticmethod
    def open_dialog(host_window: qtw.QWidget) -> None:
        """Launch the background correction dialog."""
        dialog = BackgroundCorrectionDialog(host_window)
        dialog.exec()


register_page_plugin(BackgroundCorrectionPlugin, page="measure")
