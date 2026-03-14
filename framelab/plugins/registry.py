"""Generic plugin discovery, metadata, and runtime loading helpers.

Runtime action contract (optional)
----------------------------------
Page plugins may expose a ``populate_page_menu(host_window, menu)`` callable
to register page-specific runtime actions in the host ``Plugins`` menu.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Type

PAGE_IDS = ("data", "measure", "analysis")
_PAGE_PACKAGE = {
    "data": "framelab.plugins.data",
    "measure": "framelab.plugins.measure",
    "analysis": "framelab.plugins.analysis",
}
_PLUGINS_ROOT = Path(__file__).resolve().parent
_REGISTERED: dict[str, dict[str, Type[Any]]] = {
    page: {} for page in PAGE_IDS
}


@dataclass(frozen=True)
class PluginUiCapabilities:
    """Optional UI hints a plugin can expose to the host application."""

    reveal_data_columns: tuple[str, ...] = ()
    reveal_measure_columns: tuple[str, ...] = ()
    show_metadata_controls: bool = False
    metadata_group_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginManifest:
    """Lightweight plugin metadata used before runtime imports."""

    plugin_id: str
    display_name: str
    page: str
    entrypoint_module: str
    dependencies: tuple[str, ...] = ()
    description: str = ""
    manifest_path: Path = Path()


def _normalize_page(page: str) -> str:
    normalized = str(page).strip().lower()
    if normalized not in _PAGE_PACKAGE:
        supported = ", ".join(PAGE_IDS)
        raise ValueError(f"unknown plugin page '{page}', expected one of: {supported}")
    return normalized


def _normalize_dependencies(plugin_cls: Type[Any]) -> tuple[str, ...]:
    raw = getattr(plugin_cls, "dependencies", ())
    if isinstance(raw, str):
        values = [raw]
    else:
        try:
            values = list(raw)
        except Exception:
            values = []
    cleaned: list[str] = []
    for item in values:
        token = str(item).strip()
        if token:
            cleaned.append(token)
    return tuple(cleaned)


def _normalize_token_tuple(raw: object) -> tuple[str, ...]:
    """Normalize tuple-like values into stable non-empty string tuples."""
    if isinstance(raw, str):
        values = [raw]
    else:
        try:
            values = list(raw)  # type: ignore[arg-type]
        except Exception:
            values = []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return tuple(cleaned)


def _normalize_ui_capabilities(plugin_cls: Type[Any]) -> PluginUiCapabilities:
    """Normalize optional ``ui_capabilities`` declaration on plugin class."""
    raw = getattr(plugin_cls, "ui_capabilities", None)
    if isinstance(raw, PluginUiCapabilities):
        return PluginUiCapabilities(
            reveal_data_columns=_normalize_token_tuple(
                raw.reveal_data_columns,
            ),
            reveal_measure_columns=_normalize_token_tuple(
                raw.reveal_measure_columns,
            ),
            show_metadata_controls=bool(raw.show_metadata_controls),
            metadata_group_fields=_normalize_token_tuple(
                raw.metadata_group_fields,
            ),
        )
    if isinstance(raw, Mapping):
        mapping = dict(raw)
        return PluginUiCapabilities(
            reveal_data_columns=_normalize_token_tuple(
                mapping.get("reveal_data_columns", ()),
            ),
            reveal_measure_columns=_normalize_token_tuple(
                mapping.get("reveal_measure_columns", ()),
            ),
            show_metadata_controls=bool(
                mapping.get("show_metadata_controls", False),
            ),
            metadata_group_fields=_normalize_token_tuple(
                mapping.get("metadata_group_fields", ()),
            ),
        )
    return PluginUiCapabilities()


def register_page_plugin(plugin_cls: Type[Any], *, page: str) -> Type[Any]:
    """Register a plugin class under a specific workflow page."""
    normalized_page = _normalize_page(page)
    plugin_id = str(getattr(plugin_cls, "plugin_id", "")).strip()
    if not plugin_id:
        raise ValueError("plugin must define a non-empty plugin_id")
    setattr(plugin_cls, "target_page", normalized_page)
    setattr(plugin_cls, "dependencies", _normalize_dependencies(plugin_cls))
    setattr(plugin_cls, "ui_capabilities", _normalize_ui_capabilities(plugin_cls))
    _REGISTERED[normalized_page][plugin_id] = plugin_cls
    return plugin_cls


def _manifest_paths_for_page(page: str) -> list[Path]:
    """Return plugin manifest files for one page without importing plugins."""
    normalized_page = _normalize_page(page)
    page_dir = _PLUGINS_ROOT / normalized_page
    if not page_dir.is_dir():
        return []

    manifest_paths: list[Path] = []
    for path in page_dir.rglob("*"):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        if path.name == "plugin.json" or path.name.endswith(".plugin.json"):
            manifest_paths.append(path)
    return sorted(manifest_paths)


def _read_plugin_manifest(path: Path, *, page: str) -> PluginManifest:
    """Parse and validate one plugin manifest file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid plugin manifest '{path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"plugin manifest '{path}' must contain a JSON object")

    plugin_id = str(payload.get("plugin_id", "")).strip()
    if not plugin_id:
        raise ValueError(f"plugin manifest '{path}' is missing 'plugin_id'")

    display_name = str(payload.get("display_name", "")).strip()
    if not display_name:
        raise ValueError(f"plugin manifest '{path}' is missing 'display_name'")

    manifest_page = _normalize_page(str(payload.get("page", page)))
    if manifest_page != _normalize_page(page):
        raise ValueError(
            f"plugin manifest '{path}' declares page '{manifest_page}' "
            f"but is located under '{page}'",
        )

    entrypoint_module = str(payload.get("entrypoint_module", "")).strip()
    if not entrypoint_module:
        raise ValueError(
            f"plugin manifest '{path}' is missing 'entrypoint_module'",
        )

    return PluginManifest(
        plugin_id=plugin_id,
        display_name=display_name,
        page=manifest_page,
        entrypoint_module=entrypoint_module,
        dependencies=_normalize_token_tuple(payload.get("dependencies", ())),
        description=str(payload.get("description", "")).strip(),
        manifest_path=path,
    )


def _all_plugin_manifests() -> list[PluginManifest]:
    """Return validated plugin manifests for every page."""
    manifests: list[PluginManifest] = []
    for page in PAGE_IDS:
        for path in _manifest_paths_for_page(page):
            manifests.append(_read_plugin_manifest(path, page=page))
    _validate_manifests(manifests)
    return sorted(
        manifests,
        key=lambda item: (item.page, item.display_name.lower(), item.plugin_id),
    )


def _validate_manifests(manifests: Iterable[PluginManifest]) -> None:
    """Validate manifest uniqueness and dependency references."""
    manifest_list = list(manifests)
    seen: dict[str, PluginManifest] = {}
    for manifest in manifest_list:
        existing = seen.get(manifest.plugin_id)
        if existing is not None:
            raise ValueError(
                "duplicate plugin_id "
                f"'{manifest.plugin_id}' in '{existing.manifest_path}' and "
                f"'{manifest.manifest_path}'",
            )
        seen[manifest.plugin_id] = manifest

    for manifest in manifest_list:
        for dependency in manifest.dependencies:
            if dependency not in seen:
                raise ValueError(
                    f"plugin '{manifest.plugin_id}' depends on unknown plugin "
                    f"'{dependency}'",
                )


def discover_plugin_manifests(page: str | None = None) -> list[PluginManifest]:
    """Return plugin manifests without importing plugin implementation modules."""
    manifests = _all_plugin_manifests()
    if page is None:
        return manifests
    normalized_page = _normalize_page(page)
    return [manifest for manifest in manifests if manifest.page == normalized_page]


def plugin_manifest_index() -> dict[str, PluginManifest]:
    """Return plugin manifests indexed by plugin identifier."""
    return {manifest.plugin_id: manifest for manifest in _all_plugin_manifests()}


def resolve_enabled_plugin_ids(enabled_plugin_ids: Iterable[str]) -> frozenset[str]:
    """Return selected plugin ids closed over dependencies."""
    manifest_by_id = plugin_manifest_index()
    requested: list[str] = []
    seen_requested: set[str] = set()
    for value in enabled_plugin_ids:
        plugin_id = str(value).strip()
        if not plugin_id or plugin_id in seen_requested:
            continue
        seen_requested.add(plugin_id)
        requested.append(plugin_id)

    resolved: set[str] = set()

    def _visit(plugin_id: str) -> None:
        manifest = manifest_by_id.get(plugin_id)
        if manifest is None or plugin_id in resolved:
            return
        for dependency in manifest.dependencies:
            _visit(dependency)
        resolved.add(plugin_id)

    for plugin_id in requested:
        _visit(plugin_id)
    return frozenset(resolved)


def enabled_plugin_manifests(
    enabled_plugin_ids: Iterable[str],
) -> dict[str, list[PluginManifest]]:
    """Return enabled plugin manifests grouped by workflow page."""
    enabled_ids = resolve_enabled_plugin_ids(enabled_plugin_ids)
    grouped: dict[str, list[PluginManifest]] = {page: [] for page in PAGE_IDS}
    for manifest in _all_plugin_manifests():
        if manifest.plugin_id in enabled_ids:
            grouped[manifest.page].append(manifest)
    for page in PAGE_IDS:
        grouped[page].sort(key=lambda item: item.display_name.lower())
    return grouped


def _clear_registered_plugins(page: str | None = None) -> None:
    """Reset runtime plugin-class registrations for a fresh load pass."""
    if page is None:
        for page_id in PAGE_IDS:
            _REGISTERED[page_id].clear()
        return
    _REGISTERED[_normalize_page(page)].clear()


def _import_plugin_entrypoint(module_name: str) -> None:
    """Import or reload one plugin entrypoint so it can self-register."""
    importlib.invalidate_caches()
    existing = sys.modules.get(module_name)
    if existing is None:
        importlib.import_module(module_name)
        return
    importlib.reload(existing)


def _registered_classes_for_manifests(
    page: str,
    manifests: Iterable[PluginManifest],
) -> list[Type[Any]]:
    """Import manifests for one page and return their registered classes."""
    normalized_page = _normalize_page(page)
    manifest_list = list(manifests)
    _clear_registered_plugins(normalized_page)

    for manifest in manifest_list:
        _import_plugin_entrypoint(manifest.entrypoint_module)

    registered = _REGISTERED[normalized_page]
    manifest_order = {
        manifest.plugin_id: index for index, manifest in enumerate(manifest_list)
    }
    for manifest in manifest_list:
        if manifest.plugin_id not in registered:
            raise ValueError(
                f"plugin '{manifest.plugin_id}' did not register after "
                f"importing '{manifest.entrypoint_module}'",
            )
    return sorted(
        (
            registered[plugin_id]
            for plugin_id in manifest_order
            if plugin_id in registered
        ),
        key=lambda cls: manifest_order.get(
            str(getattr(cls, "plugin_id", "")),
            10_000,
        ),
    )


def load_enabled_plugins(
    enabled_plugin_ids: Iterable[str],
) -> dict[str, list[Type[Any]]]:
    """Import only enabled plugin entrypoints and return registered classes."""
    manifests_by_page = enabled_plugin_manifests(enabled_plugin_ids)
    classes_by_page: dict[str, list[Type[Any]]] = {page: [] for page in PAGE_IDS}
    for page in PAGE_IDS:
        classes_by_page[page] = _registered_classes_for_manifests(
            page,
            manifests_by_page[page],
        )
    return classes_by_page


def load_enabled_page_plugins(
    page: str,
    enabled_plugin_ids: Iterable[str],
) -> list[Type[Any]]:
    """Import and return enabled plugins for one workflow page."""
    normalized_page = _normalize_page(page)
    manifests = enabled_plugin_manifests(enabled_plugin_ids)[normalized_page]
    return _registered_classes_for_manifests(normalized_page, manifests)


def load_page_plugins(
    page: str,
    enabled_plugin_ids: Iterable[str] | None = None,
) -> list[Type[Any]]:
    """Return plugins for one page, optionally limited to enabled ids."""
    if enabled_plugin_ids is None:
        enabled_plugin_ids = plugin_manifest_index()
    return load_enabled_page_plugins(page, enabled_plugin_ids)
