"""Build the offline FrameLab documentation site.

This script has two responsibilities:
1. build the MkDocs site into a temporary output directory; and
2. optionally copy that built site into ``framelab/assets/help`` so the
   application Help menu opens the same content that was just built.

The script deliberately keeps the build output and the bundled-help output as
separate concepts. The generated site directory is disposable; the bundled-help
copy is the runtime asset used by the application.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


_DOCS_PYTHON_TARGET_DIRNAME = ".docs_build_deps"
_DEFAULT_BUILD_SITE_SUBDIR = ".docs_build/site"
_LEGACY_CHECK_SITE_SUBDIR = ".docs_check_site"
_BUNDLED_HELP_SUBDIR = "framelab/assets/help"


def _repo_root() -> Path:
    """Return repository root directory."""
    return Path(__file__).resolve().parents[2]


def _local_docs_deps_dir() -> Path:
    """Return optional local build-only dependency directory."""
    return _repo_root() / _DOCS_PYTHON_TARGET_DIRNAME


def _mkdocs_config_path() -> Path:
    """Return MkDocs config path."""
    return _repo_root() / "mkdocs.yml"


def _default_build_site_dir() -> Path:
    """Return temporary docs build output directory."""
    return _repo_root() / _DEFAULT_BUILD_SITE_SUBDIR


def _legacy_check_site_dir() -> Path:
    """Return obsolete legacy output directory kept for cleanup only."""
    return _repo_root() / _LEGACY_CHECK_SITE_SUBDIR


def _bundled_help_dir() -> Path:
    """Return in-app bundled help output directory."""
    return _repo_root() / _BUNDLED_HELP_SUBDIR


def _docs_install_hint() -> str:
    """Return the recommended command for installing docs build dependencies."""
    return (
        "python3 -m pip install --target ./.docs_build_deps "
        "mkdocs mkdocs-material pymdown-extensions"
    )


def _resolve_mathjax_source_dir() -> Path:
    """Return MathJax asset directory from the active Python environment."""
    env_override = os.environ.get("FRAMELAB_MATHJAX_DIR", "").strip()
    if not env_override:
        env_override = os.environ.get("TIFF_VIEWER_MATHJAX_DIR", "").strip()
    if env_override:
        candidate = Path(env_override).expanduser().resolve()
        if candidate.exists():
            return candidate

    mathjax_path_cmd = shutil.which("mathjax-path")
    if mathjax_path_cmd is not None:
        result = subprocess.run(
            [mathjax_path_cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            candidate = Path(result.stdout.strip()).expanduser().resolve()
            if candidate.exists():
                return candidate

    candidate = (
        Path(sys.executable).resolve().parent.parent / "lib" / "mathjax" / "es5"
    )
    if candidate.exists():
        return candidate

    raise SystemExit(
        "MathJax assets were not found in the active environment.\n"
        "Install the environment package first, for example:\n"
        "mamba install mathjax\n"
        "or set FRAMELAB_MATHJAX_DIR to the MathJax asset directory.",
    )


def _stage_mathjax_assets(site_dir: Path) -> None:
    """Copy MathJax assets from the active environment into the built site."""
    target_dir = site_dir / "assets" / "vendor" / "mathjax"
    source_dir = _resolve_mathjax_source_dir()
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_dir)


def _build_env() -> dict[str, str]:
    """Return subprocess environment with local docs deps prepended."""
    env = os.environ.copy()
    # Silence the package-side Material banner about MkDocs 2.0. This project
    # pins and validates its own docs toolchain explicitly.
    env.setdefault("NO_MKDOCS_2_WARNING", "1")
    deps_dir = _local_docs_deps_dir()
    if deps_dir.exists():
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(deps_dir) if not existing else f"{deps_dir}{os.pathsep}{existing}"
        )
    return env


def _ensure_mkdocs_available(env: dict[str, str]) -> None:
    """Raise a readable error when the MkDocs toolchain is unavailable."""
    check = subprocess.run(
        [sys.executable, "-c", "import mkdocs, material, pymdownx"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode == 0:
        return
    raise SystemExit(
        "The documentation build toolchain is not available.\n"
        f"Install it with:\n{_docs_install_hint()}"
    )


def _run_mkdocs(site_dir: Path, *, strict: bool) -> None:
    """Run MkDocs build into the requested site directory."""
    env = _build_env()
    _ensure_mkdocs_available(env)
    site_dir.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "mkdocs",
        "build",
        "--clean",
        "-f",
        str(_mkdocs_config_path()),
        "-d",
        str(site_dir),
    ]
    if strict:
        cmd.append("--strict")
    subprocess.run(cmd, env=env, check=True)


def _copy_site_to_help_bundle(site_dir: Path) -> None:
    """Copy freshly built site into the app help asset directory."""
    target_dir = _bundled_help_dir()
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(site_dir, target_dir)


def _cleanup_legacy_docs_outputs() -> None:
    """Remove obsolete documentation output directories if present."""
    legacy_dir = _legacy_check_site_dir()
    if legacy_dir.exists():
        shutil.rmtree(legacy_dir)


def main(argv: list[str] | None = None) -> int:
    """Build docs site and optionally refresh bundled offline help assets."""
    parser = argparse.ArgumentParser(
        description="Build the FrameLab documentation site.",
    )
    parser.add_argument(
        "--site-dir",
        type=Path,
        default=_default_build_site_dir(),
        help="Temporary build output directory.",
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Do not copy the built site into framelab/assets/help.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Run mkdocs build in strict mode.",
    )
    args = parser.parse_args(argv)

    site_dir = args.site_dir.resolve()
    _cleanup_legacy_docs_outputs()
    if site_dir.exists():
        shutil.rmtree(site_dir)

    _run_mkdocs(site_dir, strict=bool(args.strict))
    _stage_mathjax_assets(site_dir)
    if not args.no_copy:
        _copy_site_to_help_bundle(site_dir)
        print(f"Bundled help updated: {_bundled_help_dir()}")
    else:
        print(f"Docs built without copy: {site_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
