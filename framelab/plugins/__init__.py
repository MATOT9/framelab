"""Shared plugin registry utilities by workflow page."""

from .registry import (
    PAGE_IDS,
    PluginManifest,
    PluginUiCapabilities,
    discover_plugin_manifests,
    enabled_plugin_manifests,
    load_enabled_page_plugins,
    load_enabled_plugins,
    load_page_plugins,
    plugin_manifest_index,
    register_page_plugin,
    resolve_enabled_plugin_ids,
)

__all__ = [
    "PAGE_IDS",
    "PluginManifest",
    "PluginUiCapabilities",
    "discover_plugin_manifests",
    "enabled_plugin_manifests",
    "load_enabled_page_plugins",
    "load_enabled_plugins",
    "load_page_plugins",
    "plugin_manifest_index",
    "register_page_plugin",
    "resolve_enabled_plugin_ids",
]
