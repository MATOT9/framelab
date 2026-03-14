"""Tests for density-aware shared UI primitives."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets as qtw

from framelab.ui_density import compact_density_tokens
from framelab.ui_primitives import PageHeader, SummaryItem, SummaryStrip


_previous_qt_message_handler = None


def _filtered_qt_message_handler(message_type, context, message) -> None:
    """Ignore known headless-plugin size-hint noise during offscreen tests."""

    if "This plugin does not support propagateSizeHints()" in str(message):
        return
    if _previous_qt_message_handler is not None:
        _previous_qt_message_handler(message_type, context, message)


class UiPrimitivesDensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        global _previous_qt_message_handler
        cls._app = qtw.QApplication.instance() or qtw.QApplication([])
        _previous_qt_message_handler = QtCore.qInstallMessageHandler(
            _filtered_qt_message_handler,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        global _previous_qt_message_handler
        QtCore.qInstallMessageHandler(_previous_qt_message_handler)
        _previous_qt_message_handler = None

    def test_page_header_applies_density_and_subtitle_visibility(self) -> None:
        header = PageHeader("Title", "Subtitle")
        self.addCleanup(header.deleteLater)

        header.apply_density(compact_density_tokens())
        layout = header.layout()

        self.assertEqual(layout.contentsMargins().left(), 12)
        self.assertEqual(layout.contentsMargins().top(), 10)
        self.assertEqual(layout.spacing(), 6)

        header.set_subtitle_visible(False)
        self.assertTrue(header.subtitle_label.isHidden())
        header.set_subtitle_visible(True)
        self.assertFalse(header.subtitle_label.isHidden())

    def test_summary_strip_rebuilds_cards_with_density_tokens(self) -> None:
        strip = SummaryStrip()
        self.addCleanup(strip.deleteLater)
        strip.set_items([SummaryItem("Images", "4"), SummaryItem("Mode", "ROI")])
        strip.apply_density(compact_density_tokens())

        card = strip.findChild(qtw.QFrame, "SummaryCard")
        self.assertIsNotNone(card)
        assert card is not None
        layout = card.layout()
        self.assertEqual(layout.contentsMargins().left(), 8)
        self.assertEqual(layout.contentsMargins().top(), 6)
        self.assertEqual(layout.spacing(), 3)

        strip.set_collapsed(True)
        self.assertTrue(strip.isHidden())
        strip.set_collapsed(False)
        self.assertFalse(strip.isHidden())


if __name__ == "__main__":
    unittest.main()
