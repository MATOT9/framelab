"""Tests for the preferences dialog live-preview behavior."""

from __future__ import annotations

import pytest

from framelab.preferences_dialog import PreferencesDialog
from framelab.ui_settings import DensityMode, UiPreferences, UiStateSnapshot


pytestmark = [pytest.mark.ui, pytest.mark.core]


@pytest.fixture
def dialog_factory(qapp):
    dialogs: list[PreferencesDialog] = []

    def _factory(snapshot: UiStateSnapshot) -> PreferencesDialog:
        dialog = PreferencesDialog(snapshot)
        dialogs.append(dialog)
        return dialog

    yield _factory

    for dialog in reversed(dialogs):
        try:
            dialog.close()
        except Exception:
            pass
        dialog.deleteLater()
    qapp.processEvents()


def test_current_preferences_reflect_initial_snapshot(dialog_factory) -> None:
    prefs = UiPreferences(
        theme_mode="light",
        density_mode=DensityMode.COMPACT,
        show_page_subtitles=False,
        show_image_preview=False,
        show_histogram_preview=True,
        restore_panel_states=False,
        restore_last_tab=False,
        collapse_analysis_plugin_controls_by_default=False,
        collapse_data_advanced_row_by_default=False,
        collapse_summary_strips_by_default=True,
        scan_worker_count_override=6,
        use_mmap_for_raw=False,
        enable_raw_simd=False,
    )
    dialog = dialog_factory(UiStateSnapshot(preferences=prefs))

    assert dialog.current_preferences() == prefs


def test_scan_worker_auto_detect_round_trips_as_none(dialog_factory) -> None:
    dialog = dialog_factory(UiStateSnapshot(preferences=UiPreferences()))

    dialog._scan_worker_count_spin.setValue(0)

    assert dialog.current_preferences().scan_worker_count_override is None


def test_reject_emits_revert_after_live_preview_change(
    dialog_factory,
    process_events,
) -> None:
    initial = UiPreferences(theme_mode="dark")
    dialog = dialog_factory(UiStateSnapshot(preferences=initial))
    seen: list[UiPreferences] = []
    dialog.preferences_changed.connect(lambda prefs: seen.append(prefs))

    dialog._theme_combo.setCurrentIndex(dialog._theme_combo.findData("light"))
    process_events()
    dialog.reject()
    process_events()

    assert len(seen) >= 2
    assert seen[0].theme_mode == "light"
    assert seen[-1].theme_mode == "dark"
