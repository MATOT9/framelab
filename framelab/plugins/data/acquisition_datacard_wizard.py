"""Data-page plugin that launches the acquisition datacard authoring wizard."""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Optional

from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt

from ..registry import register_page_plugin
from ...datacard_authoring import (
    AcquisitionDatacardModel,
    FieldMapping,
    FieldPlan,
    FieldSpec,
    FramePlan,
    OverrideRow,
    append_overrides,
    datacard_to_payload,
    generate_overrides,
    load_acquisition_datacard,
    load_field_mapping,
    mapping_config_path,
    save_acquisition_datacard,
    validate_datacard,
)
from ...ebus import EbusCanonicalFieldResolution, resolve_ebus_canonical_fields
from ...payload_utils import delete_dot_path, get_dot_path, set_dot_path
from ...ui_primitives import (
    ChipSpec,
    SummaryItem,
    build_page_header,
    build_summary_strip,
)
from ...window_drag import (
    apply_secondary_window_geometry,
    configure_secondary_window,
    place_secondary_window,
)


@dataclass(slots=True)
class _RowEntry:
    """Single editable override row entry used in the table UI."""

    frame_start: int
    frame_end: int
    key: str
    value: Any
    reason: str


def _display_value(value: Any) -> str:
    """Format value for compact table display."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=True)
    except Exception:
        return str(value)


def _parse_json_literal(text: str) -> Any:
    """Parse loose JSON literal with string fallback."""
    stripped = text.strip()
    if not stripped:
        return ""
    try:
        return json.loads(stripped)
    except Exception:
        return stripped


def _to_int(text: str, default: int) -> int:
    """Parse integer with fallback."""
    try:
        return int(text.strip())
    except Exception:
        return int(default)


def _to_float(text: str, default: float) -> float:
    """Parse float with fallback."""
    try:
        return float(text.strip())
    except Exception:
        return float(default)


class AcquisitionDatacardWizardDialog(qtw.QDialog):
    """Modal wizard dialog for acquisition datacard creation/editing."""

    _AUTO_IDENTITY_KEYS = frozenset(
        {
            "camera_id",
            "campaign_id",
            "session_id",
            "acquisition_id",
            "label",
        }
    )

    def __init__(
        self,
        host_window: Optional[qtw.QWidget],
        initial_folder: str = "",
    ) -> None:
        super().__init__(host_window)
        self.setWindowTitle("Acquisition Datacard Wizard")
        configure_secondary_window(self, draggable=True)
        self.setModal(True)
        self.setMinimumSize(980, 640)

        self._mapping: FieldMapping = load_field_mapping()
        self._model: Optional[AcquisitionDatacardModel] = None
        self._existing_rows: list[OverrideRow] = []
        self._row_entries: list[_RowEntry] = []
        self._loaded_index_base: Optional[int] = None
        self._merge_warnings: list[str] = []
        self._ebus_attached = False
        self._ebus_resolution_by_key: dict[str, EbusCanonicalFieldResolution] = {}
        self._validation_state_text = "Not validated"
        self._validation_state_level = "neutral"

        self._identity_edits: dict[str, qtw.QLineEdit] = {}
        self._paths_edits: dict[str, qtw.QLineEdit] = {}
        self._intent_edits: dict[str, qtw.QLineEdit] = {}
        self._defaults_editors: dict[str, qtw.QWidget] = {}
        self._defaults_editor_notes: dict[str, qtw.QLabel] = {}

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._header = build_page_header(
            "Acquisition Datacard Wizard",
            (
                "Author acquisition-wide metadata, defaults, and frame "
                "mapping with eBUS-aware baseline behavior."
            ),
        )
        layout.addWidget(self._header)
        self._summary_strip = build_summary_strip()
        layout.addWidget(self._summary_strip)

        self.tabs = qtw.QTabWidget()
        self.tabs.addTab(self._build_target_tab(initial_folder), "1. Target")
        self.tabs.addTab(self._build_metadata_tab(), "2. Identity/Paths/Intent")
        self.tabs.addTab(self._build_defaults_tab(), "3. Defaults")
        self.tabs.addTab(self._build_frames_tab(), "4. Frame Mapping")
        self.tabs.addTab(self._build_review_tab(), "5. Review and Save")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, 1)

        buttons = qtw.QHBoxLayout()
        self.validate_button = qtw.QPushButton("Validate")
        self.validate_button.clicked.connect(self._validate_current_model)
        buttons.addWidget(self.validate_button)

        self.save_button = qtw.QPushButton("Save Datacard")
        self.save_button.setObjectName("AccentButton")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        buttons.addStretch(1)

        self.close_button = qtw.QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self._configure_tooltips()
        self._install_drag_filters()

        if initial_folder:
            self._folder_edit.setText(initial_folder)
        self._load_target()
        self._refresh_wizard_header_state()
        apply_secondary_window_geometry(
            self,
            preferred_size=(1120, 760),
            host_window=host_window,
        )

    def _field_spec_by_key(self) -> dict[str, FieldSpec]:
        return self._mapping.by_key()

    def _defaults_specs(self) -> list[FieldSpec]:
        return [
            field for field in self._mapping.fields if field.show_in_defaults
        ]

    def _override_specs(self) -> list[FieldSpec]:
        return [
            field
            for field in self._mapping.fields
            if field.show_in_overrides
        ]

    def _build_target_tab(self, initial_folder: str) -> qtw.QWidget:
        tab = qtw.QWidget()
        layout = qtw.QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        path_row = qtw.QHBoxLayout()
        self._folder_edit = qtw.QLineEdit(initial_folder)
        self._folder_edit.setPlaceholderText("Select acquisition folder")
        path_row.addWidget(self._folder_edit, 1)
        self._browse_button = qtw.QPushButton("Browse...")
        self._browse_button.clicked.connect(self._browse_folder)
        path_row.addWidget(self._browse_button)
        self._load_target_button = qtw.QPushButton("Load Target")
        self._load_target_button.setObjectName("AccentButton")
        self._load_target_button.clicked.connect(self._load_target)
        path_row.addWidget(self._load_target_button)
        layout.addLayout(path_row)

        self._target_state_label = qtw.QLabel("No target loaded.")
        self._target_state_label.setObjectName("MutedLabel")
        self._target_state_label.setWordWrap(True)
        layout.addWidget(self._target_state_label)

        self._frame_info_label = qtw.QLabel("Frame mapping: unknown")
        self._frame_info_label.setObjectName("MutedLabel")
        self._frame_info_label.setWordWrap(True)
        layout.addWidget(self._frame_info_label)

        index_row = qtw.QHBoxLayout()
        index_label = qtw.QLabel("Frame index base")
        index_label.setObjectName("SectionTitle")
        index_row.addWidget(index_label)
        self._index_base_combo = qtw.QComboBox()
        self._index_base_combo.addItem("0-based", 0)
        self._index_base_combo.addItem("1-based", 1)
        self._index_base_combo.currentIndexChanged.connect(
            self._on_index_base_changed,
        )
        index_row.addWidget(self._index_base_combo)
        index_row.addStretch(1)
        layout.addLayout(index_row)

        self._index_warning_label = qtw.QLabel("")
        self._index_warning_label.setObjectName("MutedLabel")
        self._index_warning_label.setWordWrap(True)
        layout.addWidget(self._index_warning_label)

        append_group = qtw.QGroupBox("Existing Override Strategy")
        append_layout = qtw.QHBoxLayout(append_group)
        append_layout.setContentsMargins(10, 8, 10, 8)
        append_layout.setSpacing(8)
        self._append_existing_checkbox = qtw.QCheckBox(
            "Append new rows to existing overrides",
        )
        self._append_existing_checkbox.setChecked(True)
        append_layout.addWidget(self._append_existing_checkbox)
        self._load_existing_button = qtw.QPushButton(
            "Load Existing Rows for Full Edit",
        )
        self._load_existing_button.clicked.connect(
            self._load_existing_rows_into_editor,
        )
        append_layout.addWidget(self._load_existing_button)
        self._existing_count_label = qtw.QLabel("Existing rows: 0")
        self._existing_count_label.setObjectName("MutedLabel")
        append_layout.addWidget(self._existing_count_label)
        append_layout.addStretch(1)
        layout.addWidget(append_group)

        mapping_row = qtw.QHBoxLayout()
        mapping_label = qtw.QLabel(
            f"Field mapping file: {mapping_config_path()}",
        )
        mapping_label.setObjectName("MutedLabel")
        mapping_label.setWordWrap(True)
        mapping_row.addWidget(mapping_label, 1)
        self._reload_mapping_button = qtw.QPushButton("Reload Mapping")
        self._reload_mapping_button.clicked.connect(self._reload_mapping)
        mapping_row.addWidget(self._reload_mapping_button)
        layout.addLayout(mapping_row)

        self._mapping_warning_label = qtw.QLabel("")
        self._mapping_warning_label.setObjectName("MutedLabel")
        self._mapping_warning_label.setWordWrap(True)
        layout.addWidget(self._mapping_warning_label)
        self._refresh_mapping_warnings()

        layout.addStretch(1)
        return tab

    def _build_metadata_tab(self) -> qtw.QWidget:
        tab = qtw.QWidget()
        outer = qtw.QVBoxLayout(tab)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(8)

        scroll = qtw.QScrollArea()
        scroll.setWidgetResizable(True)
        container = qtw.QWidget()
        self._configure_scroll_surface(scroll, container)
        layout = qtw.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        identity_body = qtw.QWidget()
        identity_form = qtw.QFormLayout(identity_body)
        identity_form.setContentsMargins(0, 0, 0, 0)
        identity_fields = (
            ("camera_id", "Camera ID"),
            ("campaign_id", "Campaign ID"),
            ("session_id", "Session ID"),
            ("acquisition_id", "Acquisition ID"),
            ("label", "Label"),
            ("created_at_local", "Created At (local)"),
            ("finalized_at_local", "Finalized At (local)"),
            ("timezone", "Timezone"),
        )
        for key, label in identity_fields:
            edit = qtw.QLineEdit()
            if key in self._AUTO_IDENTITY_KEYS:
                edit.setReadOnly(True)
            self._identity_edits[key] = edit
            identity_form.addRow(label, edit)
        layout.addWidget(
            self._create_collapsible_group(
                "Identity",
                identity_body,
                tooltip="Expand/collapse identity fields.",
            ),
        )

        paths_body = qtw.QWidget()
        paths_form = qtw.QFormLayout(paths_body)
        paths_form.setContentsMargins(0, 0, 0, 0)
        path_fields = (
            ("frames_dir", "frames_dir"),
        )
        for key, label in path_fields:
            edit = qtw.QLineEdit()
            self._paths_edits[key] = edit
            paths_form.addRow(label, edit)
        layout.addWidget(
            self._create_collapsible_group(
                "Paths",
                paths_body,
                tooltip="Expand/collapse path fields.",
            ),
        )

        intent_body = qtw.QWidget()
        intent_form = qtw.QFormLayout(intent_body)
        intent_form.setContentsMargins(0, 0, 0, 0)
        intent_fields = (
            ("capture_type", "Capture Type"),
            ("subtype", "Subtype"),
            ("scene", "Scene"),
            ("tags", "Tags (comma-separated)"),
        )
        for key, label in intent_fields:
            edit = qtw.QLineEdit()
            self._intent_edits[key] = edit
            intent_form.addRow(label, edit)
        layout.addWidget(
            self._create_collapsible_group(
                "Intent",
                intent_body,
                tooltip="Expand/collapse capture intent fields.",
            ),
        )

        layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)
        return tab

    def _create_editor(
        self,
        spec: FieldSpec,
        *,
        allow_empty: bool = False,
    ) -> qtw.QWidget:
        """Create typed editor widget for one field specification."""
        if allow_empty and spec.value_type == "int":
            widget = qtw.QLineEdit()
            validator = QtGui.QIntValidator(-2_000_000_000, 2_000_000_000, widget)
            if spec.minimum is not None:
                validator.setBottom(int(spec.minimum))
            if spec.maximum is not None:
                validator.setTop(int(spec.maximum))
            widget.setValidator(validator)
            widget.setProperty("allow_empty", True)
            return widget

        if allow_empty and spec.value_type == "float":
            widget = qtw.QLineEdit()
            minimum = float(spec.minimum) if spec.minimum is not None else -1.0e15
            maximum = float(spec.maximum) if spec.maximum is not None else 1.0e15
            validator = QtGui.QDoubleValidator(minimum, maximum, 9, widget)
            validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
            widget.setValidator(validator)
            widget.setProperty("allow_empty", True)
            return widget

        if spec.value_type == "int":
            widget = qtw.QSpinBox()
            widget.setRange(-2_000_000_000, 2_000_000_000)
            if spec.minimum is not None:
                widget.setMinimum(int(spec.minimum))
            if spec.maximum is not None:
                widget.setMaximum(int(spec.maximum))
            if spec.step is not None and spec.step > 0:
                widget.setSingleStep(int(max(1, spec.step)))
            return widget

        if spec.value_type == "float":
            widget = qtw.QDoubleSpinBox()
            widget.setDecimals(9)
            widget.setRange(-1.0e15, 1.0e15)
            if spec.minimum is not None:
                widget.setMinimum(float(spec.minimum))
            if spec.maximum is not None:
                widget.setMaximum(float(spec.maximum))
            if spec.step is not None and spec.step > 0:
                widget.setSingleStep(float(spec.step))
            return widget

        if spec.value_type == "bool":
            widget = qtw.QComboBox()
            if allow_empty:
                widget.addItem("", None)
            widget.addItem("False", False)
            widget.addItem("True", True)
            if allow_empty:
                widget.setProperty("allow_empty", True)
            return widget

        if spec.value_type == "enum":
            widget = qtw.QComboBox()
            if allow_empty:
                widget.addItem("", None)
            for option in spec.options:
                widget.addItem(option, option)
            if allow_empty:
                widget.setProperty("allow_empty", True)
            return widget

        widget = qtw.QLineEdit()
        if allow_empty:
            widget.setProperty("allow_empty", True)
        return widget

    def _get_optional_float_editor_value(
        self,
        widget: qtw.QWidget,
    ) -> Optional[float]:
        """Return an optional float value from an empty-capable editor."""
        if isinstance(widget, qtw.QLineEdit):
            text = widget.text().strip()
            if not text:
                return None
            return _to_float(text, 0.0)
        if isinstance(widget, qtw.QDoubleSpinBox):
            return float(widget.value())
        return None

    def _numeric_sweep_values(self) -> tuple[float, float, float]:
        """Read validated numeric sweep parameters from the generator UI."""
        start = self._get_optional_float_editor_value(self._sweep_start_edit)
        stop = self._get_optional_float_editor_value(self._sweep_stop_edit)
        step = self._get_optional_float_editor_value(self._sweep_step_edit)
        if start is None or stop is None or step is None:
            raise ValueError("Numeric sweep requires start, stop, and step values.")
        return (start, stop, step)

    def _set_editor_value(
        self,
        widget: qtw.QWidget,
        spec: FieldSpec,
        value: Any,
    ) -> None:
        """Set typed value on a field editor widget."""
        if isinstance(widget, qtw.QSpinBox):
            widget.setValue(_to_int(str(value), widget.minimum()))
            return
        if isinstance(widget, qtw.QDoubleSpinBox):
            widget.setValue(_to_float(str(value), widget.minimum()))
            return
        if isinstance(widget, qtw.QLineEdit):
            if value is None and bool(widget.property("allow_empty")):
                widget.clear()
                return
            widget.setText("" if value is None else str(value))
            return
        if isinstance(widget, qtw.QComboBox):
            idx = widget.findData(value)
            if idx < 0:
                idx = widget.findText(str(value))
            if idx < 0 and widget.count() > 0:
                idx = 0
            if idx >= 0:
                widget.setCurrentIndex(idx)
            return
    def _get_editor_value(
        self,
        widget: qtw.QWidget,
        spec: FieldSpec,
    ) -> Any:
        """Read typed value from field editor widget."""
        if isinstance(widget, qtw.QSpinBox):
            return int(widget.value())
        if isinstance(widget, qtw.QDoubleSpinBox):
            return float(widget.value())
        if isinstance(widget, qtw.QComboBox):
            data = widget.currentData()
            if (
                bool(widget.property("allow_empty"))
                and data is None
                and not widget.currentText().strip()
            ):
                return None
            return data if data is not None else widget.currentText()
        if isinstance(widget, qtw.QLineEdit):
            text = widget.text().strip()
            if bool(widget.property("allow_empty")) and not text:
                return None
            if spec.value_type == "int":
                return _to_int(text, 0)
            if spec.value_type == "float":
                return _to_float(text, 0.0)
            if spec.value_type == "string":
                return text
            return _parse_json_literal(text)
        return None

    def _build_defaults_tab(self) -> qtw.QWidget:
        tab = qtw.QWidget()
        outer = qtw.QVBoxLayout(tab)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(8)

        scroll = qtw.QScrollArea()
        scroll.setWidgetResizable(True)
        self._defaults_container = qtw.QWidget()
        self._configure_scroll_surface(scroll, self._defaults_container)
        self._defaults_layout = qtw.QVBoxLayout(self._defaults_container)
        self._defaults_layout.setContentsMargins(0, 0, 0, 0)
        self._defaults_layout.setSpacing(8)
        scroll.setWidget(self._defaults_container)
        outer.addWidget(scroll, 1)
        self._rebuild_defaults_form()
        return tab

    def _rebuild_defaults_form(self) -> None:
        """Rebuild dynamic defaults form from mapping."""
        while self._defaults_layout.count():
            item = self._defaults_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._defaults_editors.clear()
        self._defaults_editor_notes.clear()

        grouped: "OrderedDict[str, list[FieldSpec]]" = OrderedDict()
        for spec in self._defaults_specs():
            grouped.setdefault(spec.group, []).append(spec)

        for group_name, specs in grouped.items():
            group_body = qtw.QWidget()
            form = qtw.QFormLayout(group_body)
            form.setContentsMargins(0, 0, 0, 0)
            for spec in specs:
                editor = self._create_editor(spec, allow_empty=True)
                row_widget = qtw.QWidget()
                row_layout = qtw.QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(8)
                row_layout.addWidget(editor, 1)
                note_label = qtw.QLabel("")
                note_label.setObjectName("MutedLabel")
                note_label.setVisible(False)
                row_layout.addWidget(note_label, 0, Qt.AlignRight)
                label = spec.label
                if spec.unit and "[" not in label:
                    label = f"{label} [{spec.unit}]"
                form.addRow(label, row_widget)
                self._defaults_editors[spec.key] = editor
                self._defaults_editor_notes[spec.key] = note_label
                self._set_field_editor_tooltip(editor, spec, "default")
            self._defaults_layout.addWidget(
                self._create_collapsible_group(
                    group_name,
                    group_body,
                    tooltip=f"Expand/collapse {group_name.lower()} defaults.",
                ),
            )
        self._defaults_layout.addStretch(1)
        self._install_drag_filters()
        self._refresh_ebus_field_states()

    def _build_frames_tab(self) -> qtw.QWidget:
        tab = qtw.QWidget()
        layout = qtw.QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        self._frame_mode_combo = qtw.QComboBox()
        self._frame_mode_combo.addItem("Defaults only (unknown duration)", "defaults_only")
        self._frame_mode_combo.addItem("Generate rows", "generate")
        self._frame_mode_combo.addItem("Manual rows", "manual")
        self._frame_mode_combo.currentIndexChanged.connect(
            self._update_frame_mode_visibility,
        )
        mode_row = qtw.QHBoxLayout()
        mode_row.addWidget(self._make_title_label("Frame Mapping Mode"))
        mode_row.addWidget(self._frame_mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self._generator_group = qtw.QGroupBox("Generator")
        gen_layout = qtw.QGridLayout(self._generator_group)
        gen_layout.setContentsMargins(10, 10, 10, 10)
        gen_layout.setHorizontalSpacing(8)
        gen_layout.setVerticalSpacing(6)

        self._generator_field_combo = qtw.QComboBox()
        for spec in self._override_specs():
            self._generator_field_combo.addItem(spec.label, spec.key)
        self._generator_field_combo.currentIndexChanged.connect(
            self._on_generator_field_changed,
        )
        gen_layout.addWidget(self._make_title_label("Field"), 0, 0)
        gen_layout.addWidget(self._generator_field_combo, 0, 1)

        self._generator_type_combo = qtw.QComboBox()
        self._generator_type_combo.addItem("Explicit values list", "explicit_list")
        self._generator_type_combo.addItem("Numeric sweep", "numeric_sweep")
        self._generator_type_combo.addItem("Constant over frame range", "constant_range")
        self._generator_type_combo.currentIndexChanged.connect(
            self._update_generator_mode_widgets,
        )
        gen_layout.addWidget(self._make_title_label("Generator Type"), 0, 2)
        gen_layout.addWidget(self._generator_type_combo, 0, 3)

        self._use_discovered_frames_checkbox = qtw.QCheckBox(
            "Use discovered frame order/count",
        )
        self._use_discovered_frames_checkbox.setChecked(True)
        gen_layout.addWidget(self._use_discovered_frames_checkbox, 0, 4, 1, 2)

        self._gen_frame_start = qtw.QSpinBox()
        self._gen_frame_start.setRange(0, 1_000_000_000)
        self._gen_frame_end = qtw.QSpinBox()
        self._gen_frame_end.setRange(0, 1_000_000_000)
        gen_layout.addWidget(self._make_title_label("Frame Start"), 1, 0)
        gen_layout.addWidget(self._gen_frame_start, 1, 1)
        gen_layout.addWidget(self._make_title_label("Frame End"), 1, 2)
        gen_layout.addWidget(self._gen_frame_end, 1, 3)

        self._gen_reason_edit = qtw.QLineEdit("generated")
        gen_layout.addWidget(self._make_title_label("Reason"), 1, 4)
        gen_layout.addWidget(self._gen_reason_edit, 1, 5)

        self._generator_stack = qtw.QStackedWidget()
        explicit_page = qtw.QWidget()
        explicit_layout = qtw.QHBoxLayout(explicit_page)
        explicit_layout.setContentsMargins(0, 0, 0, 0)
        explicit_layout.setSpacing(8)
        explicit_layout.addWidget(self._make_title_label("Values"))
        self._explicit_values_edit = qtw.QLineEdit()
        self._explicit_values_edit.setPlaceholderText("e.g. 100, 200, 300")
        explicit_layout.addWidget(self._explicit_values_edit, 1)
        self._generator_stack.addWidget(explicit_page)

        sweep_page = qtw.QWidget()
        sweep_layout = qtw.QHBoxLayout(sweep_page)
        sweep_layout.setContentsMargins(0, 0, 0, 0)
        sweep_layout.setSpacing(12)
        self._sweep_start_edit = self._create_editor(
            FieldSpec(
                key="__sweep_start__",
                label="Start",
                group="Generator",
                value_type="float",
            ),
            allow_empty=True,
        )
        self._sweep_stop_edit = self._create_editor(
            FieldSpec(
                key="__sweep_stop__",
                label="Stop",
                group="Generator",
                value_type="float",
            ),
            allow_empty=True,
        )
        self._sweep_step_edit = self._create_editor(
            FieldSpec(
                key="__sweep_step__",
                label="Step",
                group="Generator",
                value_type="float",
            ),
            allow_empty=True,
        )
        for label_text, editor in (
            ("Start", self._sweep_start_edit),
            ("Stop", self._sweep_stop_edit),
            ("Step", self._sweep_step_edit),
        ):
            if isinstance(editor, qtw.QLineEdit):
                editor.setMinimumWidth(180)
                editor.setMaximumWidth(220)
            pair_widget = qtw.QWidget()
            pair_layout = qtw.QHBoxLayout(pair_widget)
            pair_layout.setContentsMargins(0, 0, 0, 0)
            pair_layout.setSpacing(6)
            pair_layout.addWidget(self._make_title_label(label_text))
            pair_layout.addWidget(editor)
            sweep_layout.addWidget(pair_widget)
        sweep_layout.addStretch(1)
        self._generator_stack.addWidget(sweep_page)

        constant_page = qtw.QWidget()
        constant_layout = qtw.QHBoxLayout(constant_page)
        constant_layout.setContentsMargins(0, 0, 0, 0)
        constant_layout.setSpacing(8)
        constant_layout.addWidget(self._make_title_label("Value"))
        self._constant_value_holder = qtw.QWidget()
        self._constant_value_layout = qtw.QHBoxLayout(self._constant_value_holder)
        self._constant_value_layout.setContentsMargins(0, 0, 0, 0)
        self._constant_value_layout.setSpacing(0)
        self._constant_value_editor = qtw.QLineEdit()
        self._constant_value_layout.addWidget(self._constant_value_editor, 1)
        constant_layout.addWidget(self._constant_value_holder, 1)
        self._generator_stack.addWidget(constant_page)

        gen_layout.addWidget(self._generator_stack, 2, 0, 1, 6)
        self._generate_button = qtw.QPushButton("Generate and Append Rows")
        self._generate_button.clicked.connect(self._generate_rows)
        gen_layout.addWidget(self._generate_button, 3, 4, 1, 2)
        layout.addWidget(self._generator_group)

        manual_group = qtw.QGroupBox("Manual Row Editor")
        manual_layout = qtw.QGridLayout(manual_group)
        manual_layout.setContentsMargins(10, 10, 10, 10)
        manual_layout.setHorizontalSpacing(8)
        manual_layout.setVerticalSpacing(6)

        self._manual_start_spin = qtw.QSpinBox()
        self._manual_start_spin.setRange(0, 1_000_000_000)
        self._manual_end_spin = qtw.QSpinBox()
        self._manual_end_spin.setRange(0, 1_000_000_000)
        manual_layout.addWidget(self._make_title_label("Start"), 0, 0)
        manual_layout.addWidget(self._manual_start_spin, 0, 1)
        manual_layout.addWidget(self._make_title_label("End"), 0, 2)
        manual_layout.addWidget(self._manual_end_spin, 0, 3)

        self._manual_field_combo = qtw.QComboBox()
        for spec in self._override_specs():
            self._manual_field_combo.addItem(spec.label, spec.key)
        self._manual_field_combo.addItem("Custom key...", "__custom__")
        self._manual_field_combo.currentIndexChanged.connect(
            self._on_manual_field_changed,
        )
        manual_layout.addWidget(self._make_title_label("Field"), 1, 0)
        manual_layout.addWidget(self._manual_field_combo, 1, 1, 1, 3)

        self._manual_custom_key_edit = qtw.QLineEdit()
        self._manual_custom_key_edit.setPlaceholderText("camera_settings.some_key")
        self._manual_custom_key_edit.setVisible(False)
        manual_layout.addWidget(self._manual_custom_key_edit, 1, 4, 1, 2)

        manual_layout.addWidget(self._make_title_label("Value"), 2, 0)
        self._manual_value_holder = qtw.QWidget()
        self._manual_value_layout = qtw.QHBoxLayout(self._manual_value_holder)
        self._manual_value_layout.setContentsMargins(0, 0, 0, 0)
        self._manual_value_layout.setSpacing(0)
        self._manual_value_editor = qtw.QLineEdit()
        self._manual_value_layout.addWidget(self._manual_value_editor, 1)
        manual_layout.addWidget(self._manual_value_holder, 2, 1, 1, 3)

        self._manual_reason_edit = qtw.QLineEdit("manual")
        manual_layout.addWidget(self._make_title_label("Reason"), 2, 4)
        manual_layout.addWidget(self._manual_reason_edit, 2, 5)

        self._add_row_button = qtw.QPushButton("Add / Update Row")
        self._add_row_button.clicked.connect(self._add_or_update_manual_row)
        manual_layout.addWidget(self._add_row_button, 3, 3)
        self._remove_row_button = qtw.QPushButton("Remove Selected")
        self._remove_row_button.clicked.connect(self._remove_selected_rows)
        manual_layout.addWidget(self._remove_row_button, 3, 4)
        self._clear_rows_button = qtw.QPushButton("Clear Editor Rows")
        self._clear_rows_button.clicked.connect(self._clear_editor_rows)
        manual_layout.addWidget(self._clear_rows_button, 3, 5)
        layout.addWidget(manual_group)

        self._rows_table = qtw.QTableWidget(0, 5)
        self._rows_table.setHorizontalHeaderLabels(
            ["Start", "End", "Field", "Value", "Reason"],
        )
        self._rows_table.setSelectionBehavior(qtw.QAbstractItemView.SelectRows)
        self._rows_table.setSelectionMode(
            qtw.QAbstractItemView.ExtendedSelection,
        )
        self._rows_table.setEditTriggers(qtw.QAbstractItemView.NoEditTriggers)
        self._rows_table.verticalHeader().setVisible(False)
        header = self._rows_table.horizontalHeader()
        header.setSectionResizeMode(0, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, qtw.QHeaderView.Stretch)
        header.setSectionResizeMode(4, qtw.QHeaderView.ResizeToContents)
        self._rows_table.cellClicked.connect(self._on_row_table_clicked)
        layout.addWidget(self._rows_table, 1)

        self._rows_summary_label = qtw.QLabel("Editor rows: 0")
        self._rows_summary_label.setObjectName("MutedLabel")
        layout.addWidget(self._rows_summary_label)

        self._update_generator_editor()
        self._update_manual_editor()
        self._update_frame_mode_visibility()
        return tab

    def _build_review_tab(self) -> qtw.QWidget:
        tab = qtw.QWidget()
        layout = qtw.QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        self._refresh_review_button = qtw.QPushButton("Refresh Preview")
        self._refresh_review_button.clicked.connect(self._refresh_review)
        layout.addWidget(self._refresh_review_button)

        self._review_warnings = qtw.QPlainTextEdit()
        self._configure_review_editor(self._review_warnings)
        self._review_warnings.setReadOnly(True)
        self._review_warnings.setPlaceholderText("Validation and merge warnings")
        self._review_warnings.setMaximumHeight(160)
        layout.addWidget(self._review_warnings)

        self._review_json = qtw.QPlainTextEdit()
        self._configure_review_editor(self._review_json)
        self._review_json.setReadOnly(True)
        self._review_json.setPlaceholderText("Datacard JSON preview")
        layout.addWidget(self._review_json, 1)
        return tab

    @staticmethod
    def _make_title_label(text: str) -> qtw.QLabel:
        label = qtw.QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    @staticmethod
    def _apply_tooltip(target: Any, text: str) -> None:
        if hasattr(target, "setToolTip"):
            target.setToolTip(text)
        if hasattr(target, "setStatusTip"):
            target.setStatusTip(text)

    @staticmethod
    def _clear_tooltip(target: Any) -> None:
        if hasattr(target, "setToolTip"):
            target.setToolTip("")
        if hasattr(target, "setStatusTip"):
            target.setStatusTip("")

    @staticmethod
    def _configure_scroll_surface(
        scroll: qtw.QScrollArea,
        content: qtw.QWidget,
    ) -> None:
        scroll.setObjectName("WizardScrollArea")
        scroll.setFrameShape(qtw.QFrame.NoFrame)
        scroll.viewport().setObjectName("WizardScrollViewport")
        scroll.viewport().setAutoFillBackground(True)
        content.setObjectName("WizardScrollContent")
        content.setAutoFillBackground(True)

    @staticmethod
    def _configure_review_editor(editor: qtw.QPlainTextEdit) -> None:
        editor.setObjectName("WizardReviewEditor")
        editor.viewport().setObjectName("WizardReviewViewport")
        editor.viewport().setAutoFillBackground(True)

    def place_near_host(self, host_window: Optional[qtw.QWidget]) -> None:
        place_secondary_window(self, host_window=host_window)

    @staticmethod
    def _set_collapsible_section_state(
        toggle: qtw.QToolButton,
        body: qtw.QWidget,
        title: str,
        expanded: bool,
    ) -> None:
        body.setVisible(expanded)
        blocker = QtCore.QSignalBlocker(toggle)
        toggle.setChecked(expanded)
        toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        toggle.setText(
            f"{title} ({'Hide' if expanded else 'Show'})",
        )
        del blocker

    def _create_collapsible_group(
        self,
        title: str,
        body: qtw.QWidget,
        *,
        expanded: bool = True,
        tooltip: str = "",
    ) -> qtw.QGroupBox:
        group = qtw.QGroupBox(title)
        layout = qtw.QVBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toggle = qtw.QToolButton()
        toggle.setObjectName("DisclosureButton")
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setCheckable(True)
        if tooltip:
            self._apply_tooltip(toggle, tooltip)
        self._set_collapsible_section_state(toggle, body, title, expanded)
        toggle.toggled.connect(
            lambda checked, button=toggle, section=body, section_title=title: (
                self._set_collapsible_section_state(
                    button,
                    section,
                    section_title,
                    bool(checked),
                )
            ),
        )
        layout.addWidget(toggle)
        layout.addWidget(body)
        return group

    def _set_field_editor_tooltip(
        self,
        widget: qtw.QWidget,
        spec: FieldSpec,
        context: str,
    ) -> None:
        del context
        tooltip = spec.tooltip.strip()
        if tooltip:
            self._apply_tooltip(widget, tooltip)
            return
        self._clear_tooltip(widget)

    def _configure_tooltips(self) -> None:
        self.tabs.setTabToolTip(
            0,
            "Choose the acquisition folder, frame index base, and override merge behavior.",
        )
        self.tabs.setTabToolTip(
            1,
            "Edit identity, paths, and capture intent fields stored in the datacard.",
        )
        self.tabs.setTabToolTip(
            2,
            "Set default camera, instrument, and acquisition values used across frames.",
        )
        self.tabs.setTabToolTip(
            3,
            "Generate or edit per-frame override rows before saving the datacard.",
        )
        self.tabs.setTabToolTip(
            4,
            "Review validation messages and the JSON preview that will be written.",
        )

        target_tooltips = {
            self._folder_edit: (
                "Acquisition folder to load. Paste a path or browse, then click "
                "Load Target."
            ),
            self._browse_button: "Pick the acquisition folder from disk.",
            self._load_target_button: (
                "Load the selected folder and any existing acquisition datacard "
                "into the wizard."
            ),
            self._index_base_combo: (
                "Choose whether frame numbers in overrides start at 0 or 1. Match "
                "the acquisition numbering."
            ),
            self._append_existing_checkbox: (
                "Keep existing saved override rows and append the editor rows when "
                "you save."
            ),
            self._load_existing_button: (
                "Copy existing saved override rows into the editor so you can edit "
                "them directly."
            ),
            self._reload_mapping_button: (
                "Reload the field mapping JSON after editing it outside the wizard."
            ),
        }
        for widget, text in target_tooltips.items():
            self._apply_tooltip(widget, text)

        identity_tooltips = {
            "camera_id": (
                "Read-only camera identifier. This is derived from the folder "
                "structure or external metadata sources."
            ),
            "campaign_id": (
                "Read-only campaign identifier derived from the surrounding data "
                "hierarchy."
            ),
            "session_id": (
                "Read-only session identifier derived from the surrounding data "
                "hierarchy."
            ),
            "acquisition_id": (
                "Read-only acquisition identifier derived from the target folder."
            ),
            "label": (
                "Read-only acquisition name derived from the target folder naming "
                "pattern."
            ),
            "created_at_local": (
                "Local creation timestamp. Enter the recorded local time string."
            ),
            "finalized_at_local": (
                "Local completion timestamp. Leave blank if the acquisition is not finalized."
            ),
            "timezone": "Timezone name or offset for the local timestamps.",
        }
        for key, text in identity_tooltips.items():
            self._apply_tooltip(self._identity_edits[key], text)

        path_tooltips = {
            "frames_dir": (
                "Folder name, relative to the acquisition root, that contains the "
                "frame files."
            ),
        }
        for key, text in path_tooltips.items():
            self._apply_tooltip(self._paths_edits[key], text)

        intent_tooltips = {
            "capture_type": "High-level capture type, such as calibration or acquisition.",
            "subtype": "More specific capture subtype for filtering or downstream tooling.",
            "scene": "Short description of the recorded scene or target.",
            "tags": "Comma-separated tags. Use commas to add multiple values.",
        }
        for key, text in intent_tooltips.items():
            self._apply_tooltip(self._intent_edits[key], text)

        frame_tooltips = {
            self._frame_mode_combo: (
                "Choose whether to save defaults only, generate rows, or edit rows "
                "manually."
            ),
            self._generator_field_combo: (
                "Select which mapped field the generator will write into each row."
            ),
            self._generator_type_combo: (
                "Choose how generator values are produced: explicit list, numeric "
                "sweep, or one constant over a range."
            ),
            self._use_discovered_frames_checkbox: (
                "Use the discovered frame order and count from the loaded target "
                "instead of only the manual frame range."
            ),
            self._gen_frame_start: "First frame index to include when generating rows.",
            self._gen_frame_end: "Last frame index to include when generating rows.",
            self._gen_reason_edit: "Short reason text stored with the generated rows.",
            self._explicit_values_edit: (
                "Comma-separated values. One value is applied to each generated row in order."
            ),
            self._sweep_start_edit: "Starting numeric value for the generated sweep.",
            self._sweep_stop_edit: "Final numeric value for the generated sweep.",
            self._sweep_step_edit: "Step size between generated sweep values.",
            self._generate_button: (
                "Create rows from the generator settings and append them to the editor table."
            ),
            self._manual_start_spin: "Start frame for the manual row you are editing.",
            self._manual_end_spin: "End frame for the manual row you are editing.",
            self._manual_field_combo: "Select the mapped field to override on this row.",
            self._manual_custom_key_edit: (
                "Dot-path key for a custom override field that is not listed in the mapping."
            ),
            self._manual_reason_edit: "Short reason text stored with the manual row.",
            self._add_row_button: (
                "Add a new row or replace the currently selected row with these values."
            ),
            self._remove_row_button: "Delete the selected rows from the editor table.",
            self._clear_rows_button: (
                "Remove every staged row from the editor table. Saved rows stay on disk until you save."
            ),
            self._rows_table: (
                "Staged override rows. Click a row to load it back into the manual editor."
            ),
        }
        for widget, text in frame_tooltips.items():
            self._apply_tooltip(widget, text)

        review_tooltips = {
            self._refresh_review_button: (
                "Rebuild validation messages and the JSON preview from the current form values."
            ),
            self._review_warnings: (
                "Read-only validation and merge messages for the current draft."
            ),
            self._review_json: (
                "Read-only JSON preview of the datacard that will be saved."
            ),
            self.validate_button: (
                "Run validation without saving so you can review errors and warnings first."
            ),
            self.save_button: (
                "Validate and write acquisition_datacard.json for the loaded target folder."
            ),
            self.close_button: (
                "Close the wizard without saving any unsaved edits from this session."
            ),
        }
        for widget, text in review_tooltips.items():
            self._apply_tooltip(widget, text)

        for key, editor in self._defaults_editors.items():
            field_spec = self._spec_for_key(key)
            if field_spec is not None:
                self._set_field_editor_tooltip(editor, field_spec, "default")

    def _install_drag_filters(self) -> None:
        configure_secondary_window(self, draggable=True)

    def _review_widgets_ready(self) -> bool:
        return hasattr(self, "_review_json") and hasattr(
            self,
            "_review_warnings",
        )

    def _refresh_mapping_warnings(self) -> None:
        if self._mapping.warnings:
            self._mapping_warning_label.setText(
                " | ".join(self._mapping.warnings),
            )
        else:
            self._mapping_warning_label.setText("")

    def _reload_mapping(self) -> None:
        self._mapping = load_field_mapping()
        self._rebuild_defaults_form()
        self._rebuild_field_combos()
        self._refresh_ebus_field_states()
        self._refresh_mapping_warnings()
        self._configure_tooltips()
        self._populate_from_model()

    def _rebuild_field_combos(self) -> None:
        current_manual_key = self._current_manual_field_key()
        current_gen_key = self._current_generator_field_key()

        self._generator_field_combo.clear()
        for spec in self._override_specs():
            self._generator_field_combo.addItem(spec.label, spec.key)
        idx = self._generator_field_combo.findData(current_gen_key)
        if idx < 0 and self._generator_field_combo.count() > 0:
            idx = 0
        if idx >= 0:
            self._generator_field_combo.setCurrentIndex(idx)

        self._manual_field_combo.clear()
        for spec in self._override_specs():
            self._manual_field_combo.addItem(spec.label, spec.key)
        self._manual_field_combo.addItem("Custom key...", "__custom__")
        idx = self._manual_field_combo.findData(current_manual_key)
        if idx < 0 and self._manual_field_combo.count() > 0:
            idx = 0
        if idx >= 0:
            self._manual_field_combo.setCurrentIndex(idx)

        self._update_generator_editor()
        self._update_manual_editor()

    def _browse_folder(self) -> None:
        start = self._folder_edit.text().strip() or str(Path.home())
        folder = qtw.QFileDialog.getExistingDirectory(
            self,
            "Select Acquisition Folder",
            start,
        )
        if not folder:
            return
        self._folder_edit.setText(folder)
        self._load_target()

    def _load_target(self) -> None:
        folder = self._folder_edit.text().strip()
        if not folder:
            return
        path = Path(folder)
        if not path.is_dir():
            self._target_state_label.setText("Target folder does not exist.")
            self._validation_state_text = "Invalid target"
            self._validation_state_level = "error"
            self._refresh_wizard_header_state()
            return

        self._model = load_acquisition_datacard(path)
        self._validation_state_text = "Loaded"
        self._validation_state_level = "success"
        self._loaded_index_base = int(self._model.index_base)
        index = self._index_base_combo.findData(self._loaded_index_base)
        if index >= 0:
            self._index_base_combo.setCurrentIndex(index)
        self._apply_index_base_to_spinboxes()
        self._load_ebus_state(path)
        self._existing_rows = deepcopy(self._model.overrides)
        self._row_entries.clear()
        self._rebuild_field_combos()
        self._refresh_ebus_field_states()
        self._refresh_rows_table()

        exists = self._model.source_exists
        self._target_state_label.setText(
            (
                f"Loaded existing datacard: {self._model.source_path}"
                if exists
                else f"Creating new datacard at: {self._model.source_path}"
            ),
        )
        if self._ebus_attached:
            self._target_state_label.setText(
                self._target_state_label.text()
                + "\nDetected eBUS snapshot. Snapshot-backed Defaults use acquisition-wide baseline rules, while frame-targeted overrides remain available."
            )
        self._existing_count_label.setText(
            f"Existing rows: {len(self._existing_rows)}",
        )
        self._append_existing_checkbox.setChecked(bool(self._existing_rows))
        self._load_existing_button.setEnabled(bool(self._existing_rows))

        frame_count = len(self._model.frame_indices)
        self._frame_info_label.setText(
            f"Frame discovery: {frame_count} frame(s), mode={self._model.frame_index_mode}",
        )
        self._populate_from_model()
        self._refresh_review()
        self._refresh_wizard_header_state()

    def _populate_from_model(self) -> None:
        if self._model is None:
            return

        for key, edit in self._identity_edits.items():
            value = self._model.identity.get(key)
            edit.setText("" if value is None else str(value))

        for key, edit in self._paths_edits.items():
            value = self._model.paths.get(key)
            if key == "frames_dir" and value in (None, ""):
                value = "frames"
            edit.setText("" if value is None else str(value))

        for key, edit in self._intent_edits.items():
            value = self._model.intent.get(key)
            if key == "tags":
                if isinstance(value, list):
                    edit.setText(", ".join(str(item) for item in value))
                else:
                    edit.setText("" if value is None else str(value))
            else:
                edit.setText("" if value is None else str(value))

        defaults_source = self._model.defaults
        for key, editor in self._defaults_editors.items():
            spec = self._field_spec_by_key().get(key)
            if spec is None:
                continue
            resolution = self._ebus_resolution_by_key.get(key)
            if resolution is not None and resolution.snapshot_present:
                self._set_editor_value(
                    editor,
                    spec,
                    resolution.effective_value,
                )
                continue
            self._set_editor_value(
                editor,
                spec,
                get_dot_path(defaults_source, key),
            )
        self._refresh_ebus_field_states()

    def _on_index_base_changed(self) -> None:
        self._apply_index_base_to_spinboxes()
        if self._loaded_index_base is None:
            self._index_warning_label.setText("")
            self._refresh_wizard_header_state()
            return
        current = int(self._index_base_combo.currentData())
        if current == self._loaded_index_base:
            self._index_warning_label.setText(
                f"Using detected index base: {self._loaded_index_base}.",
            )
            self._refresh_wizard_header_state()
            return
        self._index_warning_label.setText(
            (
                "Index base changed from loaded file. Frame ranges are not "
                "auto-converted; verify selectors before saving."
            ),
        )
        self._refresh_wizard_header_state()
        self._refresh_review()

    def _apply_index_base_to_spinboxes(self) -> None:
        base = int(self._index_base_combo.currentData())
        minimum = 1 if base == 1 else 0
        for spin in (
            self._gen_frame_start,
            self._gen_frame_end,
            self._manual_start_spin,
            self._manual_end_spin,
        ):
            spin.setMinimum(minimum)
            if spin.value() < minimum:
                spin.setValue(minimum)

    def _load_existing_rows_into_editor(self) -> None:
        self._row_entries.clear()
        for row in self._existing_rows:
            for key, value in row.changes.items():
                self._row_entries.append(
                    _RowEntry(
                        frame_start=int(row.frame_start),
                        frame_end=int(row.frame_end),
                        key=str(key),
                        value=deepcopy(value),
                        reason=row.reason,
                    ),
                )
        self._append_existing_checkbox.setChecked(False)
        self._refresh_rows_table()
        self._refresh_review()

    def _current_generator_field_key(self) -> str:
        data = self._generator_field_combo.currentData()
        return str(data) if data is not None else ""

    def _current_manual_field_key(self) -> str:
        data = self._manual_field_combo.currentData()
        return str(data) if data is not None else ""

    def _replace_layout_widget(
        self,
        layout: qtw.QLayout,
        current_widget: qtw.QWidget,
        new_widget: qtw.QWidget,
    ) -> qtw.QWidget:
        layout.removeWidget(current_widget)
        current_widget.deleteLater()
        layout.addWidget(new_widget, 1)
        return new_widget

    def _on_generator_field_changed(self) -> None:
        self._update_generator_editor()

    def _on_manual_field_changed(self) -> None:
        self._manual_custom_key_edit.setVisible(
            self._current_manual_field_key() == "__custom__",
        )
        self._update_manual_editor()

    def _spec_for_key(self, key: str) -> Optional[FieldSpec]:
        return self._field_spec_by_key().get(key)

    def _update_generator_editor(self) -> None:
        key = self._current_generator_field_key()
        spec = self._spec_for_key(key)
        if spec is None:
            return
        self._constant_value_editor = self._replace_layout_widget(
            self._constant_value_layout,
            self._constant_value_editor,
            self._create_editor(spec),
        )
        self._set_field_editor_tooltip(
            self._constant_value_editor,
            spec,
            "generator",
        )

    def _update_manual_editor(self) -> None:
        key = self._current_manual_field_key()
        spec = self._spec_for_key(key)
        if key == "__custom__" or spec is None:
            spec = FieldSpec(
                key="__custom__",
                label="Custom",
                group="Custom",
                value_type="string",
            )
        self._manual_value_editor = self._replace_layout_widget(
            self._manual_value_layout,
            self._manual_value_editor,
            self._create_editor(spec),
        )
        if key == "__custom__":
            self._apply_tooltip(
                self._manual_value_editor,
                (
                    "Value for the custom override key. Enter plain text, or JSON "
                    "for numbers, booleans, lists, or objects."
                ),
            )
        else:
            self._set_field_editor_tooltip(
                self._manual_value_editor,
                spec,
                "manual",
            )

    def _update_generator_mode_widgets(self) -> None:
        mode = str(self._generator_type_combo.currentData())
        mapping = {
            "explicit_list": 0,
            "numeric_sweep": 1,
            "constant_range": 2,
        }
        self._generator_stack.setCurrentIndex(mapping.get(mode, 0))

    def _update_frame_mode_visibility(self) -> None:
        mode = str(self._frame_mode_combo.currentData())
        self._generator_group.setVisible(mode == "generate")
        manual_visible = mode in {"generate", "manual"}
        self._rows_table.setVisible(manual_visible)
        self._rows_summary_label.setVisible(manual_visible)
        self._add_row_button.setEnabled(mode == "manual")
        self._remove_row_button.setEnabled(manual_visible)
        self._clear_rows_button.setEnabled(manual_visible)
        self._refresh_review()

    def _frame_order_from_discovery(self) -> list[int]:
        if self._model is None:
            return []
        count = len(self._model.frame_indices)
        base = int(self._index_base_combo.currentData())
        return [base + idx for idx in range(count)]

    def _parse_generator_values(self) -> list[Any]:
        key = self._current_generator_field_key()
        spec = self._spec_for_key(key)
        if spec is None:
            return []
        mode = str(self._generator_type_combo.currentData())
        if mode == "explicit_list":
            raw_values = [
                token.strip()
                for token in self._explicit_values_edit.text().split(",")
            ]
            values: list[Any] = []
            for token in raw_values:
                if not token:
                    continue
                values.append(self._coerce_value(token, spec))
            return values
        if mode == "numeric_sweep":
            start, stop, step = self._numeric_sweep_values()
            plan = FieldPlan(
                key=key,
                start_value=start,
                stop_value=stop,
                step_value=step,
                reason=self._gen_reason_edit.text().strip() or "generated",
            )
            rows = generate_overrides(
                frame_plan=FramePlan(start_frame=0, end_frame=0),
                field_plan=plan,
                mode="numeric_sweep",
            )
            first_key = next(iter(rows[0].changes.keys()), key) if rows else key
            return [row.changes[first_key] for row in rows]
        if mode == "constant_range":
            return [self._get_editor_value(self._constant_value_editor, spec)]
        return []

    def _coerce_value(self, text: str, spec: FieldSpec) -> Any:
        if spec.value_type == "int":
            return _to_int(text, 0)
        if spec.value_type == "float":
            return _to_float(text, 0.0)
        if spec.value_type == "bool":
            lowered = text.strip().lower()
            return lowered in {"1", "true", "yes", "on"}
        if spec.value_type == "enum":
            return text.strip()
        return text

    def _generate_rows(self) -> None:
        key = self._current_generator_field_key()
        spec = self._spec_for_key(key)
        if spec is None:
            return
        mode = str(self._generator_type_combo.currentData())
        reason = self._gen_reason_edit.text().strip() or "generated"
        start_frame = int(self._gen_frame_start.value())
        end_frame = int(self._gen_frame_end.value())
        use_discovered = self._use_discovered_frames_checkbox.isChecked()
        frame_indices = self._frame_order_from_discovery() if use_discovered else []
        frame_plan = FramePlan(
            index_base=int(self._index_base_combo.currentData()),
            start_frame=start_frame,
            end_frame=end_frame,
            frame_indices=frame_indices,
        )
        try:
            if mode == "explicit_list":
                values = self._parse_generator_values()
                rows = generate_overrides(
                    frame_plan=frame_plan,
                    field_plan=FieldPlan(
                        key=key,
                        values=values,
                        reason=reason,
                    ),
                    mode="explicit_list",
                )
            elif mode == "numeric_sweep":
                start, stop, step = self._numeric_sweep_values()
                rows = generate_overrides(
                    frame_plan=frame_plan,
                    field_plan=FieldPlan(
                        key=key,
                        start_value=start,
                        stop_value=stop,
                        step_value=step,
                        reason=reason,
                    ),
                    mode="numeric_sweep",
                )
            else:
                constant_value = self._get_editor_value(
                    self._constant_value_editor,
                    spec,
                )
                rows = generate_overrides(
                    frame_plan=frame_plan,
                    field_plan=FieldPlan(
                        key=key,
                        constant_value=constant_value,
                        reason=reason,
                    ),
                    mode="constant_range",
                )
        except Exception as exc:
            qtw.QMessageBox.warning(
                self,
                "Generator Error",
                str(exc),
            )
            return

        for row in rows:
            for change_key, change_value in row.changes.items():
                self._row_entries.append(
                    _RowEntry(
                        frame_start=row.frame_start,
                        frame_end=row.frame_end,
                        key=change_key,
                        value=deepcopy(change_value),
                        reason=row.reason,
                    ),
                )
        self._refresh_rows_table()
        self._refresh_review()

    def _manual_row_from_inputs(self) -> Optional[_RowEntry]:
        start = int(self._manual_start_spin.value())
        end = int(self._manual_end_spin.value())
        if start > end:
            start, end = end, start
        key = self._current_manual_field_key()
        if key == "__custom__":
            key = self._manual_custom_key_edit.text().strip()
            if not key:
                return None
            value = _parse_json_literal(
                self._manual_value_editor.text()
                if isinstance(self._manual_value_editor, qtw.QLineEdit)
                else "",
            )
        else:
            spec = self._spec_for_key(key)
            if spec is None:
                return None
            value = self._get_editor_value(self._manual_value_editor, spec)
        reason = self._manual_reason_edit.text().strip() or "manual"
        return _RowEntry(
            frame_start=start,
            frame_end=end,
            key=key,
            value=value,
            reason=reason,
        )

    def _add_or_update_manual_row(self) -> None:
        entry = self._manual_row_from_inputs()
        if entry is None:
            qtw.QMessageBox.warning(
                self,
                "Invalid Manual Row",
                "Please provide a valid field key and value.",
            )
            return
        selected = self._rows_table.selectedIndexes()
        if selected:
            row_index = selected[0].row()
            if 0 <= row_index < len(self._row_entries):
                self._row_entries[row_index] = entry
            else:
                self._row_entries.append(entry)
        else:
            self._row_entries.append(entry)
        self._refresh_rows_table()
        self._refresh_review()

    def _remove_selected_rows(self) -> None:
        indexes = self._rows_table.selectionModel().selectedRows()
        if not indexes:
            return
        to_delete = sorted((index.row() for index in indexes), reverse=True)
        for row in to_delete:
            if 0 <= row < len(self._row_entries):
                del self._row_entries[row]
        self._refresh_rows_table()
        self._refresh_review()

    def _clear_editor_rows(self) -> None:
        self._row_entries.clear()
        self._refresh_rows_table()
        self._refresh_review()

    def _refresh_rows_table(self) -> None:
        self._rows_table.setRowCount(len(self._row_entries))
        for row_idx, entry in enumerate(self._row_entries):
            values = (
                str(entry.frame_start),
                str(entry.frame_end),
                entry.key,
                _display_value(entry.value),
                entry.reason,
            )
            for col_idx, value in enumerate(values):
                item = qtw.QTableWidgetItem(value)
                align = Qt.AlignCenter if col_idx in {0, 1} else Qt.AlignLeft
                item.setTextAlignment(align | Qt.AlignVCenter)
                self._rows_table.setItem(row_idx, col_idx, item)
        self._rows_summary_label.setText(f"Editor rows: {len(self._row_entries)}")
        self._refresh_wizard_header_state()

    def _on_row_table_clicked(self, row: int, _col: int) -> None:
        if not (0 <= row < len(self._row_entries)):
            return
        entry = self._row_entries[row]
        self._manual_start_spin.setValue(entry.frame_start)
        self._manual_end_spin.setValue(entry.frame_end)
        key_index = self._manual_field_combo.findData(entry.key)
        if key_index >= 0:
            self._manual_field_combo.setCurrentIndex(key_index)
            spec = self._spec_for_key(entry.key)
            if spec is not None:
                self._set_editor_value(
                    self._manual_value_editor,
                    spec,
                    entry.value,
                )
        else:
            key_index = self._manual_field_combo.findData("__custom__")
            if key_index >= 0:
                self._manual_field_combo.setCurrentIndex(key_index)
                self._manual_custom_key_edit.setText(entry.key)
                if isinstance(self._manual_value_editor, qtw.QLineEdit):
                    self._manual_value_editor.setText(_display_value(entry.value))
        self._manual_reason_edit.setText(entry.reason)

    def _rows_grouped_for_model(self) -> list[OverrideRow]:
        grouped: "OrderedDict[tuple[int, int, str], dict[str, Any]]" = OrderedDict()
        for entry in self._row_entries:
            key = (entry.frame_start, entry.frame_end, entry.reason)
            grouped.setdefault(key, {})
            grouped[key][entry.key] = deepcopy(entry.value)

        rows: list[OverrideRow] = []
        for (start, end, reason), changes in grouped.items():
            rows.append(
                OverrideRow(
                    frame_start=int(start),
                    frame_end=int(end),
                    changes=changes,
                    reason=reason,
                ),
            )
        return rows

    def _load_ebus_state(self, acquisition_root: Path) -> None:
        """Load eBUS baseline and override state for the current target."""
        if self._model is None:
            self._ebus_attached = False
            self._ebus_resolution_by_key = {}
            return
        resolutions = resolve_ebus_canonical_fields(
            acquisition_root,
            {
                "defaults": deepcopy(self._model.defaults),
                "external_sources": deepcopy(self._model.external_sources),
            },
            mapping=self._mapping,
        )
        self._ebus_attached = bool(resolutions.snapshot_loaded)
        self._ebus_resolution_by_key = resolutions.by_key()

    def _refresh_ebus_field_states(self) -> None:
        """Apply source badges and editability rules to eBUS-managed fields."""
        for spec in self._defaults_specs():
            editor = self._defaults_editors.get(spec.key)
            note = self._defaults_editor_notes.get(spec.key)
            if editor is None:
                continue
            resolution = self._ebus_resolution_by_key.get(spec.key)
            is_snapshot_backed = bool(
                resolution is not None and resolution.snapshot_present
            )
            editor.setEnabled(
                not is_snapshot_backed
                or not bool(resolution.defaults_locked if resolution is not None else False),
            )
            if note is None:
                continue
            if not is_snapshot_backed or resolution is None:
                note.setVisible(False)
                continue
            if resolution.provenance == "ebus_override":
                note.setText("Source: acquisition-wide eBUS override over snapshot")
            elif resolution.provenance == "acquisition_default":
                note.setText("Source: acquisition default over eBUS snapshot")
            elif not resolution.defaults_locked:
                note.setText("Source: eBUS snapshot baseline (editable acquisition default)")
            else:
                note.setText("Source: eBUS snapshot baseline (read-only)")
            note.setVisible(True)
        self._refresh_wizard_header_state()

    def _refresh_wizard_header_state(self) -> None:
        """Refresh top-of-dialog target and validation summary."""
        if not hasattr(self, "_header") or not hasattr(self, "_summary_strip"):
            return
        target_loaded = bool(self._model is not None and self._model.source_path is not None)
        merge_mode = (
            "Append existing"
            if getattr(self, "_append_existing_checkbox", None) is not None
            and self._append_existing_checkbox.isChecked()
            else "Replace with editor"
        )
        index_base = (
            int(self._index_base_combo.currentData())
            if hasattr(self, "_index_base_combo") and self._index_base_combo.currentData() is not None
            else 0
        )
        self._header.set_chips(
            [
                ChipSpec(
                    "Target loaded" if target_loaded else "No target",
                    level="success" if target_loaded else "warning",
                ),
                ChipSpec(
                    "eBUS attached" if self._ebus_attached else "No eBUS snapshot",
                    level="info" if self._ebus_attached else "neutral",
                ),
                ChipSpec(
                    self._validation_state_text,
                    level=self._validation_state_level,
                ),
            ],
        )
        self._summary_strip.set_items(
            [
                SummaryItem(
                    "Index Base",
                    f"{index_base}-based",
                    level="info",
                ),
                SummaryItem(
                    "Existing Rows",
                    str(len(self._existing_rows)),
                    level="success" if self._existing_rows else "neutral",
                ),
                SummaryItem(
                    "Editor Rows",
                    str(len(self._row_entries)),
                    level="info" if self._row_entries else "neutral",
                ),
                SummaryItem(
                    "Merge Mode",
                    merge_mode,
                    level="warning" if "Append" in merge_mode else "neutral",
                ),
                SummaryItem(
                    "Target",
                    self._model.source_path.parent.name
                    if self._model is not None and self._model.source_path is not None
                    else "None",
                    level="success" if target_loaded else "neutral",
                ),
            ],
        )

    def _build_model_from_ui(self) -> Optional[AcquisitionDatacardModel]:
        if self._model is None or self._model.source_path is None:
            return None

        model = deepcopy(self._model)
        model.index_base = int(self._index_base_combo.currentData())

        for key, edit in self._identity_edits.items():
            if key in self._AUTO_IDENTITY_KEYS:
                continue
            value = edit.text().strip()
            model.identity[key] = value if value else None

        for key, edit in self._paths_edits.items():
            value = edit.text().strip()
            if key == "frames_dir":
                model.paths[key] = value or "frames"
            else:
                model.paths[key] = value if value else None

        for key, edit in self._intent_edits.items():
            text = edit.text().strip()
            if key == "tags":
                tags = [token.strip() for token in text.split(",") if token.strip()]
                model.intent[key] = tags
            else:
                model.intent[key] = text if text else ""

        defaults_payload = deepcopy(model.defaults)
        if not isinstance(defaults_payload, dict):
            defaults_payload = {}
        external_sources = deepcopy(model.external_sources)
        if not isinstance(external_sources, dict):
            external_sources = {}
        ebus_block = deepcopy(external_sources.get("ebus"))
        if not isinstance(ebus_block, dict):
            ebus_block = {}
        raw_overrides = ebus_block.get("overrides")
        if isinstance(raw_overrides, dict):
            ebus_overrides = {
                str(raw_key).strip(): deepcopy(raw_value)
                for raw_key, raw_value in raw_overrides.items()
                if str(raw_key).strip()
            }
        else:
            ebus_overrides = {}
        for key, editor in self._defaults_editors.items():
            spec = self._spec_for_key(key)
            if spec is None:
                continue
            resolution = self._ebus_resolution_by_key.get(key)
            if resolution is not None and resolution.snapshot_present:
                if resolution.defaults_locked:
                    delete_dot_path(defaults_payload, key)
                    ebus_overrides.pop(resolution.ebus_label, None)
                    continue
                value = self._get_editor_value(editor, spec)
                existing_default = (
                    get_dot_path(self._model.defaults, key)
                    if isinstance(self._model.defaults, dict)
                    else None
                )
                if value is None:
                    delete_dot_path(defaults_payload, key)
                elif existing_default is not None or value != resolution.snapshot_value:
                    set_dot_path(defaults_payload, key, deepcopy(value))
                else:
                    delete_dot_path(defaults_payload, key)
                ebus_overrides.pop(resolution.ebus_label, None)
                continue
            value = self._get_editor_value(editor, spec)
            if value is None:
                delete_dot_path(defaults_payload, key)
                continue
            set_dot_path(defaults_payload, key, value)
        model.defaults = defaults_payload
        if ebus_overrides:
            ebus_block["overrides"] = ebus_overrides
        else:
            ebus_block.pop("overrides", None)
        if ebus_block:
            external_sources["ebus"] = ebus_block
        else:
            external_sources.pop("ebus", None)
        model.external_sources = external_sources

        mode = str(self._frame_mode_combo.currentData())
        new_rows = self._rows_grouped_for_model()
        if mode == "defaults_only":
            new_rows = []

        if self._append_existing_checkbox.isChecked() and self._existing_rows:
            merge = append_overrides(
                existing_rows=self._existing_rows,
                new_rows=new_rows,
                policy="last_write_wins",
            )
            model.overrides = merge.rows
            self._merge_warnings = merge.warnings
        else:
            model.overrides = new_rows
            self._merge_warnings = []

        return model

    def _refresh_review(self) -> None:
        if not self._review_widgets_ready():
            return
        model = self._build_model_from_ui()
        if model is None:
            self._review_json.clear()
            self._review_warnings.setPlainText("Load a target acquisition first.")
            self._validation_state_text = "No target"
            self._validation_state_level = "warning"
            self._refresh_wizard_header_state()
            return
        mapping = self._mapping
        report = validate_datacard(model, mapping)
        payload = datacard_to_payload(model)
        self._review_json.setPlainText(
            json.dumps(payload, indent=2, ensure_ascii=True),
        )
        warnings = list(self._merge_warnings)
        warnings.extend(report.warnings)
        if report.errors:
            warnings.extend([f"ERROR: {message}" for message in report.errors])
        if not warnings:
            warnings = ["No validation warnings."]
        self._review_warnings.setPlainText("\n".join(warnings))
        if report.errors:
            self._validation_state_text = "Validation errors"
            self._validation_state_level = "error"
        elif report.warnings:
            self._validation_state_text = "Warnings present"
            self._validation_state_level = "warning"
        else:
            self._validation_state_text = "Ready to save"
            self._validation_state_level = "success"
        self._refresh_wizard_header_state()

    def _validate_current_model(self) -> None:
        model = self._build_model_from_ui()
        if model is None:
            qtw.QMessageBox.warning(
                self,
                "Validation",
                "Load a target acquisition first.",
            )
            return
        report = validate_datacard(model, self._mapping)
        self._refresh_review()
        if report.errors:
            qtw.QMessageBox.critical(
                self,
                "Validation Failed",
                "\n".join(report.errors),
            )
            return
        msg = "Validation passed."
        if report.warnings:
            msg += "\n\nWarnings:\n" + "\n".join(report.warnings[:20])
        qtw.QMessageBox.information(self, "Validation", msg)

    def _save(self) -> None:
        model = self._build_model_from_ui()
        if model is None or model.source_path is None:
            qtw.QMessageBox.warning(
                self,
                "Save Datacard",
                "Load a target acquisition first.",
            )
            return
        report = validate_datacard(model, self._mapping)
        if report.errors:
            qtw.QMessageBox.critical(
                self,
                "Save Blocked",
                "Fix validation errors before saving:\n\n" + "\n".join(report.errors),
            )
            self._refresh_review()
            return
        try:
            save_acquisition_datacard(model.source_path, model)
        except Exception as exc:
            qtw.QMessageBox.critical(
                self,
                "Save Failed",
                str(exc),
            )
            return
        self._model = load_acquisition_datacard(model.source_path.parent)
        self._existing_rows = deepcopy(self._model.overrides)
        self._existing_count_label.setText(
            f"Existing rows: {len(self._existing_rows)}",
        )
        self._target_state_label.setText(f"Saved: {model.source_path}")
        self._refresh_review()
        qtw.QMessageBox.information(
            self,
            "Datacard Saved",
            f"Saved acquisition datacard:\n{model.source_path}",
        )

    def _on_tab_changed(self, tab_index: int) -> None:
        if tab_index == 4:
            self._refresh_review()


class AcquisitionDatacardWizardPlugin:
    """Plugin entrypoint for acquisition datacard authoring."""

    plugin_id = "acquisition_datacard_wizard"
    display_name = "Acquisition Datacard Wizard"
    dependencies: tuple[str, ...] = ()

    @staticmethod
    def populate_page_menu(host_window: qtw.QWidget, menu: qtw.QMenu) -> None:
        """Populate plugin menu with wizard actions."""
        open_action = menu.addAction("Open Wizard...")
        open_action.setToolTip(
            "Open the acquisition datacard wizard for the selected folder, including any app-overridable eBUS-backed fields.",
        )
        open_action.setStatusTip(
            "Open the acquisition datacard wizard for the selected folder, including any app-overridable eBUS-backed fields.",
        )
        open_action.triggered.connect(
            lambda _checked=False: AcquisitionDatacardWizardPlugin.open_wizard(
                host_window,
            ),
        )
        menu.addSeparator()
        mapping_action = menu.addAction("Open Mapping Folder")
        mapping_action.setToolTip(
            "Show the JSON mapping file location used to build the wizard fields.",
        )
        mapping_action.setStatusTip(
            "Show the JSON mapping file location used to build the wizard fields.",
        )
        mapping_action.triggered.connect(
            lambda _checked=False: AcquisitionDatacardWizardPlugin.open_mapping_folder(
                host_window,
            ),
        )

    @staticmethod
    def open_wizard(host_window: qtw.QWidget) -> None:
        """Launch wizard dialog."""
        initial = ""
        folder_edit = getattr(host_window, "folder_edit", None)
        if isinstance(folder_edit, qtw.QLineEdit):
            initial = folder_edit.text().strip()
        dialog = AcquisitionDatacardWizardDialog(host_window, initial_folder=initial)
        dialog.place_near_host(host_window)
        dialog.exec()

    @staticmethod
    def open_mapping_folder(host_window: qtw.QWidget) -> None:
        """Open file explorer at the folder containing the mapping file."""
        path = mapping_config_path()
        folder = path.parent
        folder.mkdir(parents=True, exist_ok=True)
        opened = QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(folder)),
        )
        if opened:
            return
        qtw.QMessageBox.warning(
            host_window,
            "Open Mapping Folder",
            (
                "Could not open the mapping folder automatically.\n\n"
                f"Folder: {folder}\n"
                f"Mapping file: {path}"
            ),
        )


register_page_plugin(AcquisitionDatacardWizardPlugin, page="data")
