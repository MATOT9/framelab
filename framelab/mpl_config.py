"""Helpers for configuring Matplotlib runtime paths safely."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def matplotlib_config_dir() -> Path:
    """Return a writable cache/config directory for Matplotlib."""

    xdg_cache_home = os.environ.get("XDG_CACHE_HOME", "").strip()
    cache_root = Path(xdg_cache_home) if xdg_cache_home else Path.home() / ".cache"
    return cache_root / "framelab" / "matplotlib"


def _writable_config_dir_candidates() -> tuple[Path, ...]:
    """Return ordered candidate directories for Matplotlib runtime state."""

    return (
        matplotlib_config_dir(),
        Path("/tmp") / "framelab" / "matplotlib",
    )


def _can_write_directory(path: Path) -> bool:
    """Return whether a directory can actually be written to."""

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    try:
        with NamedTemporaryFile(dir=path, prefix=".framelab_mpl_", delete=True):
            pass
    except OSError:
        return False
    return True


def ensure_matplotlib_config_dir() -> Path:
    """Ensure Matplotlib uses a writable config/cache directory."""

    configured = os.environ.get("MPLCONFIGDIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if _can_write_directory(path):
            os.environ["MPLCONFIGDIR"] = str(path)
            return path
    for path in _writable_config_dir_candidates():
        if _can_write_directory(path):
            os.environ["MPLCONFIGDIR"] = str(path)
            return path
    raise OSError("Could not create a writable Matplotlib config directory.")


__all__ = ["ensure_matplotlib_config_dir", "matplotlib_config_dir"]
