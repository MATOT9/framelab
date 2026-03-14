"""Helpers for locating eBUS snapshot files in acquisition folders."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


ACQUISITION_EBUS_CONFIG_NAME = "acquisition_ebus_config.pvcfg"
EBUS_PARSE_VERSION = "1.0"


def attached_ebus_config_path(acquisition_root: str | Path) -> Path:
    """Return the attached eBUS sidecar path for an acquisition root."""
    return Path(acquisition_root).joinpath(ACQUISITION_EBUS_CONFIG_NAME)


def has_attached_ebus_config(acquisition_root: str | Path) -> bool:
    """Return whether an acquisition root carries an attached eBUS sidecar."""
    return attached_ebus_config_path(acquisition_root).is_file()


def discover_ebus_snapshot_path(acquisition_root: str | Path) -> Path | None:
    """Return the best available eBUS snapshot file under one acquisition root.

    The app intentionally avoids treating one ``.pvcfg`` filename as special for
    normal acquisition discovery. If exactly one ``.pvcfg`` exists at the
    acquisition root, it becomes the baseline snapshot source regardless of its
    name. If several root-level ``.pvcfg`` files exist, the caller must
    disambiguate instead of guessing.
    """
    root = Path(acquisition_root)
    if not root.is_dir():
        return None
    pvcfg_files = sorted(
        child for child in root.iterdir()
        if child.is_file() and child.suffix.lower() == ".pvcfg"
    )
    if len(pvcfg_files) == 1:
        return pvcfg_files[0]
    return None


def file_sha256(path: str | Path) -> str:
    """Return SHA-256 digest for a file."""
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
