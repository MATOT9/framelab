"""Tests for density-aware shared UI primitives."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6 import QtCore, QtWidgets as qtw

from framelab.ui_density import compact_density_tokens
from framelab.ui_primitives import ChipSpec, PageHeader, SummaryItem, SummaryStrip
from framelab.workflow_widgets import WorkflowBreadcrumbBar, WorkflowLineageEntry, WorkflowLineageRail


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


class _TransientWindowRecorder(QtCore.QObject):
    def __init__(self) -> None:
        super().__init__()
        self.windowed_children: list[tuple[str, str]] = []
        self._tracked_object_names = {
            "MutedLabel",
            "PageHeaderSubtitle",
            "StatusChip",
            "SummaryCard",
            "SummaryLabel",
            "SummaryValue",
            "SectionTitle",
        }

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QtCore.QEvent.Show
            and isinstance(watched, qtw.QWidget)
            and watched.isWindow()
            and watched.objectName() in self._tracked_object_names
        ):
            self.windowed_children.append(
                (type(watched).__name__, watched.objectName()),
            )
        return False


def test_rebuilding_visible_ui_primitives_does_not_promote_children_to_windows(
    qapp,
    filtered_qt_message_handler,
    process_events,
) -> None:
    container = qtw.QWidget()
    layout = qtw.QVBoxLayout(container)
    header = PageHeader("Title", "Subtitle", parent=container)
    strip = SummaryStrip(container)
    breadcrumb = WorkflowBreadcrumbBar(container)
    rail = WorkflowLineageRail(container)
    layout.addWidget(header)
    layout.addWidget(strip)
    layout.addWidget(breadcrumb)
    layout.addWidget(rail)
    container.resize(720, 480)

    recorder = _TransientWindowRecorder()
    qapp.installEventFilter(recorder)
    try:
        container.show()
        process_events()
        recorder.windowed_children.clear()

        header.set_chips([ChipSpec("Loaded", level="success")])
        process_events()
        header.set_chips([ChipSpec("Ready", level="info")])

        strip.set_items([SummaryItem("Images", "4"), SummaryItem("Mode", "ROI")])
        process_events()
        strip.set_items([SummaryItem("Images", "8"), SummaryItem("Mode", "Full")])

        breadcrumb.set_breadcrumb(
            profile_label="Calibration",
            context_label="Workspace",
            nodes=(("camera-a", "camera-a"), ("session-01", "session-01")),
        )
        process_events()
        breadcrumb.set_breadcrumb(
            profile_label="Calibration",
            context_label="Workspace",
            nodes=(("camera-a", "camera-a"), ("session-02", "session-02")),
        )

        rail.set_entries(
            [
                WorkflowLineageEntry("camera-a"),
                WorkflowLineageEntry("session-01", is_active=True),
            ],
            context_label="Workspace",
        )
        process_events()
        rail.set_entries(
            [
                WorkflowLineageEntry("camera-a"),
                WorkflowLineageEntry("session-02", is_active=True),
            ],
            context_label="Workspace",
        )
        process_events()

        assert recorder.windowed_children == []
    finally:
        qapp.removeEventFilter(recorder)
        container.close()
        container.deleteLater()
        process_events()
