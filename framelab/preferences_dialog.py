"""Preferences dialog for FrameLab appearance and workspace settings."""

from __future__ import annotations

from dataclasses import replace

from PySide6 import QtCore, QtWidgets as qtw
from PySide6.QtCore import Qt, Signal

from .ui_primitives import build_page_header
from .ui_settings import DensityMode, UiPreferences, UiStateSnapshot
from .window_drag import configure_secondary_window


class PreferencesDialog(qtw.QDialog):
    """Dialog with vertical navigation for UI preferences."""

    preferences_changed = Signal(object)

    def __init__(
        self,
        state_snapshot: UiStateSnapshot,
        parent: qtw.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        configure_secondary_window(self)
        self.setModal(True)
        self.resize(760, 520)
        self.setMinimumSize(680, 460)

        self._initial_preferences = replace(state_snapshot.preferences)
        self._last_emitted_preferences = replace(state_snapshot.preferences)
        self._reverting = False

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = build_page_header(
            "Preferences",
            (
                "Adjust appearance and workspace defaults. Appearance changes "
                "preview live while the dialog is open."
            ),
        )
        layout.addWidget(header)

        body = qtw.QHBoxLayout()
        body.setSpacing(12)

        self._nav_list = qtw.QListWidget()
        self._nav_list.setMaximumWidth(180)
        self._nav_list.setSpacing(2)
        self._nav_list.setAlternatingRowColors(False)
        self._nav_list.setUniformItemSizes(True)
        self._stack = qtw.QStackedWidget()

        body.addWidget(self._nav_list)
        body.addWidget(self._stack, 1)
        layout.addLayout(body, 1)

        self._theme_combo = qtw.QComboBox()
        self._theme_combo.addItem("Dark", "dark")
        self._theme_combo.addItem("Light", "light")

        self._density_combo = qtw.QComboBox()
        self._density_combo.addItem("Auto", DensityMode.AUTO.value)
        self._density_combo.addItem("Comfortable", DensityMode.COMFORTABLE.value)
        self._density_combo.addItem("Compact", DensityMode.COMPACT.value)

        self._show_subtitles_checkbox = qtw.QCheckBox("Show page subtitles")
        self._show_image_preview_checkbox = qtw.QCheckBox("Show image preview")
        self._show_histogram_checkbox = qtw.QCheckBox("Show histogram preview")
        self._restore_panel_states_checkbox = qtw.QCheckBox("Restore panel disclosure state")
        self._restore_last_tab_checkbox = qtw.QCheckBox("Restore last active workflow tab")
        self._collapse_summary_strips_checkbox = qtw.QCheckBox("Collapse summary strips by default")
        self._collapse_analysis_controls_checkbox = qtw.QCheckBox(
            "Collapse analysis plugin controls by default"
        )
        self._collapse_data_advanced_checkbox = qtw.QCheckBox(
            "Collapse data advanced controls by default"
        )

        self._add_page(
            "Appearance",
            "Appearance",
            "Theme and density controls for the main workstation chrome.",
            [
                self._form_row("Theme", self._theme_combo),
                self._form_row("Density", self._density_combo),
                self._show_subtitles_checkbox,
            ],
        )
        self._add_page(
            "Workspace",
            "Workspace",
            "Preview visibility and restore behavior for day-to-day sessions.",
            [
                self._show_image_preview_checkbox,
                self._show_histogram_checkbox,
                self._restore_panel_states_checkbox,
                self._restore_last_tab_checkbox,
                self._collapse_summary_strips_checkbox,
            ],
        )
        self._add_page(
            "Analysis",
            "Analysis",
            "Defaults specific to plugin-based analysis workflows.",
            [self._collapse_analysis_controls_checkbox],
        )
        self._add_page(
            "Data & Measure",
            "Data & Measure",
            "Defaults for metadata intake and measurement workspace behavior.",
            [self._collapse_data_advanced_checkbox],
        )

        buttons = qtw.QDialogButtonBox(
            qtw.QDialogButtonBox.Ok | qtw.QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._nav_list.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._set_preferences(self._initial_preferences)
        self._connect_live_preview_controls()
        self._nav_list.setCurrentRow(0)

    def current_preferences(self) -> UiPreferences:
        """Return the current preference selections."""

        theme_mode = str(self._theme_combo.currentData() or "dark")
        density_value = str(self._density_combo.currentData() or DensityMode.AUTO.value)
        return UiPreferences(
            theme_mode="light" if theme_mode == "light" else "dark",
            density_mode=DensityMode(density_value),
            show_page_subtitles=self._show_subtitles_checkbox.isChecked(),
            show_image_preview=self._show_image_preview_checkbox.isChecked(),
            show_histogram_preview=self._show_histogram_checkbox.isChecked(),
            restore_panel_states=self._restore_panel_states_checkbox.isChecked(),
            restore_last_tab=self._restore_last_tab_checkbox.isChecked(),
            collapse_analysis_plugin_controls_by_default=(
                self._collapse_analysis_controls_checkbox.isChecked()
            ),
            collapse_data_advanced_row_by_default=(
                self._collapse_data_advanced_checkbox.isChecked()
            ),
            collapse_summary_strips_by_default=(
                self._collapse_summary_strips_checkbox.isChecked()
            ),
        )

    def reject(self) -> None:
        """Revert any live-preview changes before closing the dialog."""

        if self.current_preferences() != self._initial_preferences:
            self._reverting = True
            self.preferences_changed.emit(replace(self._initial_preferences))
            self._reverting = False
        super().reject()

    def _add_page(
        self,
        nav_label: str,
        title: str,
        description: str,
        widgets: list[qtw.QWidget],
    ) -> None:
        page = qtw.QWidget()
        layout = qtw.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = build_page_header(title, description)
        layout.addWidget(header)

        card = qtw.QFrame()
        card.setObjectName("SubtlePanel")
        card_layout = qtw.QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(10)
        for widget in widgets:
            card_layout.addWidget(widget)
        card_layout.addStretch(1)
        layout.addWidget(card)
        layout.addStretch(1)

        self._stack.addWidget(page)
        self._nav_list.addItem(nav_label)

    def _connect_live_preview_controls(self) -> None:
        controls: list[QtCore.QObject] = [
            self._theme_combo,
            self._density_combo,
            self._show_subtitles_checkbox,
            self._show_image_preview_checkbox,
            self._show_histogram_checkbox,
            self._restore_panel_states_checkbox,
            self._restore_last_tab_checkbox,
            self._collapse_summary_strips_checkbox,
            self._collapse_analysis_controls_checkbox,
            self._collapse_data_advanced_checkbox,
        ]
        for control in controls:
            if isinstance(control, qtw.QComboBox):
                control.currentIndexChanged.connect(self._emit_live_preview)
            elif isinstance(control, qtw.QAbstractButton):
                control.toggled.connect(self._emit_live_preview)

    def _emit_live_preview(self, *_args: object) -> None:
        if self._reverting:
            return
        prefs = self.current_preferences()
        if prefs == self._last_emitted_preferences:
            return
        self._last_emitted_preferences = replace(prefs)
        self.preferences_changed.emit(replace(prefs))

    def _set_preferences(self, prefs: UiPreferences) -> None:
        theme_index = self._theme_combo.findData(prefs.theme_mode)
        if theme_index >= 0:
            self._theme_combo.setCurrentIndex(theme_index)
        density_index = self._density_combo.findData(prefs.density_mode.value)
        if density_index >= 0:
            self._density_combo.setCurrentIndex(density_index)
        self._show_subtitles_checkbox.setChecked(prefs.show_page_subtitles)
        self._show_image_preview_checkbox.setChecked(prefs.show_image_preview)
        self._show_histogram_checkbox.setChecked(prefs.show_histogram_preview)
        self._restore_panel_states_checkbox.setChecked(prefs.restore_panel_states)
        self._restore_last_tab_checkbox.setChecked(prefs.restore_last_tab)
        self._collapse_summary_strips_checkbox.setChecked(
            prefs.collapse_summary_strips_by_default
        )
        self._collapse_analysis_controls_checkbox.setChecked(
            prefs.collapse_analysis_plugin_controls_by_default
        )
        self._collapse_data_advanced_checkbox.setChecked(
            prefs.collapse_data_advanced_row_by_default
        )

    @staticmethod
    def _form_row(label_text: str, field: qtw.QWidget) -> qtw.QWidget:
        row = qtw.QWidget()
        layout = qtw.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = qtw.QLabel(label_text)
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
        layout.addWidget(field, 1)
        return row
