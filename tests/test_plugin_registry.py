"""Tests for plugin manifest discovery."""

from __future__ import annotations

import unittest

from framelab.plugins import discover_plugin_manifests


class PluginRegistryTests(unittest.TestCase):
    def test_background_correction_manifest_is_discovered(self) -> None:
        manifests = {
            manifest.plugin_id: manifest
            for manifest in discover_plugin_manifests("measure")
        }
        self.assertIn("background_correction", manifests)
        manifest = manifests["background_correction"]
        self.assertEqual(manifest.display_name, "Background Correction")
        self.assertEqual(manifest.page, "measure")


if __name__ == "__main__":
    unittest.main()
