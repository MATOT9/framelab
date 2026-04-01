"""Shared lightweight widgets for workflow-management surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt

from .ui_density import DensityTokens, comfortable_density_tokens
from .ui_primitives import StatusChip, make_status_chip


@dataclass(frozen=True, slots=True)
class WorkflowLineageEntry:
    """One row inside the compact workflow lineage rail."""

    label: str
    detail: str = ""
    tooltip: str = ""
    is_active: bool = False


class WorkflowBreadcrumbBar(qtw.QFrame):
    """Compact chip-based breadcrumb for workflow profile and ancestry."""

    def __init__(
        self,
        parent: qtw.QWidget | None = None,
        *,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SubtlePanel")
        layout = qtw.QHBoxLayout(self)
        if compact:
            layout.setContentsMargins(6, 4, 6, 4)
            layout.setSpacing(4)
        else:
            layout.setContentsMargins(10, 8, 10, 8)
            layout.setSpacing(6)
        self._layout = layout
        self._layout.addStretch(1)
        self.setVisible(False)

    def set_breadcrumb(
        self,
        *,
        profile_label: str | None,
        context_label: str | None = None,
        nodes: Iterable[tuple[str, str]] = (),
        empty_text: str | None = None,
    ) -> None:
        """Replace breadcrumb content with a profile badge and node chips."""

        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        breadcrumb_nodes = [(str(label), str(tooltip)) for label, tooltip in nodes if str(label).strip()]
        if not profile_label and not context_label and not breadcrumb_nodes and empty_text:
            self._layout.insertWidget(
                self._layout.count() - 1,
                make_status_chip(
                    str(empty_text).strip(),
                    level="neutral",
                    tooltip="No workflow selected",
                    parent=self,
                ),
            )
            self.setVisible(True)
            return
        if profile_label:
            self._layout.insertWidget(
                self._layout.count() - 1,
                make_status_chip(
                    str(profile_label).strip(),
                    level="info",
                    tooltip="Active workflow profile",
                    parent=self,
                ),
            )
        if context_label:
            if profile_label:
                arrow = qtw.QLabel("›", self)
                arrow.setObjectName("MutedLabel")
                arrow.setAlignment(Qt.AlignCenter)
                self._layout.insertWidget(self._layout.count() - 1, arrow)
            self._layout.insertWidget(
                self._layout.count() - 1,
                make_status_chip(
                    str(context_label).strip(),
                    level="neutral",
                    tooltip="Loaded workflow anchor scope",
                    parent=self,
                ),
            )
        for index, (label, tooltip) in enumerate(breadcrumb_nodes):
            if profile_label or context_label or index > 0:
                arrow = qtw.QLabel("›", self)
                arrow.setObjectName("MutedLabel")
                arrow.setAlignment(Qt.AlignCenter)
                self._layout.insertWidget(self._layout.count() - 1, arrow)
            level = "success" if index == len(breadcrumb_nodes) - 1 else "neutral"
            chip = make_status_chip(
                label,
                level=level,
                tooltip=tooltip,
                parent=self,
            )
            chip.setSizePolicy(qtw.QSizePolicy.Fixed, qtw.QSizePolicy.Fixed)
            self._layout.insertWidget(self._layout.count() - 1, chip)
        self.setVisible(bool(profile_label or context_label or breadcrumb_nodes))


class WorkflowLineageRow(qtw.QWidget):
    """One graph-like active-path row with a marker, elbow, and labels."""

    def __init__(
        self,
        entry: WorkflowLineageEntry,
        *,
        first: bool,
        last: bool,
        parent: qtw.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entry = entry
        self._first = bool(first)
        self._last = bool(last)

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(30, 3, 6, 3)
        layout.setSpacing(1)

        self._label = qtw.QLabel(entry.label, self)
        self._label.setWordWrap(True)
        self._label.setToolTip(entry.tooltip)
        if entry.is_active:
            font = self._label.font()
            font.setBold(True)
            self._label.setFont(font)
            self._label.setObjectName("SectionTitle")
        layout.addWidget(self._label)

        self._detail = qtw.QLabel(entry.detail, self)
        self._detail.setObjectName("MutedLabel")
        self._detail.setWordWrap(True)
        self._detail.setToolTip(entry.tooltip)
        self._detail.setVisible(bool(entry.detail.strip()))
        layout.addWidget(self._detail)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        palette = self.palette()
        line_color = palette.color(QtGui.QPalette.Mid)
        marker_color = palette.color(QtGui.QPalette.Link)
        if not self._entry.is_active:
            marker_color = marker_color.lighter(125)

        x = 12
        mid_y = self.height() / 2.0
        top_y = 0 if not self._first else mid_y
        bottom_y = self.height() if not self._last else mid_y

        pen = QtGui.QPen(
            marker_color if self._entry.is_active else line_color,
            1.35,
        )
        painter.setPen(pen)
        if top_y != mid_y:
            painter.drawLine(QtCore.QPointF(x, top_y), QtCore.QPointF(x, mid_y))
        if bottom_y != mid_y:
            painter.drawLine(QtCore.QPointF(x, mid_y), QtCore.QPointF(x, bottom_y))
        painter.drawLine(QtCore.QPointF(x, mid_y), QtCore.QPointF(x + 10, mid_y))

        painter.setBrush(marker_color)
        radius = 4.25 if self._entry.is_active else 3.1
        painter.drawEllipse(QtCore.QPointF(x, mid_y), radius, radius)


class WorkflowLineageRail(qtw.QFrame):
    """Compact active-path rail used to make workflow lineage visually explicit."""

    def __init__(self, parent: qtw.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SubtlePanel")
        self._density_tokens = comfortable_density_tokens()

        layout = qtw.QVBoxLayout(self)
        self._layout = layout

        self._title_label = qtw.QLabel("Active Path", self)
        self._title_label.setObjectName("SectionTitle")
        layout.addWidget(self._title_label)

        self._context_label = qtw.QLabel("", self)
        self._context_label.setObjectName("MutedLabel")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._rows_layout = qtw.QVBoxLayout()
        layout.addLayout(self._rows_layout)

        self._empty_label = qtw.QLabel("No active workflow scope", self)
        self._empty_label.setObjectName("MutedLabel")
        self._empty_label.setWordWrap(True)
        self._rows_layout.addWidget(self._empty_label)
        self._rows_layout.addStretch(1)

        self.apply_density(self._density_tokens)
        self.setVisible(False)

    def apply_density(self, tokens: DensityTokens) -> None:
        """Apply active density tokens to the rail layout."""

        self._density_tokens = tokens
        self._layout.setContentsMargins(
            tokens.panel_margin_h,
            max(5, tokens.panel_margin_v - 1),
            tokens.panel_margin_h,
            max(5, tokens.panel_margin_v - 1),
        )
        self._layout.setSpacing(max(3, tokens.panel_spacing - 3))
        self._rows_layout.setSpacing(max(2, tokens.panel_spacing - 4))

    def set_entries(
        self,
        entries: Iterable[WorkflowLineageEntry],
        *,
        context_label: str | None = None,
        empty_text: str = "No active workflow scope",
    ) -> None:
        """Replace the current lineage entries with one active-path stack."""

        for index in range(self._rows_layout.count() - 1, -1, -1):
            item = self._rows_layout.itemAt(index)
            widget = item.widget()
            if not isinstance(widget, WorkflowLineageRow):
                continue
            item = self._rows_layout.takeAt(index)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        rows = [entry for entry in entries if entry.label.strip()]
        has_context = bool(str(context_label or "").strip())
        self._context_label.setText(str(context_label or "").strip())
        self._context_label.setVisible(has_context)
        self._empty_label.setText(str(empty_text).strip())
        self._empty_label.setVisible(not rows)

        for index, entry in enumerate(rows):
            row = WorkflowLineageRow(
                entry,
                first=index == 0,
                last=index == len(rows) - 1,
                parent=self,
            )
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self.setVisible(bool(rows or has_context or self._empty_label.text().strip()))

    def entry_labels(self) -> tuple[str, ...]:
        """Return visible lineage labels for tests and diagnostics."""

        labels: list[str] = []
        for index in range(self._rows_layout.count() - 1):
            item = self._rows_layout.itemAt(index)
            widget = item.widget()
            if isinstance(widget, WorkflowLineageRow):
                labels.append(widget._entry.label)
        return tuple(labels)


def set_chip_cell(
    table: qtw.QTableWidget,
    row: int,
    column: int,
    text: str,
    *,
    level: str = "neutral",
    tooltip: str = "",
) -> None:
    """Place one status-chip widget inside a table cell."""

    chip = StatusChip(text, level=level, tooltip=tooltip, parent=table)
    chip.setAlignment(Qt.AlignCenter)
    table.setCellWidget(row, column, chip)
