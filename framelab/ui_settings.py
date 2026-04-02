"""Persistent UI preferences and workspace state for FrameLab."""

from __future__ import annotations

import json
from configparser import ConfigParser
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .scan_settings import app_config_path

_CONFIG_FILE_NAME = "ui_state.ini"
_LEGACY_CONFIG_NAMES: tuple[str, ...] = ()
_SECTION_APPEARANCE = "appearance"
_SECTION_WORKSPACE = "workspace"
_SECTION_DATA_PAGE = "data_page"
_SECTION_ANALYSIS_PAGE = "analysis_page"
_SECTION_PANELS = "panels"
_SECTION_SPLITTERS = "splitters"
_SECTION_RECENT_WORKFLOWS = "recent_workflows"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


class DensityMode(StrEnum):
    """User-selected chrome density preference."""

    COMFORTABLE = "comfortable"
    COMPACT = "compact"
    AUTO = "auto"


@dataclass(slots=True)
class UiPreferences:
    """Persisted UI preferences that shape workspace behavior."""

    theme_mode: str = "dark"
    density_mode: DensityMode = DensityMode.AUTO
    show_page_subtitles: bool = True
    show_image_preview: bool = True
    show_histogram_preview: bool = False
    restore_panel_states: bool = True
    restore_last_tab: bool = True
    collapse_analysis_plugin_controls_by_default: bool = True
    collapse_data_advanced_row_by_default: bool = True
    collapse_summary_strips_by_default: bool = False
    scan_worker_count_override: int | None = None
    use_mmap_for_raw: bool = True
    enable_raw_simd: bool = True


@dataclass(slots=True)
class UiPanelState:
    """Simple persisted disclosure state for one panel."""

    expanded: bool | None = None


@dataclass(slots=True)
class RecentWorkflowEntry:
    """One recently used workflow workspace/profile pair."""

    workspace_root: str
    profile_id: str
    anchor_type_id: str | None = None
    active_node_id: str | None = None


@dataclass(slots=True)
class UiStateSnapshot:
    """Complete UI snapshot persisted between launches."""

    preferences: UiPreferences = field(default_factory=UiPreferences)
    panel_states: dict[str, bool] = field(default_factory=dict)
    splitter_sizes: dict[str, list[int]] = field(default_factory=dict)
    last_tab_index: int | None = None
    last_analysis_plugin_id: str | None = None
    workflow_workspace_root: str | None = None
    workflow_profile_id: str | None = None
    workflow_anchor_type_id: str | None = None
    workflow_active_node_id: str | None = None
    recent_workflows: list[RecentWorkflowEntry] = field(default_factory=list)


def ui_state_config_path() -> Path:
    """Return the shared config path used for UI persistence."""

    return app_config_path(
        _CONFIG_FILE_NAME,
        legacy_names=_LEGACY_CONFIG_NAMES,
    )


def _normalize_theme_mode(value: object) -> str:
    text = str(value).strip().lower()
    return "light" if text == "light" else "dark"


def _parse_bool(value: object, fallback: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return fallback


def _parse_density_mode(value: object) -> DensityMode:
    text = str(value).strip().lower()
    for mode in DensityMode:
        if mode.value == text:
            return mode
    return DensityMode.AUTO


def _parse_int(value: object, fallback: int | None = None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _parse_positive_optional_int(value: object, fallback: int | None = None) -> int | None:
    parsed = _parse_int(value, fallback)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _parse_splitter_sizes(value: object) -> list[int] | None:
    text = str(value).strip()
    if not text:
        return None
    sizes: list[int] = []
    for token in text.split(","):
        cleaned = token.strip()
        if not cleaned:
            continue
        try:
            sizes.append(int(cleaned))
        except ValueError:
            return None
    return sizes or None


def _serialize_bool(value: bool) -> str:
    return "true" if value else "false"


def _serialize_splitter_sizes(sizes: list[int]) -> str:
    return ",".join(str(int(size)) for size in sizes)


def _parse_recent_workflow_entry(value: object) -> RecentWorkflowEntry | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    workspace_root = str(payload.get("workspace_root", "")).strip()
    profile_id = str(payload.get("profile_id", "")).strip().lower()
    if not workspace_root or not profile_id:
        return None
    anchor_type_id = str(payload.get("anchor_type_id", "")).strip().lower() or None
    active_node_id = str(payload.get("active_node_id", "")).strip() or None
    return RecentWorkflowEntry(
        workspace_root=workspace_root,
        profile_id=profile_id,
        anchor_type_id=anchor_type_id,
        active_node_id=active_node_id,
    )


def _serialize_recent_workflow_entry(entry: RecentWorkflowEntry) -> str:
    return json.dumps(
        {
            "workspace_root": entry.workspace_root,
            "profile_id": entry.profile_id,
            "anchor_type_id": entry.anchor_type_id,
            "active_node_id": entry.active_node_id,
        },
        ensure_ascii=True,
        sort_keys=True,
    )


class UiStateStore:
    """Config-backed persistence for UI preferences and workspace state."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or ui_state_config_path()

    def load(self) -> UiStateSnapshot:
        """Load persisted UI state with safe defaults."""

        config = self._read_config()
        defaults = UiPreferences()
        preferences = UiPreferences(
            theme_mode=_normalize_theme_mode(
                config.get(
                    _SECTION_APPEARANCE,
                    "theme",
                    fallback=defaults.theme_mode,
                ),
            ),
            density_mode=_parse_density_mode(
                config.get(
                    _SECTION_APPEARANCE,
                    "density_mode",
                    fallback=defaults.density_mode.value,
                ),
            ),
            show_page_subtitles=bool(
                _parse_bool(
                    config.get(
                        _SECTION_APPEARANCE,
                        "show_page_subtitles",
                        fallback=defaults.show_page_subtitles,
                    ),
                    defaults.show_page_subtitles,
                ),
            ),
            show_image_preview=bool(
                _parse_bool(
                    config.get(
                        _SECTION_WORKSPACE,
                        "show_image_preview",
                        fallback=defaults.show_image_preview,
                    ),
                    defaults.show_image_preview,
                ),
            ),
            show_histogram_preview=bool(
                _parse_bool(
                    config.get(
                        _SECTION_WORKSPACE,
                        "show_histogram_preview",
                        fallback=defaults.show_histogram_preview,
                    ),
                    defaults.show_histogram_preview,
                ),
            ),
            restore_panel_states=bool(
                _parse_bool(
                    config.get(
                        _SECTION_WORKSPACE,
                        "restore_panel_states",
                        fallback=defaults.restore_panel_states,
                    ),
                    defaults.restore_panel_states,
                ),
            ),
            restore_last_tab=bool(
                _parse_bool(
                    config.get(
                        _SECTION_WORKSPACE,
                        "restore_last_tab",
                        fallback=defaults.restore_last_tab,
                    ),
                    defaults.restore_last_tab,
                ),
            ),
            collapse_analysis_plugin_controls_by_default=bool(
                _parse_bool(
                    config.get(
                        _SECTION_ANALYSIS_PAGE,
                        "collapse_plugin_controls_by_default",
                        fallback=defaults.collapse_analysis_plugin_controls_by_default,
                    ),
                    defaults.collapse_analysis_plugin_controls_by_default,
                ),
            ),
            collapse_data_advanced_row_by_default=bool(
                _parse_bool(
                    config.get(
                        _SECTION_DATA_PAGE,
                        "collapse_advanced_row_by_default",
                        fallback=defaults.collapse_data_advanced_row_by_default,
                    ),
                    defaults.collapse_data_advanced_row_by_default,
                ),
            ),
            collapse_summary_strips_by_default=bool(
                _parse_bool(
                    config.get(
                        _SECTION_WORKSPACE,
                        "collapse_summary_strips_by_default",
                        fallback=defaults.collapse_summary_strips_by_default,
                    ),
                    defaults.collapse_summary_strips_by_default,
                ),
            ),
            scan_worker_count_override=_parse_positive_optional_int(
                config.get(
                    _SECTION_DATA_PAGE,
                    "scan_worker_count_override",
                    fallback=defaults.scan_worker_count_override,
                ),
                defaults.scan_worker_count_override,
            ),
            use_mmap_for_raw=bool(
                _parse_bool(
                    config.get(
                        _SECTION_DATA_PAGE,
                        "use_mmap_for_raw",
                        fallback=defaults.use_mmap_for_raw,
                    ),
                    defaults.use_mmap_for_raw,
                ),
            ),
            enable_raw_simd=bool(
                _parse_bool(
                    config.get(
                        _SECTION_DATA_PAGE,
                        "enable_raw_simd",
                        fallback=defaults.enable_raw_simd,
                    ),
                    defaults.enable_raw_simd,
                ),
            ),
        )

        panel_states: dict[str, bool] = {}
        if config.has_section(_SECTION_PANELS):
            for key, raw_value in config.items(_SECTION_PANELS):
                parsed = _parse_bool(raw_value)
                if parsed is not None:
                    panel_states[key] = parsed

        splitter_sizes: dict[str, list[int]] = {}
        if config.has_section(_SECTION_SPLITTERS):
            for key, raw_value in config.items(_SECTION_SPLITTERS):
                parsed = _parse_splitter_sizes(raw_value)
                if parsed is not None:
                    splitter_sizes[key] = parsed

        last_tab_index = _parse_int(
            config.get(
                _SECTION_WORKSPACE,
                "last_workflow_tab",
                fallback=None,
            ),
        )
        if last_tab_index is not None and last_tab_index < 0:
            last_tab_index = None

        raw_plugin_id = config.get(
            _SECTION_ANALYSIS_PAGE,
            "last_plugin_id",
            fallback="",
        )
        last_analysis_plugin_id = str(raw_plugin_id).strip() or None
        workflow_workspace_root = (
            config.get(
                _SECTION_WORKSPACE,
                "workflow_root",
                fallback="",
            ).strip()
            or None
        )
        workflow_profile_id = (
            config.get(
                _SECTION_WORKSPACE,
                "workflow_profile_id",
                fallback="",
            ).strip()
            or None
        )
        workflow_anchor_type_id = (
            config.get(
                _SECTION_WORKSPACE,
                "workflow_anchor_type_id",
                fallback="",
            ).strip()
            or None
        )
        workflow_active_node_id = (
            config.get(
                _SECTION_WORKSPACE,
                "workflow_active_node_id",
                fallback="",
            ).strip()
            or None
        )
        recent_workflows: list[RecentWorkflowEntry] = []
        if config.has_section(_SECTION_RECENT_WORKFLOWS):
            for _key, raw_value in sorted(config.items(_SECTION_RECENT_WORKFLOWS)):
                entry = _parse_recent_workflow_entry(raw_value)
                if entry is not None:
                    recent_workflows.append(entry)

        return UiStateSnapshot(
            preferences=preferences,
            panel_states=panel_states,
            splitter_sizes=splitter_sizes,
            last_tab_index=last_tab_index,
            last_analysis_plugin_id=last_analysis_plugin_id,
            workflow_workspace_root=workflow_workspace_root,
            workflow_profile_id=workflow_profile_id,
            workflow_anchor_type_id=workflow_anchor_type_id,
            workflow_active_node_id=workflow_active_node_id,
            recent_workflows=recent_workflows,
        )

    def save(self, snapshot: UiStateSnapshot) -> None:
        """Persist a complete UI state snapshot while preserving other config."""

        config = self._read_config()
        self._set_option(
            config,
            _SECTION_APPEARANCE,
            "theme",
            _normalize_theme_mode(snapshot.preferences.theme_mode),
        )
        self._set_option(
            config,
            _SECTION_APPEARANCE,
            "density_mode",
            snapshot.preferences.density_mode.value,
        )
        self._set_option(
            config,
            _SECTION_APPEARANCE,
            "show_page_subtitles",
            _serialize_bool(snapshot.preferences.show_page_subtitles),
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "show_image_preview",
            _serialize_bool(snapshot.preferences.show_image_preview),
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "show_histogram_preview",
            _serialize_bool(snapshot.preferences.show_histogram_preview),
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "restore_panel_states",
            _serialize_bool(snapshot.preferences.restore_panel_states),
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "restore_last_tab",
            _serialize_bool(snapshot.preferences.restore_last_tab),
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "collapse_summary_strips_by_default",
            _serialize_bool(snapshot.preferences.collapse_summary_strips_by_default),
        )
        self._set_option(
            config,
            _SECTION_DATA_PAGE,
            "collapse_advanced_row_by_default",
            _serialize_bool(snapshot.preferences.collapse_data_advanced_row_by_default),
        )
        self._set_option(
            config,
            _SECTION_DATA_PAGE,
            "scan_worker_count_override",
            None
            if snapshot.preferences.scan_worker_count_override is None
            else str(max(1, int(snapshot.preferences.scan_worker_count_override))),
        )
        self._set_option(
            config,
            _SECTION_DATA_PAGE,
            "use_mmap_for_raw",
            _serialize_bool(snapshot.preferences.use_mmap_for_raw),
        )
        self._set_option(
            config,
            _SECTION_DATA_PAGE,
            "enable_raw_simd",
            _serialize_bool(snapshot.preferences.enable_raw_simd),
        )
        self._set_option(
            config,
            _SECTION_ANALYSIS_PAGE,
            "collapse_plugin_controls_by_default",
            _serialize_bool(
                snapshot.preferences.collapse_analysis_plugin_controls_by_default
            ),
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "last_workflow_tab",
            None
            if snapshot.last_tab_index is None
            else str(int(snapshot.last_tab_index)),
        )
        self._set_option(
            config,
            _SECTION_ANALYSIS_PAGE,
            "last_plugin_id",
            snapshot.last_analysis_plugin_id or None,
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "workflow_root",
            snapshot.workflow_workspace_root or None,
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "workflow_profile_id",
            snapshot.workflow_profile_id or None,
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "workflow_anchor_type_id",
            snapshot.workflow_anchor_type_id or None,
        )
        self._set_option(
            config,
            _SECTION_WORKSPACE,
            "workflow_active_node_id",
            snapshot.workflow_active_node_id or None,
        )
        self._replace_section(
            config,
            _SECTION_PANELS,
            {
                key: _serialize_bool(value)
                for key, value in sorted(snapshot.panel_states.items())
            },
        )
        self._replace_section(
            config,
            _SECTION_SPLITTERS,
            {
                key: _serialize_splitter_sizes(value)
                for key, value in sorted(snapshot.splitter_sizes.items())
                if value
            },
        )
        self._replace_section(
            config,
            _SECTION_RECENT_WORKFLOWS,
            {
                f"entry_{index:02d}": _serialize_recent_workflow_entry(entry)
                for index, entry in enumerate(snapshot.recent_workflows[:8], start=1)
                if entry.workspace_root and entry.profile_id
            },
        )
        self._write_config(config)

    def set_panel_state(self, key: str, expanded: bool) -> None:
        """Persist one panel disclosure state."""

        clean_key = str(key).strip()
        if not clean_key:
            return
        config = self._read_config()
        self._set_option(
            config,
            _SECTION_PANELS,
            clean_key,
            _serialize_bool(bool(expanded)),
        )
        self._write_config(config)

    def panel_state(self, key: str) -> bool | None:
        """Return the persisted state for one panel if available."""

        clean_key = str(key).strip()
        if not clean_key:
            return None
        return self.load().panel_states.get(clean_key)

    def set_splitter_sizes(self, key: str, sizes: list[int]) -> None:
        """Persist the latest splitter sizes for one splitter."""

        clean_key = str(key).strip()
        if not clean_key:
            return
        normalized = [int(size) for size in sizes]
        config = self._read_config()
        self._set_option(
            config,
            _SECTION_SPLITTERS,
            clean_key,
            _serialize_splitter_sizes(normalized) if normalized else None,
        )
        self._write_config(config)

    def splitter_sizes(self, key: str) -> list[int] | None:
        """Return persisted splitter sizes for one splitter if available."""

        clean_key = str(key).strip()
        if not clean_key:
            return None
        sizes = self.load().splitter_sizes.get(clean_key)
        return list(sizes) if sizes is not None else None

    def _read_config(self) -> ConfigParser:
        config = ConfigParser()
        if self.path.exists():
            config.read(self.path, encoding="utf-8")
        return config

    def _write_config(self, config: ConfigParser) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            config.write(handle)

    @staticmethod
    def _ensure_section(config: ConfigParser, section: str) -> None:
        if not config.has_section(section):
            config.add_section(section)

    @classmethod
    def _set_option(
        cls,
        config: ConfigParser,
        section: str,
        option: str,
        value: str | None,
    ) -> None:
        cls._ensure_section(config, section)
        if value is None:
            if config.has_option(section, option):
                config.remove_option(section, option)
            return
        config.set(section, option, value)

    @classmethod
    def _replace_section(
        cls,
        config: ConfigParser,
        section: str,
        values: dict[str, str],
    ) -> None:
        if config.has_section(section):
            config.remove_section(section)
        if not values:
            return
        config.add_section(section)
        for key, value in values.items():
            config.set(section, key, value)


__all__ = [
    "DensityMode",
    "UiPanelState",
    "UiPreferences",
    "UiStateSnapshot",
    "UiStateStore",
    "ui_state_config_path",
]
