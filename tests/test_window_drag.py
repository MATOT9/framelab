"""Tests for secondary-window flags and screen-aware geometry helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets as qtw
from PySide6.QtCore import Qt

import framelab.window_drag as window_drag_module
from framelab.plugins.data.acquisition_datacard_wizard import (
    AcquisitionDatacardWizardDialog,
)
from framelab.window_drag import (
    _current_frame_margins,
    apply_secondary_window_geometry,
    configure_secondary_window,
    place_secondary_window,
)


pytestmark = [pytest.mark.ui, pytest.mark.core]


def test_configure_secondary_window_uses_dialog_flags_by_default(qapp) -> None:
    dialog = qtw.QDialog()
    configure_secondary_window(dialog)

    assert (dialog.windowFlags() & Qt.WindowType_Mask) == Qt.Dialog

    configure_secondary_window(dialog, standalone=True)
    assert (dialog.windowFlags() & Qt.WindowType_Mask) == Qt.Window


def test_apply_secondary_window_geometry_clamps_to_available_rect(
    monkeypatch,
    qapp,
) -> None:
    dialog = qtw.QDialog()
    dialog.setMinimumSize(980, 640)
    available = QtCore.QRect(100, 120, 940, 620)
    margins = QtCore.QMargins(8, 31, 8, 8)

    monkeypatch.setattr(
        window_drag_module,
        "secondary_window_available_geometry",
        lambda window, *, host_window=None: available,
    )
    monkeypatch.setattr(
        window_drag_module,
        "_current_frame_margins",
        lambda window: margins,
    )

    apply_secondary_window_geometry(dialog, preferred_size=(1120, 760))

    assert dialog.minimumWidth() <= available.width() - margins.left() - margins.right()
    assert dialog.minimumHeight() <= available.height() - margins.top() - margins.bottom()
    assert dialog.width() <= available.width() - margins.left() - margins.right()
    assert dialog.height() <= available.height() - margins.top() - margins.bottom()


def test_place_secondary_window_uses_top_level_host_for_child_widgets(
    monkeypatch,
    qapp,
) -> None:
    main_window = qtw.QMainWindow()
    main_window.resize(1200, 800)
    main_window.move(420, 180)
    central = qtw.QWidget()
    central.setObjectName("MainWindowCentral")
    main_window.setCentralWidget(central)
    main_window.show()
    qapp.processEvents()

    dialog = qtw.QDialog(main_window)
    dialog.resize(400, 300)
    available = QtCore.QRect(100, 120, 1400, 900)
    margins = QtCore.QMargins()

    monkeypatch.setattr(
        window_drag_module,
        "secondary_window_available_geometry",
        lambda window, *, host_window=None: available,
    )
    monkeypatch.setattr(
        window_drag_module,
        "_current_frame_margins",
        lambda window: margins,
    )

    try:
        place_secondary_window(dialog, host_window=central)
        qapp.processEvents()

        expected_x = main_window.frameGeometry().center().x() - dialog.width() // 2
        expected_y = main_window.frameGeometry().center().y() - dialog.height() // 2
        assert abs(dialog.x() - expected_x) <= 1
        assert abs(dialog.y() - expected_y) <= 1
    finally:
        dialog.close()
        dialog.deleteLater()
        main_window.close()
        main_window.deleteLater()
        qapp.processEvents()


def test_acquisition_wizard_uses_host_parent_and_clamped_geometry(
    tmp_path: Path,
    qapp,
    monkeypatch,
) -> None:
    host = qtw.QWidget()
    host.resize(1200, 800)
    host.move(420, 180)
    host.show()
    qapp.processEvents()

    acquisition_root = tmp_path / "acquisition"
    acquisition_root.mkdir(parents=True, exist_ok=True)
    available = QtCore.QRect(100, 120, 1040, 700)
    margins = QtCore.QMargins(8, 31, 8, 8)

    monkeypatch.setattr(
        window_drag_module,
        "secondary_window_available_geometry",
        lambda window, *, host_window=None: available,
    )
    monkeypatch.setattr(
        window_drag_module,
        "_current_frame_margins",
        lambda window: margins,
    )

    dialog = AcquisitionDatacardWizardDialog(host, str(acquisition_root))
    qapp.processEvents()

    try:
        assert dialog.parentWidget() is host
        assert dialog.width() <= available.width() - margins.left() - margins.right()
        assert dialog.height() <= available.height() - margins.top() - margins.bottom()

        dialog.place_near_host(host)
        qapp.processEvents()

        frame_left = dialog.x() - margins.left()
        frame_top = dialog.y() - margins.top()
        frame_right = frame_left + dialog.width() + margins.left() + margins.right()
        frame_bottom = frame_top + dialog.height() + margins.top() + margins.bottom()
        assert frame_left >= available.left()
        assert frame_top >= available.top()
        assert frame_right <= available.right() + 1
        assert frame_bottom <= available.bottom() + 1
    finally:
        dialog.close()
        dialog.deleteLater()
        host.close()
        host.deleteLater()
        qapp.processEvents()


def test_current_frame_margins_does_not_force_native_window_creation(qapp) -> None:
    class _DialogWithoutWinId(qtw.QDialog):
        def winId(self):  # type: ignore[override]
            raise AssertionError("winId should not be called for pre-show geometry")

    dialog = _DialogWithoutWinId()

    margins = _current_frame_margins(dialog)

    assert margins == QtCore.QMargins()
    dialog.deleteLater()
