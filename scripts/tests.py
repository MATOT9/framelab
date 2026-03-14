"""Small pytest wrapper for common FrameLab test workflows."""

from __future__ import annotations

import os
import sys
import fnmatch
import argparse
import subprocess
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"

UI_PATTERNS = (
    "test_ui_*.py",
    "test_*_page_ui.py",
    "test_preferences_dialog.py",
    "test_window_density.py",
)
DATA_PATTERNS = (
    "test_data_page_ui.py",
    "test_dataset_state.py",
    "test_metadata_resolution.py",
    "test_ebus_metadata_resolution.py",
    "test_session_manager.py",
    "test_image_io.py",
)
ANALYSIS_PATTERNS = (
    "test_analysis_*.py",
    "test_metrics_math.py",
)
FAST_PATTERNS = (
    "test_dataset_state.py",
    "test_plugin_registry.py",
    "test_metrics_state.py",
    "test_metrics_math.py",
    "test_background.py",
    "test_image_io.py",
    "test_ui_density.py",
    "test_ui_settings.py",
)

SUITE_HELP = {
    "all": "every test module under tests/",
    "fast": "small, mostly non-Qt regression set",
    "ui": "Qt-heavy UI, density, and page layout regressions",
    "data": "dataset loading, metadata, session, and eBUS flows",
    "analysis": "analysis context, math, and analysis-page behavior",
    "core": "everything except the UI-focused suite",
}


def _all_test_files() -> list[Path]:
    """Return all test files in a stable order."""
    return sorted(TESTS_DIR.glob("test_*.py"))


def _matches_any(path: Path, patterns: tuple[str, ...]) -> bool:
    """Return whether the file name matches any provided shell pattern."""
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)


def _files_for_suite(name: str) -> list[Path]:
    """Resolve one named suite to concrete test files."""
    files = _all_test_files()
    if name == "all":
        return files
    if name == "fast":
        return [path for path in files if _matches_any(path, FAST_PATTERNS)]
    if name == "ui":
        return [path for path in files if _matches_any(path, UI_PATTERNS)]
    if name == "data":
        return [path for path in files if _matches_any(path, DATA_PATTERNS)]
    if name == "analysis":
        return [path for path in files if _matches_any(path, ANALYSIS_PATTERNS)]
    if name == "core":
        ui_files = set(_files_for_suite("ui"))
        return [path for path in files if path not in ui_files]
    raise KeyError(name)


def _resolve_target(target: str) -> list[Path]:
    """Resolve one CLI target into test files."""
    candidate = Path(target)
    if any(char in target for char in "*?[]"):
        return [
            path
            for path in _all_test_files()
            if fnmatch.fnmatch(path.name, target)
            or fnmatch.fnmatch(str(path.relative_to(REPO_ROOT)), target)
        ]

    search_order = (
        candidate,
        REPO_ROOT / candidate,
        TESTS_DIR / candidate,
        TESTS_DIR / f"{target}.py",
    )
    for option in search_order:
        if option.is_file():
            return [option.resolve()]
    raise FileNotFoundError(target)


def _dedupe(files: list[Path]) -> list[Path]:
    """Return files with duplicates removed while preserving order."""
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _selected_files(args: argparse.Namespace) -> list[Path]:
    """Resolve the effective file selection from CLI arguments."""
    selected: list[Path] = []
    if not args.suite and not args.pattern and not args.targets:
        args.suite = ["all"]

    for suite_name in args.suite:
        selected.extend(_files_for_suite(suite_name))
    for pattern in args.pattern:
        selected.extend(_resolve_target(pattern))
    for target in args.targets:
        selected.extend(_resolve_target(target))

    return _dedupe(selected)


def _build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Run FrameLab pytest suites.",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Explicit test files or glob patterns such as tests/test_background.py or test_ui_*.py.",
    )
    parser.add_argument(
        "--suite",
        action="append",
        choices=sorted(SUITE_HELP),
        default=[],
        help="Named suite to run. May be repeated.",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="Additional glob pattern to match against tests/ files.",
    )
    parser.add_argument(
        "--list-suites",
        action="store_true",
        help="Show the available named suites and exit.",
    )
    parser.add_argument(
        "--show-files",
        action="store_true",
        help="Print the selected test files before running them.",
    )
    parser.add_argument(
        "--failfast",
        action="store_true",
        help="Stop on the first failure or error.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Use verbose runner output.",
    )
    return parser


def _pytest_available() -> bool:
    """Return whether pytest can be imported in the active environment."""

    return importlib.util.find_spec("pytest") is not None


def _run_pytest(files: list[Path], args: argparse.Namespace) -> int:
    """Run the selected files through pytest."""

    cmd = [sys.executable, "-m", "pytest"]
    if args.verbose:
        cmd.append("-v")
    if args.failfast:
        cmd.append("-x")
    cmd.extend(str(path) for path in files)
    completed = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=False,
    )
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Default to an offscreen Qt backend in shell-driven test runs. Users can
    # still override this explicitly in their environment when they want a
    # visible platform plugin.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    if args.list_suites:
        for name in sorted(SUITE_HELP):
            print(f"{name:8} {SUITE_HELP[name]}")
        return 0

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    if str(TESTS_DIR) not in sys.path:
        sys.path.insert(0, str(TESTS_DIR))

    try:
        files = _selected_files(args)
    except (FileNotFoundError, KeyError, RuntimeError) as exc:
        parser.error(str(exc))

    if not files:
        parser.error("No test files matched the requested suites/patterns.")

    if args.show_files:
        for path in files:
            print(path.relative_to(REPO_ROOT))

    if not _pytest_available():
        parser.error(
            "pytest is not installed in the active environment. "
            "Install it before running the test suite.",
        )
    return _run_pytest(files, args)


if __name__ == "__main__":
    raise SystemExit(main())
