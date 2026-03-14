"""Tests for plugin manifest discovery."""

from __future__ import annotations

import pytest

from framelab.plugins import discover_plugin_manifests


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
