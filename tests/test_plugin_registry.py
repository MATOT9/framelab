"""Tests for plugin manifest discovery."""

from __future__ import annotations

import pytest

from framelab.plugins import discover_plugin_manifests, load_enabled_page_plugins
from framelab.plugins.selection import (
    load_selected_plugin_ids,
    save_selected_plugin_ids,
)


pytestmark = [pytest.mark.fast, pytest.mark.core]


def test_background_correction_manifest_is_discovered() -> None:
    manifests = {
        manifest.plugin_id: manifest
        for manifest in discover_plugin_manifests("measure")
    }
    assert "background_correction" in manifests
    manifest = manifests["background_correction"]
    assert manifest.display_name == "Background Correction"
    assert manifest.page == "measure"


def test_session_manager_manifest_is_marked_legacy() -> None:
    manifests = {
        manifest.plugin_id: manifest
        for manifest in discover_plugin_manifests("data")
    }
    assert "ebus_config_tools" not in manifests
    assert "session_manager" in manifests
    manifest = manifests["session_manager"]
    assert manifest.display_name == "Session Manager (Legacy)"


def test_event_signature_manifest_is_discovered() -> None:
    manifests = {
        manifest.plugin_id: manifest
        for manifest in discover_plugin_manifests("analysis")
    }
    assert "event_signature" in manifests
    manifest = manifests["event_signature"]
    assert manifest.display_name == "Event Signature"
    assert manifest.page == "analysis"

    plugin_classes = load_enabled_page_plugins("analysis", ("event_signature",))
    assert [plugin.plugin_id for plugin in plugin_classes] == ["event_signature"]


def test_stale_ebus_plugin_selection_id_is_ignored() -> None:
    manifests = discover_plugin_manifests()

    save_selected_plugin_ids(("ebus_config_tools", "session_manager"))
    selected = load_selected_plugin_ids(manifests)

    assert "ebus_config_tools" not in selected
    assert "session_manager" in selected
    assert "acquisition_datacard_wizard" in selected
