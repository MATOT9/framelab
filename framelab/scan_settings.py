"""Persistent settings for scan-time skip patterns."""

from __future__ import annotations

import os
from configparser import ConfigParser
from pathlib import Path
from shutil import copy2


_SECTION = "scan"
_OPTION_SKIP_PATTERNS = "skip_patterns"
_CONFIG_DIR_NAME = "config"
_CONFIG_FILE_NAME = "config.ini"


def _unique_cleaned(values: list[str]) -> list[str]:
    """Return deduplicated non-empty values while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _repo_root() -> Path:
    """Return application root directory."""
    return Path(__file__).resolve().parent.parent


def _legacy_user_config_dir() -> Path:
    """Return previous XDG-style config directory."""
    xdg_config = Path(
        os.environ.get(
            "XDG_CONFIG_HOME",
            str(Path.home() / ".config"),
        )
    )
    return xdg_config / "tiff_viewer"


def app_config_dir() -> Path:
    """Return shareable in-app config directory."""
    return _repo_root() / _CONFIG_DIR_NAME


def app_config_path(
    filename: str,
    *,
    legacy_names: tuple[str, ...] = (),
) -> Path:
    """Return a local config file path and migrate legacy files when needed."""
    path = app_config_dir() / filename
    if path.exists():
        return path

    legacy_paths: list[Path] = []
    nuitka_dir = _repo_root() / "nuitka" / "config"
    for legacy_name in legacy_names:
        legacy_paths.append(nuitka_dir / legacy_name)
    legacy_paths.append(_legacy_user_config_dir() / filename)
    for legacy_name in legacy_names:
        legacy_paths.append(_legacy_user_config_dir() / legacy_name)

    seen: set[Path] = set()
    for legacy_path in legacy_paths:
        if legacy_path in seen:
            continue
        seen.add(legacy_path)
        if not legacy_path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        copy2(legacy_path, path)
        break
    return path


def skip_config_path() -> Path:
    """Return config file path used for FrameLab settings."""
    return app_config_path(
        _CONFIG_FILE_NAME,
        legacy_names=(
            "tiff_viewer.ini",
            _CONFIG_FILE_NAME,
        ),
    )


def load_skip_patterns() -> list[str]:
    """Load skip patterns from config."""
    config = ConfigParser()
    path = skip_config_path()
    if path.exists():
        config.read(path, encoding="utf-8")

    raw_text = config.get(_SECTION, _OPTION_SKIP_PATTERNS, fallback="")
    values = [line.strip() for line in raw_text.splitlines()]
    return _unique_cleaned(values)


def save_skip_patterns(patterns: list[str]) -> None:
    """Persist skip patterns to config."""
    cleaned = _unique_cleaned(patterns)
    path = skip_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    config = ConfigParser()
    if path.exists():
        config.read(path, encoding="utf-8")

    if not config.has_section(_SECTION):
        config.add_section(_SECTION)

    if cleaned:
        config.set(_SECTION, _OPTION_SKIP_PATTERNS, "\n".join(cleaned))
    elif config.has_option(_SECTION, _OPTION_SKIP_PATTERNS):
        config.remove_option(_SECTION, _OPTION_SKIP_PATTERNS)

    with path.open("w", encoding="utf-8") as handle:
        config.write(handle)
