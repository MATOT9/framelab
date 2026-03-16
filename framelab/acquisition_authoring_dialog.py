"""Workflow-native acquisition creation dialog with preview support."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets as qtw

from .session_manager import (
    SessionIndex,
    create_acquisition_batch,
    inspect_session,
    preview_acquisition_batch,
)
from .ui_primitives import ChipSpec, SummaryItem, build_page_header, build_summary_strip
from .window_drag import configure_secondary_window


class AcquisitionAuthoringDialog(qtw.QDialog):
    """Create one or more acquisitions under a workflow-selected session."""

    def __init__(
        self,
        session_root: str | Path,
        parent: qtw.QWidget | None = None,
        *,
        initial_mode: str = "next",
    ) -> None:
        super().__init__(parent)
        self._session_root = Path(session_root).expanduser().resolve()
        self._session_index: SessionIndex = inspect_session(self._session_root)
        self.created_paths: tuple[Path, ...] = ()
        self.deleted_paths: tuple[Path, ...] = ()
        self.renamed_paths: tuple[tuple[Path, Path], ...] = ()

        self.setWindowTitle("Create Acquisitions")
        configure_secondary_window(self)
        self.setModal(True)
        self.resize(860, 640)
        self.setMinimumSize(760, 560)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._header = build_page_header(
            "Create Acquisitions",
            (
                "Create one or more acquisition folders under the selected session. "
                "Use preview to verify numbering, labels, and collisions before committing."
            ),
        )
        layout.addWidget(self._header)

        self._summary_strip = build_summary_strip()
        layout.addWidget(self._summary_strip)

        form_panel = qtw.QFrame()
        form_panel.setObjectName("CommandBar")
        form_layout = qtw.QGridLayout(form_panel)
        form_layout.setContentsMargins(12, 10, 12, 10)
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(8)

        mode_label = qtw.QLabel("Mode")
        mode_label.setObjectName("SectionTitle")
        form_layout.addWidget(mode_label, 0, 0)

        self._mode_combo = qtw.QComboBox()
        self._mode_combo.addItem("Next Available", "next")
        self._mode_combo.addItem("Manual Number", "manual")
        self._mode_combo.addItem("Batch Create", "batch")
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        form_layout.addWidget(self._mode_combo, 0, 1)

        number_label = qtw.QLabel("Starting Number")
        number_label.setObjectName("SectionTitle")
        form_layout.addWidget(number_label, 0, 2)

        self._starting_number_spin = qtw.QSpinBox()
        self._starting_number_spin.setRange(0, 999999)
        self._starting_number_spin.valueChanged.connect(self._refresh_preview)
        form_layout.addWidget(self._starting_number_spin, 0, 3)

        count_label = qtw.QLabel("Count")
        count_label.setObjectName("SectionTitle")
        form_layout.addWidget(count_label, 1, 0)

        self._count_spin = qtw.QSpinBox()
        self._count_spin.setRange(1, 999)
        self._count_spin.setValue(1)
        self._count_spin.valueChanged.connect(self._refresh_preview)
        form_layout.addWidget(self._count_spin, 1, 1)

        labels_label = qtw.QLabel("Optional Labels")
        labels_label.setObjectName("SectionTitle")
        form_layout.addWidget(labels_label, 1, 2)

        self._labels_edit = qtw.QPlainTextEdit()
        self._labels_edit.setPlaceholderText(
            "Optional labels, one per line.\n"
            "Single create: first line only.\n"
            "Batch create: each line applies to one row.",
        )
        self._labels_edit.setMinimumHeight(92)
        self._labels_edit.setTabChangesFocus(True)
        self._labels_edit.textChanged.connect(self._refresh_preview)
        form_layout.addWidget(self._labels_edit, 1, 3, 2, 1)

        self._mode_hint = qtw.QLabel("")
        self._mode_hint.setObjectName("MutedLabel")
        self._mode_hint.setWordWrap(True)
        form_layout.addWidget(self._mode_hint, 2, 0, 1, 3)

        layout.addWidget(form_panel)

        self._warning_label = qtw.QLabel("")
        self._warning_label.setObjectName("MutedLabel")
        self._warning_label.setWordWrap(True)
        layout.addWidget(self._warning_label)

        self._preview_table = qtw.QTableWidget(0, 4)
        self._preview_table.setHorizontalHeaderLabels(
            ["Number", "Label", "Folder", "Result"],
        )
        self._preview_table.setEditTriggers(qtw.QAbstractItemView.NoEditTriggers)
        self._preview_table.setSelectionMode(qtw.QAbstractItemView.NoSelection)
        self._preview_table.setWordWrap(False)
        self._preview_table.verticalHeader().setVisible(False)
        header = self._preview_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setSectionResizeMode(0, qtw.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, qtw.QHeaderView.Stretch)
        header.setSectionResizeMode(2, qtw.QHeaderView.Stretch)
        header.setSectionResizeMode(3, qtw.QHeaderView.ResizeToContents)
        layout.addWidget(self._preview_table, 1)

        actions = qtw.QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        cancel_button = qtw.QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)

        self._create_button = qtw.QPushButton("Create")
        self._create_button.setObjectName("AccentButton")
        self._create_button.clicked.connect(self._accept_creation)
        actions.addWidget(self._create_button)
        layout.addLayout(actions)

        initial_index = self._mode_combo.findData(initial_mode)
        self._mode_combo.setCurrentIndex(initial_index if initial_index >= 0 else 0)
        self._starting_number_spin.setValue(self._default_starting_number())
        self._refresh_summary()
        self._on_mode_changed()

    def _default_starting_number(self) -> int:
        if self._session_index.entries:
            return self._session_index.entries[-1].number + 1
        return self._session_index.starting_number

    def _current_mode(self) -> str:
        data = self._mode_combo.currentData()
        text = str(data).strip().lower() if data is not None else ""
        return text or "next"

    def _parsed_labels(self) -> tuple[str | None, ...]:
        lines = [
            line.strip()
            for line in self._labels_edit.toPlainText().splitlines()
            if line.strip()
        ]
        return tuple(line or None for line in lines)

    def _invalid_label_message(self, labels: tuple[str | None, ...]) -> str | None:
        for label in labels:
            if label is None:
                continue
            if "/" in label or "\\" in label:
                return "Labels cannot contain path separators."
        return None

    def _requested_plan(self) -> tuple[int, int | None, tuple[str | None, ...]]:
        mode = self._current_mode()
        labels = self._parsed_labels()
        if mode == "batch":
            return (self._count_spin.value(), self._starting_number_spin.value(), labels)
        if mode == "manual":
            label = labels[:1]
            return (1, self._starting_number_spin.value(), label)
        label = labels[:1]
        return (1, None, label)

    def _on_mode_changed(self) -> None:
        mode = self._current_mode()
        is_batch = mode == "batch"
        is_manual = mode in {"manual", "batch"}
        self._starting_number_spin.setEnabled(is_manual)
        self._count_spin.setEnabled(is_batch)
        if not is_batch:
            self._count_spin.setValue(1)
        if mode == "next":
            self._mode_hint.setText(
                "Creates one acquisition using the next available contiguous number.",
            )
        elif mode == "manual":
            self._mode_hint.setText(
                "Creates one acquisition using the explicit number shown below.",
            )
        else:
            self._mode_hint.setText(
                "Creates several acquisitions contiguously from the chosen starting number.",
            )
        self._refresh_preview()

    def _refresh_summary(self) -> None:
        numbering_valid = self._session_index.numbering_valid
        next_number = self._default_starting_number()
        self._header.set_chips(
            [
                ChipSpec(self._session_root.name, level="info"),
                ChipSpec(
                    "Numbering valid" if numbering_valid else "Needs reindex",
                    level="success" if numbering_valid else "warning",
                ),
                ChipSpec(
                    f"{len(self._session_index.entries)} existing",
                    level="neutral",
                ),
            ],
        )
        self._summary_strip.set_items(
            [
                SummaryItem("Session", self._session_root.name, level="info"),
                SummaryItem(
                    "Acquisitions",
                    str(len(self._session_index.entries)),
                    level="neutral",
                ),
                SummaryItem("Next Number", str(next_number), level="info"),
                SummaryItem(
                    "Numbering",
                    "Valid" if numbering_valid else "Warning",
                    level="success" if numbering_valid else "warning",
                    tooltip=self._session_index.warning_text,
                ),
            ],
        )

    def _refresh_preview(self) -> None:
        count, starting_number, labels = self._requested_plan()
        label_error = self._invalid_label_message(labels)
        preview = preview_acquisition_batch(
            self._session_root,
            count=count,
            starting_number=starting_number,
            labels=labels,
        )
        self._preview_table.setRowCount(0)
        collisions: list[str] = []
        for row, entry in enumerate(preview):
            self._preview_table.insertRow(row)
            values = [
                str(entry.number),
                entry.label or "",
                entry.folder_name,
                "Collision" if entry.collision_exists else "Ready",
            ]
            for column, value in enumerate(values):
                item = qtw.QTableWidgetItem(value)
                if column == 2:
                    item.setToolTip(str(entry.path))
                self._preview_table.setItem(row, column, item)
            if entry.collision_exists:
                collisions.append(entry.folder_name)
        self._preview_table.resizeColumnToContents(0)
        self._preview_table.resizeColumnToContents(3)

        warnings: list[str] = []
        if not self._session_index.numbering_valid:
            warnings.append(self._session_index.warning_text)
        if label_error:
            warnings.append(label_error)
        if collisions:
            joined = ", ".join(collisions[:3])
            suffix = f" (+{len(collisions) - 3} more)" if len(collisions) > 3 else ""
            warnings.append(f"Collision detected: {joined}{suffix}.")
        if (
            self._current_mode() == "batch"
            and labels
            and len(labels) != count
        ):
            warnings.append(
                "Batch preview uses one label per line; remaining rows stay unlabeled.",
            )
        self._warning_label.setText("\n".join(warnings))
        self._create_button.setText(
            "Create Batch" if self._current_mode() == "batch" else "Create Acquisition",
        )
        self._create_button.setEnabled(
            self._session_index.numbering_valid
            and label_error is None
            and not collisions
        )

    def _accept_creation(self) -> None:
        count, starting_number, labels = self._requested_plan()
        try:
            result = create_acquisition_batch(
                self._session_root,
                count=count,
                starting_number=starting_number,
                labels=labels,
            )
        except Exception as exc:
            qtw.QMessageBox.warning(self, "Create Acquisitions", str(exc))
            return
        self.created_paths = result.created_paths
        self.accept()
