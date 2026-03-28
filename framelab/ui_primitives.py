"""Shared lightweight UI primitives used across workflow pages and dialogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6 import QtWidgets as qtw
from PySide6.QtCore import Qt

from .ui_density import DensityTokens, comfortable_density_tokens


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
        self._density_tokens = comfortable_density_tokens()
        self._subtitle_requested_visible = bool(subtitle.strip())
        self._compact_chip_mode = False
        layout = qtw.QVBoxLayout(self)
        self._layout = layout
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.title_label = qtw.QLabel(title, self)
        self.title_label.setObjectName("PageHeaderTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.subtitle_label = qtw.QLabel(subtitle, self)
        self.subtitle_label.setObjectName("PageHeaderSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle.strip()))
        layout.addWidget(self.subtitle_label)

        chip_row = qtw.QWidget(self)
        chip_row.setObjectName("PageHeaderChips")
        chip_layout = qtw.QHBoxLayout(chip_row)
        chip_layout.setContentsMargins(0, 0, 0, 0)
        chip_layout.setSpacing(8)
        chip_layout.addStretch(1)
        self._chip_row = chip_row
        self._chip_layout = chip_layout
        layout.addWidget(chip_row)
        chip_row.setVisible(False)
        self.apply_density(self._density_tokens)

    def set_title(self, title: str) -> None:
        """Update header title."""
        self.title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        """Update header subtitle and visibility."""
        self.subtitle_label.setText(subtitle)
        self._subtitle_requested_visible = bool(subtitle.strip())
        self._sync_subtitle_visibility()

    def set_subtitle_visible(self, visible: bool) -> None:
        """Show or hide the subtitle without clearing its text."""

        self._subtitle_requested_visible = bool(visible)
        self._sync_subtitle_visibility()

    def set_compact_chip_mode(self, enabled: bool) -> None:
        """Toggle tighter spacing for the chip row."""

        self._compact_chip_mode = bool(enabled)
        self._sync_chip_spacing()

    def apply_density(self, tokens: DensityTokens) -> None:
        """Apply density spacing tokens to the header layout."""

        self._density_tokens = tokens
        self._layout.setContentsMargins(
            tokens.header_margin_h,
            tokens.header_margin_v,
            tokens.header_margin_h,
            tokens.header_margin_v,
        )
        self._layout.setSpacing(tokens.header_spacing)
        self._sync_chip_spacing()
        self._sync_subtitle_visibility()

    def set_chips(self, specs: Iterable[ChipSpec]) -> None:
        """Replace header chips with the provided specs."""
        while self._chip_layout.count() > 1:
            item = self._chip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
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
        self._sync_chip_spacing()

    def _sync_subtitle_visibility(self) -> None:
        self.subtitle_label.setVisible(
            bool(self._subtitle_requested_visible)
            and bool(self.subtitle_label.text().strip()),
        )

    def _sync_chip_spacing(self) -> None:
        spacing = self._density_tokens.chip_spacing
        if self._compact_chip_mode:
            spacing = max(4, spacing - 2)
        self._chip_layout.setSpacing(spacing)


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
        self._density_tokens = comfortable_density_tokens()
        self._items: list[SummaryItem] = []
        self._collapsed = False
        self._auto_hide_when_empty = True
        self._layout = qtw.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.apply_density(self._density_tokens)

    def apply_density(self, tokens: DensityTokens) -> None:
        """Apply density spacing tokens and rebuild cards if needed."""

        self._density_tokens = tokens
        self._layout.setSpacing(tokens.panel_spacing)
        if self._items:
            self._rebuild_items()

    def set_collapsed(self, collapsed: bool) -> None:
        """Show or hide the strip while retaining its content."""

        self._collapsed = bool(collapsed)
        self._sync_visibility()

    def is_collapsed(self) -> bool:
        """Return whether the strip is currently collapsed."""

        return self._collapsed

    def set_items(
        self,
        items: Iterable[SummaryItem],
        *,
        auto_hide_when_empty: bool = True,
    ) -> None:
        """Replace strip contents with the provided summary cells."""
        self._items = list(items)
        self._auto_hide_when_empty = bool(auto_hide_when_empty)
        self._rebuild_items()

    def _rebuild_items(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

        visible_count = 0
        for summary in self._items:
            card = qtw.QFrame(self)
            card.setObjectName("SummaryCard")
            card.setProperty("statusLevel", str(summary.level or "neutral"))
            card.setSizePolicy(
                qtw.QSizePolicy.Expanding,
                qtw.QSizePolicy.Fixed,
            )
            card_layout = qtw.QVBoxLayout(card)
            card_layout.setContentsMargins(
                self._density_tokens.summary_card_margin_h,
                self._density_tokens.summary_card_margin_v,
                self._density_tokens.summary_card_margin_h,
                self._density_tokens.summary_card_margin_v,
            )
            card_layout.setSpacing(self._density_tokens.summary_card_spacing)

            value = qtw.QLabel(summary.value, card)
            value.setObjectName("SummaryValue")
            value.setTextFormat(Qt.PlainText)
            value.setWordWrap(False)
            value.setSizePolicy(
                qtw.QSizePolicy.Ignored,
                qtw.QSizePolicy.Preferred,
            )
            card_layout.addWidget(value)

            label = qtw.QLabel(summary.label, card)
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
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        should_show = not self._collapsed
        if self._auto_hide_when_empty:
            should_show = should_show and bool(self._items)
        self.setVisible(should_show)


def build_summary_strip(
    items: Iterable[SummaryItem] = (),
    *,
    parent: qtw.QWidget | None = None,
) -> SummaryStrip:
    """Return a summary strip pre-populated with the given items."""
    strip = SummaryStrip(parent)
    strip.set_items(items)
    return strip
