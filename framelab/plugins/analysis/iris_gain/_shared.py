"""Shared dataclasses, widgets, and optional plotting backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from PySide6 import QtGui, QtWidgets as qtw
from PySide6.QtCore import Qt

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    MATPLOTLIB_AVAILABLE = True
except Exception:
    FigureCanvasQTAgg = None  # type: ignore[assignment]
    Figure = None  # type: ignore[assignment]
    MATPLOTLIB_AVAILABLE = False


@dataclass
class _CurveSeries:
    """Single plotted curve."""

    curve_id: int
    label: str
    x_values: list[float]
    y_values: list[float]
    std_values: list[float]
    sem_values: list[float]
    error_values: list[float]
    point_counts: list[int]


@dataclass
class _FitSeries:
    """Linear regression fit or overlay series for plotted data."""

    label: str
    slope: float
    intercept: float
    r2: float
    x_values: np.ndarray
    y_values: np.ndarray
    std_values: Optional[np.ndarray] = None
    sem_values: Optional[np.ndarray] = None
    kind: str = "linear_fit"


@dataclass
class _FitHoverItem:
    """Hover payload for plotted overlay series."""

    label: str
    kind: str
    x_values: np.ndarray
    y_values: np.ndarray
    std_values: Optional[np.ndarray] = None
    sem_values: Optional[np.ndarray] = None


class _SortableTableItem(qtw.QTableWidgetItem):
    """Table item supporting numeric sort via user-role payload."""

    def __init__(
        self,
        text: str,
        sort_value: object,
    ) -> None:
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, qtw.QTableWidgetItem):
            return super().__lt__(other)
        left = getattr(self, "sort_value", None)
        right = getattr(other, "sort_value", None)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            left_value = float(left)
            right_value = float(right)
            left_finite = np.isfinite(left_value)
            right_finite = np.isfinite(right_value)
            if left_finite and right_finite:
                return left_value < right_value
            if left_finite and not right_finite:
                return True
            if not left_finite and right_finite:
                return False
            return False
        if left is not None and right is not None:
            return str(left).lower() < str(right).lower()
        return super().__lt__(other)


class _ResultTableWidget(qtw.QTableWidget):
    """Plugin result table with spreadsheet-like copy behavior."""

    def __init__(self, parent: Optional[qtw.QWidget] = None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # type: ignore[override]
        """Handle Ctrl+C copy shortcut."""
        if event.matches(QtGui.QKeySequence.Copy):
            self.copy_selection_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection_to_clipboard(self) -> None:
        """Copy selected table cells to clipboard as tab-separated text."""
        indexes = self.selectedIndexes()
        if not indexes:
            return
        ordered = sorted(indexes, key=lambda idx: (idx.row(), idx.column()))
        rows = sorted({idx.row() for idx in ordered})
        cols = sorted({idx.column() for idx in ordered})
        row_pos = {row: i for i, row in enumerate(rows)}
        col_pos = {col: i for i, col in enumerate(cols)}
        grid = [["" for _ in cols] for _ in rows]
        for idx in ordered:
            item = self.item(idx.row(), idx.column())
            value = item.text() if item is not None else ""
            grid[row_pos[idx.row()]][col_pos[idx.column()]] = value
        text = "\n".join("\t".join(row) for row in grid)
        qtw.QApplication.clipboard().setText(text)

    def _show_context_menu(self, pos) -> None:
        menu = qtw.QMenu(self)
        copy_action = menu.addAction("Copy")
        copy_action.setEnabled(bool(self.selectedIndexes()))
        triggered = menu.exec(self.viewport().mapToGlobal(pos))
        if triggered == copy_action:
            self.copy_selection_to_clipboard()
