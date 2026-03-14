"""Tests for density-aware shared UI primitives."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6 import QtCore, QtWidgets as qtw

from framelab.ui_density import compact_density_tokens
from framelab.ui_primitives import PageHeader, SummaryItem, SummaryStrip


pytestmark = [pytest.mark.ui, pytest.mark.core]


@pytest.fixture
def filtered_qt_message_handler(qapp) -> Iterator[None]:
    """Ignore known headless-plugin size-hint noise during offscreen tests."""

    previous_handler = None

    def _filtered_handler(message_type, context, message) -> None:
        if "This plugin does not support propagateSizeHints()" in str(message):
            return
        if previous_handler is not None:
            previous_handler(message_type, context, message)

    previous_handler = QtCore.qInstallMessageHandler(_filtered_handler)
    try:
        yield
    finally:
        QtCore.qInstallMessageHandler(previous_handler)


def test_page_header_applies_density_and_subtitle_visibility(
    qapp,
    filtered_qt_message_handler,
) -> None:
    header = PageHeader("Title", "Subtitle")

    header.apply_density(compact_density_tokens())
    layout = header.layout()

    assert layout.contentsMargins().left() == 12
    assert layout.contentsMargins().top() == 10
    assert layout.spacing() == 6

    header.set_subtitle_visible(False)
    assert header.subtitle_label.isHidden()
    header.set_subtitle_visible(True)
    assert not header.subtitle_label.isHidden()

    header.deleteLater()


def test_summary_strip_rebuilds_cards_with_density_tokens(
    qapp,
    filtered_qt_message_handler,
) -> None:
    strip = SummaryStrip()
    strip.set_items([SummaryItem("Images", "4"), SummaryItem("Mode", "ROI")])
    strip.apply_density(compact_density_tokens())

    card = strip.findChild(qtw.QFrame, "SummaryCard")
    assert card is not None
    layout = card.layout()
    assert layout.contentsMargins().left() == 8
    assert layout.contentsMargins().top() == 6
    assert layout.spacing() == 3

    strip.set_collapsed(True)
    assert strip.isHidden()
    strip.set_collapsed(False)
    assert not strip.isHidden()

    strip.deleteLater()
