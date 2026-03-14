"""Startup selector and local persistence for plugin enablement."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from PySide6 import QtCore
from PySide6 import QtWidgets as qtw

from ..payload_utils import read_json_dict, write_json_dict
from ..scan_settings import app_config_path
from .registry import (
    PAGE_IDS,
    PluginManifest,
    discover_plugin_manifests,
)
from ..ui_primitives import (
    ChipSpec,
    SummaryItem,
    build_page_header,
    build_summary_strip,
    make_status_chip,
)

_SELECTION_CONFIG_FILE = "plugin_selection.json"
_SELECTION_SCHEMA_VERSION = "1.0"
_PAGE_TITLES = {
    "data": "Data",
    "measure": "Measure",
    "analysis": "Analyze",
}


def plugin_selection_config_path() -> Path:
    """Return the local plugin-selection config path."""
    return app_config_path(_SELECTION_CONFIG_FILE)


def _resolve_selection(
    plugin_ids: Iterable[str],
    manifest_by_id: dict[str, PluginManifest],
) -> frozenset[str]:
    """Return selected ids closed over dependencies using provided manifests."""
    requested: list[str] = []
    seen_requested: set[str] = set()
    for value in plugin_ids:
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


def load_selected_plugin_ids(
    manifests: Optional[Iterable[PluginManifest]] = None,
) -> frozenset[str]:
    """Return persisted enabled plugin ids or default to all discovered plugins."""
    manifest_list = list(manifests or discover_plugin_manifests())
    manifest_by_id = {manifest.plugin_id: manifest for manifest in manifest_list}
    default_ids = frozenset(manifest_by_id)

    payload = read_json_dict(plugin_selection_config_path())
    if payload is None:
        return default_ids

    raw_ids = payload.get("enabled_plugin_ids")
    if not isinstance(raw_ids, list):
        return default_ids

    return _resolve_selection(raw_ids, manifest_by_id)


def save_selected_plugin_ids(enabled_plugin_ids: Iterable[str]) -> None:
    """Persist selected plugin ids to the local config directory."""
    cleaned = sorted(
        {
            str(plugin_id).strip()
            for plugin_id in enabled_plugin_ids
            if str(plugin_id).strip()
        },
    )
    write_json_dict(
        plugin_selection_config_path(),
        {
            "schema_version": _SELECTION_SCHEMA_VERSION,
            "enabled_plugin_ids": cleaned,
        },
    )


class PluginStartupDialog(qtw.QDialog):
    """Startup dialog that lets the user choose which plugins to load."""

    def __init__(
        self,
        manifests: Iterable[PluginManifest],
        *,
        selected_plugin_ids: Iterable[str] = (),
        parent: Optional[qtw.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlag(QtCore.Qt.Tool, True)
        self.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
        self.setWindowTitle("Select Plugins")
        self.setModal(True)
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.resize(680, 520)
        self.setMinimumSize(560, 420)

        self._manifests = sorted(
            manifests,
            key=lambda item: (item.page, item.display_name.lower(), item.plugin_id),
        )
        self._manifest_by_id = {
            manifest.plugin_id: manifest for manifest in self._manifests
        }
        self._checkbox_by_id: dict[str, qtw.QCheckBox] = {}
        self._dependents_by_id: dict[str, set[str]] = {
            plugin_id: set() for plugin_id in self._manifest_by_id
        }
        self._updating = False

        for manifest in self._manifests:
            for dependency in manifest.dependencies:
                self._dependents_by_id.setdefault(dependency, set()).add(
                    manifest.plugin_id,
                )

        layout = qtw.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._header = build_page_header(
            "Plugin Startup",
            (
                "Choose which plugins to load before opening the main app. "
                "Dependencies stay consistent automatically."
            ),
        )
        layout.addWidget(self._header)
        self._summary_strip = build_summary_strip()
        layout.addWidget(self._summary_strip)

        scroll = qtw.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("WizardScrollArea")
        content = qtw.QWidget()
        content.setObjectName("WizardScrollContent")
        content_layout = qtw.QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        manifests_by_page = {
            page: [manifest for manifest in self._manifests if manifest.page == page]
            for page in PAGE_IDS
        }
        for page in PAGE_IDS:
            group = qtw.QGroupBox(_PAGE_TITLES[page])
            group_layout = qtw.QVBoxLayout(group)
            group_layout.setContentsMargins(10, 10, 10, 10)
            group_layout.setSpacing(8)
            page_manifests = manifests_by_page[page]
            if not page_manifests:
                label = qtw.QLabel("No plugins available.")
                label.setObjectName("MutedLabel")
                group_layout.addWidget(label)
            else:
                for manifest in page_manifests:
                    group_layout.addWidget(self._build_plugin_row(manifest))
            content_layout.addWidget(group)

        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        button_row = qtw.QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = qtw.QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        launch_button = qtw.QPushButton("Launch")
        launch_button.setObjectName("AccentButton")
        launch_button.clicked.connect(self.accept)
        button_row.addWidget(launch_button)
        layout.addLayout(button_row)

        self._apply_initial_selection(selected_plugin_ids)
        self._refresh_summary()

    def _build_plugin_row(self, manifest: PluginManifest) -> qtw.QWidget:
        """Create one plugin row with checkbox and muted details."""
        container = qtw.QFrame()
        container.setObjectName("SubtlePanel")
        layout = qtw.QVBoxLayout(container)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header_row = qtw.QHBoxLayout()
        header_row.setSpacing(8)

        checkbox = qtw.QCheckBox(manifest.display_name)
        checkbox.toggled.connect(
            lambda checked, plugin_id=manifest.plugin_id: self._on_plugin_toggled(
                plugin_id,
                checked,
            ),
        )
        self._checkbox_by_id[manifest.plugin_id] = checkbox
        header_row.addWidget(checkbox)
        header_row.addWidget(
            make_status_chip(
                _PAGE_TITLES.get(manifest.page, manifest.page.title()),
                level="info",
                parent=container,
            ),
        )
        if manifest.dependencies:
            header_row.addWidget(
                make_status_chip(
                    f"{len(manifest.dependencies)} dep",
                    level="warning",
                    tooltip=", ".join(manifest.dependencies),
                    parent=container,
                ),
            )
        header_row.addStretch(1)
        header_row.addWidget(
            make_status_chip(
                manifest.plugin_id,
                level="neutral",
                parent=container,
            ),
        )
        layout.addLayout(header_row)

        details = manifest.description.strip()
        if details:
            label = qtw.QLabel(details)
            label.setObjectName("MutedLabel")
            label.setWordWrap(True)
            label.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(label)
        if manifest.dependencies:
            deps = qtw.QLabel(
                "Depends on: " + ", ".join(manifest.dependencies),
            )
            deps.setObjectName("MutedLabel")
            deps.setWordWrap(True)
            layout.addWidget(deps)
        return container

    def _apply_initial_selection(
        self,
        selected_plugin_ids: Iterable[str],
    ) -> None:
        """Apply startup checkbox state while honoring dependencies."""
        selected_ids = _resolve_selection(
            selected_plugin_ids,
            self._manifest_by_id,
        )
        self._updating = True
        try:
            for manifest in self._manifests:
                checkbox = self._checkbox_by_id[manifest.plugin_id]
                checkbox.setChecked(manifest.plugin_id in selected_ids)
        finally:
            self._updating = False

    def _dependency_closure(self, plugin_id: str) -> set[str]:
        """Return transitive dependencies required by one plugin."""
        resolved: set[str] = set()

        def _visit(current_id: str) -> None:
            manifest = self._manifest_by_id.get(current_id)
            if manifest is None:
                return
            for dependency in manifest.dependencies:
                if dependency in resolved:
                    continue
                resolved.add(dependency)
                _visit(dependency)

        _visit(plugin_id)
        return resolved

    def _dependent_closure(self, plugin_id: str) -> set[str]:
        """Return transitive dependents that must be disabled with a plugin."""
        resolved: set[str] = set()

        def _visit(current_id: str) -> None:
            for dependent in self._dependents_by_id.get(current_id, ()):
                if dependent in resolved:
                    continue
                resolved.add(dependent)
                _visit(dependent)

        _visit(plugin_id)
        return resolved

    def _on_plugin_toggled(self, plugin_id: str, checked: bool) -> None:
        """Keep checkbox state dependency-consistent."""
        if self._updating:
            return
        self._updating = True
        try:
            related_ids = (
                self._dependency_closure(plugin_id)
                if checked
                else self._dependent_closure(plugin_id)
            )
            for related_id in related_ids:
                checkbox = self._checkbox_by_id.get(related_id)
                if checkbox is not None:
                    checkbox.setChecked(checked)
        finally:
            self._updating = False
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        """Refresh top-of-dialog plugin counts by page."""
        enabled = set(self.enabled_plugin_ids())
        counts_by_page = {
            page: sum(
                1
                for manifest in self._manifests
                if manifest.page == page and manifest.plugin_id in enabled
            )
            for page in PAGE_IDS
        }
        total = len(enabled)
        self._header.set_chips(
            [
                ChipSpec(
                    f"{total} enabled",
                    level="success" if total else "warning",
                )
            ]
        )
        self._summary_strip.set_items(
            [
                SummaryItem(
                    _PAGE_TITLES[page],
                    str(counts_by_page[page]),
                    level="success" if counts_by_page[page] else "neutral",
                )
                for page in PAGE_IDS
            ]
        )

    def enabled_plugin_ids(self) -> tuple[str, ...]:
        """Return enabled plugin ids in stable manifest order."""
        return tuple(
            manifest.plugin_id
            for manifest in self._manifests
            if self._checkbox_by_id[manifest.plugin_id].isChecked()
        )
