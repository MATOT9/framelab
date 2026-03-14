"""Validate documentation sources and the offline help build.

The check is intentionally conservative:
- ensure the required Markdown, asset, and configuration files exist;
- run a strict MkDocs build into a disposable output directory; and
- verify that the build produced key HTML entry points.

This script is meant to catch documentation drift before it reaches the bundled
offline-help assets used by the application.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys


_DOCS_BUILD_DIR = Path(".docs_build")
_CHECK_SITE_SUBDIR = _DOCS_BUILD_DIR / "check-site"

REQUIRED_FILES = (
    "mkdocs.yml",
    "docs_layout.md",
    "docs/index.md",
    "docs/user-guide/index.md",
    "docs/user-guide/concepts-and-limits.md",
    "docs/user-guide/quick-start.md",
    "docs/user-guide/plugins.md",
    "docs/user-guide/plugin-selector.md",
    "docs/user-guide/data-workflow.md",
    "docs/user-guide/data/session-manager.md",
    "docs/user-guide/data/datacard-wizard.md",
    "docs/user-guide/measure-workflow.md",
    "docs/user-guide/analysis-workflow.md",
    "docs/user-guide/analysis/intensity-trend-explorer.md",
    "docs/user-guide/data/ebus-config-tools.md",
    "docs/user-guide/troubleshooting.md",
    "docs/developer-guide/index.md",
    "docs/developer-guide/architecture.md",
    "docs/developer-guide/plugin-system.md",
    "docs/developer-guide/datacard-system.md",
    "docs/developer-guide/ebus-config-integration.md",
    "docs/developer-guide/ui-structure.md",
    "docs/developer-guide/packaging.md",
    "docs/reference/index.md",
    "docs/reference/config-files.md",
    "docs/reference/plugin-manifests.md",
    "docs/reference/acquisition-mapping.md",
    "docs/reference/ebus-parameter-catalog.md",
    "docs/reference/keyboard-shortcuts.md",
    "docs/troubleshooting/index.md",
    "docs/stylesheets/extra.css",
    "docs/assets/images/branding/app-icon.png",
    "docs/assets/images/placeholders/screenshot-placeholder-16x9.svg",
    "docs/assets/images/placeholders/figure-placeholder-4x3.svg",
    "docs/assets/javascripts/mathjax-config.js",
    "scripts/docs/build.py",
)

EXPECTED_BUILD_OUTPUTS = (
    ".docs_build/check-site/index.html",
    ".docs_build/check-site/user-guide/index.html",
    ".docs_build/check-site/user-guide/concepts-and-limits.html",
    ".docs_build/check-site/user-guide/quick-start.html",
    ".docs_build/check-site/user-guide/data/session-manager.html",
    ".docs_build/check-site/user-guide/data/ebus-config-tools.html",
    ".docs_build/check-site/developer-guide/index.html",
    ".docs_build/check-site/developer-guide/ebus-config-integration.html",
    ".docs_build/check-site/reference/index.html",
    ".docs_build/check-site/reference/ebus-parameter-catalog.html",
    ".docs_build/check-site/troubleshooting/index.html",
)


def _repo_root() -> Path:
    """Return repository root directory."""
    return Path(__file__).resolve().parents[2]


def _check_required_files() -> None:
    """Fail if any required documentation source file is missing."""
    repo_root = _repo_root()
    missing = [
        relative_path
        for relative_path in REQUIRED_FILES
        if not (repo_root / relative_path).exists()
    ]
    if missing:
        joined = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(f"Missing required documentation files:\n{joined}")


def _run_strict_build() -> None:
    """Run the docs build script in strict mode without copying output."""
    repo_root = _repo_root()
    site_dir = repo_root / _CHECK_SITE_SUBDIR
    legacy_dir = repo_root / ".docs_check_site"
    if legacy_dir.exists():
        shutil.rmtree(legacy_dir)
    if site_dir.exists():
        shutil.rmtree(site_dir)
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "docs" / "build.py"),
            "--strict",
            "--no-copy",
            "--site-dir",
            str(site_dir),
        ],
        check=True,
        cwd=repo_root,
    )


def _check_build_outputs() -> None:
    """Fail if key built HTML files are missing."""
    repo_root = _repo_root()
    missing = [
        relative_path
        for relative_path in EXPECTED_BUILD_OUTPUTS
        if not (repo_root / relative_path).exists()
    ]
    if missing:
        joined = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(f"Missing expected built documentation outputs:\n{joined}")


def main() -> int:
    """Run docs source and build validation."""
    _check_required_files()
    _run_strict_build()
    _check_build_outputs()
    print("Documentation sources and build outputs validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
