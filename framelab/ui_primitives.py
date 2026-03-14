"""Shared lightweight UI primitives used across workflow pages and dialogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt


@dataclass(slots=True)
class ChipSpec:
    """Display payload for one status chip."""

    text: str
    level: str = "neutral"
    tooltip: str = ""


@dataclass(slots=True)
class SummaryItem:
    """Display payload for one summary-strip cell."""

    label: str
    value: str
    level: str = "neutral"
    tooltip: str = ""


class StatusChip(qtw.QLabel):
    """Compact status token styled through object name and level property."""

    def __init__(
        self,
        text: str = "",
        *,
        level: str = "neutral",
        tooltip: str = "",
        parent: qtw.QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setObjectName("StatusChip")
        self.setAlignment(Qt.AlignCenter)
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(False)
        self.setSizePolicy(
            qtw.QSizePolicy.Fixed,
            qtw.QSizePolicy.Fixed,
        )
        self.set_status(text, level=level, tooltip=tooltip)

    def set_status(
        self,
        text: str,
        *,
        level: str = "neutral",
        tooltip: str = "",
    ) -> None:
        """Update displayed text and semantic level."""
        self.setText(text)
        self.setProperty("statusLevel", str(level or "neutral"))
        clean_tooltip = " ".join(tooltip.split())
        self.setToolTip(clean_tooltip)
        self.setStatusTip(clean_tooltip)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()


def make_status_chip(
    text: str,
    *,
    level: str = "neutral",
    tooltip: str = "",
    parent: qtw.QWidget | None = None,
) -> StatusChip:
    """Return a styled status-chip label."""
    return StatusChip(text, level=level, tooltip=tooltip, parent=parent)


class PageHeader(qtw.QFrame):
    """Reusable page/dialog header with title, subtitle, and status chips."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: qtw.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.title_label = qtw.QLabel(title)
        self.title_label.setObjectName("PageHeaderTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.subtitle_label = qtw.QLabel(subtitle)
        self.subtitle_label.setObjectName("PageHeaderSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle.strip()))
        layout.addWidget(self.subtitle_label)

        chip_row = qtw.QWidget()
        chip_row.setObjectName("PageHeaderChips")
        chip_layout = qtw.QHBoxLayout(chip_row)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(8)
        chip_layout.addStretch(1)
        self._chip_row = chip_row
        self._chip_layout = chip_layout
        layout.addWidget(chip_row)
        chip_row.setVisible(False)

    def set_title(self, title: str) -> None:
        """Update header title."""
        self.title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        """Update header subtitle and visibility."""
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.setVisible(bool(subtitle.strip()))

    def set_chips(self, specs: Iterable[ChipSpec]) -> None:
        """Replace header chips with the provided specs."""
        while self._chip_layout.count() > 1:
            item = self._chip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for spec in specs:
            chip = make_status_chip(
                spec.text,
                level=spec.level,
                tooltip=spec.tooltip,
                parent=self._chip_row,
            )
            self._chip_layout.insertWidget(
                self._chip_layout.count() - 1,
                chip,
            )
        self._chip_row.setVisible(self._chip_layout.count() > 1)


def build_page_header(
    title: str,
    subtitle: str = "",
    *,
    chips: Iterable[ChipSpec] = (),
    parent: qtw.QWidget | None = None,
) -> PageHeader:
    """Return a page header pre-populated with the given text and chips."""
    header = PageHeader(title, subtitle, parent)
    header.set_chips(chips)
    return header


class SummaryStrip(qtw.QFrame):
    """Reusable strip of compact summary cards."""

    def __init__(self, parent: qtw.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SummaryStrip")
        self._layout = qtw.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

    def set_items(self, items: Iterable[SummaryItem]) -> None:
        """Replace strip contents with the provided summary cells."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        visible_count = 0
        for summary in items:
            card = qtw.QFrame(self)
            card.setObjectName("SummaryCard")
            card.setProperty("statusLevel", str(summary.level or "neutral"))
            card.setSizePolicy(
                qtw.QSizePolicy.Expanding,
                qtw.QSizePolicy.Fixed,
            )
            card_layout = qtw.QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(4)

            value = qtw.QLabel(summary.value)
            value.setObjectName("SummaryValue")
            value.setTextFormat(Qt.PlainText)
            value.setWordWrap(False)
            value.setSizePolicy(
                qtw.QSizePolicy.Ignored,
                qtw.QSizePolicy.Preferred,
            )
            card_layout.addWidget(value)

            label = qtw.QLabel(summary.label)
            label.setObjectName("SummaryLabel")
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(False)
            label.setSizePolicy(
                qtw.QSizePolicy.Ignored,
                qtw.QSizePolicy.Preferred,
            )
            card_layout.addWidget(label)

            clean_tooltip = " ".join(summary.tooltip.split())
            if clean_tooltip:
                card.setToolTip(clean_tooltip)
                card.setStatusTip(clean_tooltip)
            else:
                card.setToolTip(f"{summary.label}: {summary.value}")
                card.setStatusTip(f"{summary.label}: {summary.value}")
            self._layout.addWidget(card, 1)
            visible_count += 1
        self.setVisible(visible_count > 0)


def build_summary_strip(
    items: Iterable[SummaryItem] = (),
    *,
    parent: qtw.QWidget | None = None,
) -> SummaryStrip:
    """Return a summary strip pre-populated with the given items."""
    strip = SummaryStrip(parent)
    strip.set_items(items)
    return strip
