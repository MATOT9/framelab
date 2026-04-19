"""Helpers for locating package-bundled runtime assets."""

from __future__ import annotations

from pathlib import Path


def package_dir() -> Path:
    """Return the root directory of the installed ``framelab`` package."""

    return Path(__file__).resolve().parent


def assets_dir() -> Path:
    """Return the packaged runtime assets directory."""

    return package_dir() / "assets"


def asset_path(*parts: str) -> Path:
    """Return the path to one packaged runtime asset."""

    return assets_dir().joinpath(*parts)


def labreport_style_path() -> Path:
    """Return the packaged Matplotlib style file path."""

    return asset_path("LabReport.mplstyle")


__all__ = [
    "asset_path",
    "assets_dir",
    "labreport_style_path",
    "package_dir",
]
