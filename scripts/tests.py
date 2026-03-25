"""Small pytest wrapper for common FrameLab test workflows."""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"

UI_PATTERNS = (
    "test_ui_*.py",
    "test_*_page_ui.py",
    "test_preferences_dialog.py",
    "test_window_density.py",
    "test_workflow_*_dialog.py",
    "test_*_dock.py",
)
DATA_PATTERNS = (
    "test_data_page_ui.py",
    "test_dataset_state.py",
    "test_metadata_resolution.py",
    "test_ebus_metadata_resolution.py",
    "test_session_manager.py",
    "test_image_io.py",
    "test_workspace_document.py",
)
ANALYSIS_PATTERNS = (
    "test_analysis_*.py",
    "test_metrics_math.py",
)
FAST_PATTERNS = (
    "test_background.py",
    "test_dataset_state.py",
    "test_icons.py",
    "test_metrics_math.py",
    "test_metrics_state.py",
    "test_plugin_registry.py",
    "test_scan_settings.py",
    "test_scripts_tests.py",
    "test_ui_density.py",
    "test_ui_settings.py",
)
FAST_SMOKE_PATTERNS = (
    "test_metrics_state.py",
    "test_plugin_registry.py",
    "test_ui_settings.py",
)
SOURCE_TEST_MAP = {
    "analysis.py": ("test_analysis_page_ui.py",),
    "chrome.py": ("test_window_workflow_state.py",),
    "dataset_loading.py": ("test_data_page_ui.py", "test_window_workflow_state.py"),
    "icons.py": ("test_icons.py",),
    "inspect_page.py": ("test_measure_page_ui.py", "test_metrics_math.py"),
    "metrics_runtime.py": ("test_measure_page_ui.py", "test_metrics_math.py"),
    "metrics_state.py": ("test_metrics_state.py", "test_measure_page_ui.py"),
    "models.py": ("test_metrics_math.py",),
    "window.py": ("test_window_workflow_state.py", "test_icons.py"),
    "window_actions.py": ("test_measure_page_ui.py",),
}

SUITE_HELP = {
    "all": "every test module under tests/",
    "analysis": "analysis context, math, and analysis-page behavior",
    "changed": "git-changed tests plus mapped source tests and a smoke set",
    "core": "everything except the UI-focused suite",
    "data": "dataset loading, metadata, session, and eBUS flows",
    "fast": "default local regression set with light Qt coverage",
    "ui": "Qt-heavy UI, density, and page layout regressions",
}


def _all_test_files() -> list[Path]:
    """Return all test files in a stable order."""

    return sorted(TESTS_DIR.glob("test_*.py"))


def _matches_any(path: Path, patterns: tuple[str, ...]) -> bool:
    """Return whether the file name matches any provided shell pattern."""

    return any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)


def _find_tests_matching_patterns(*patterns: str) -> list[Path]:
    """Return stable test files matching one or more filename patterns."""

    return [
        path
        for path in _all_test_files()
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)
    ]


def _git_changed_paths() -> list[Path]:
    """Return repo paths reported as changed by git status."""

    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []

    changed: list[Path] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            continue
        payload = line[3:]
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        if not payload:
            continue
        changed.append((REPO_ROOT / payload).resolve(strict=False))
    return changed


def _tests_for_changed_path(path: Path) -> list[Path]:
    """Return direct and heuristic test matches for one changed repo path."""

    try:
        relative = path.resolve(strict=False).relative_to(REPO_ROOT)
    except ValueError:
        return []

    if relative.parts and relative.parts[0] == "tests" and path.name.startswith("test_"):
        return [path.resolve(strict=False)]

    selected: list[Path] = []
    stem = path.stem
    selected.extend(
        _find_tests_matching_patterns(
            f"test_{stem}.py",
            f"test_{stem}_*.py",
            f"test_*_{stem}.py",
        ),
    )
    selected.extend(
        TESTS_DIR / name
        for name in SOURCE_TEST_MAP.get(path.name, ())
    )

    if relative.parts and relative.parts[0] == "framelab":
        if "workflow" in relative.parts:
            selected.extend(
                TESTS_DIR / name
                for name in (
                    "test_workflow_state.py",
                    "test_workflow_selection_dialog.py",
                    "test_window_workflow_state.py",
                )
            )
        elif "main_window" in relative.parts:
            if path.name in {"inspect_page.py", "metrics_runtime.py", "window_actions.py"}:
                selected.extend(
                    TESTS_DIR / name
                    for name in ("test_measure_page_ui.py", "test_metrics_math.py")
                )
            elif path.name in {"data_page.py", "dataset_loading.py"}:
                selected.extend(
                    TESTS_DIR / name
                    for name in ("test_data_page_ui.py", "test_window_workflow_state.py")
                )
            elif path.name == "analysis.py":
                selected.append(TESTS_DIR / "test_analysis_page_ui.py")

    return [
        candidate.resolve(strict=False)
        for candidate in selected
        if candidate.is_file()
    ]


def _files_for_changed_suite() -> list[Path]:
    """Return one quick regression set based on current git changes."""

    selected: list[Path] = []
    for changed_path in _git_changed_paths():
        selected.extend(_tests_for_changed_path(changed_path))
    selected.extend(_find_tests_matching_patterns(*FAST_SMOKE_PATTERNS))
    if not selected:
        selected.extend(_files_for_suite("fast"))
    return _dedupe(selected)


def _files_for_suite(name: str) -> list[Path]:
    """Resolve one named suite to concrete test files."""

    files = _all_test_files()
    if name == "all":
        return files
    if name == "fast":
        return [path for path in files if _matches_any(path, FAST_PATTERNS)]
    if name == "changed":
        return _files_for_changed_suite()
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
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def _selected_files(args: argparse.Namespace) -> list[Path]:
    """Resolve the effective file selection from CLI arguments."""

    selected: list[Path] = []
    if not args.suite and not args.pattern and not args.targets:
        args.suite = ["fast"]

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
    parser.add_argument(
        "--serial",
        action="store_true",
        help="Force a serial pytest run even when pytest-xdist is available.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="Explicit pytest-xdist worker count. Omit to use auto when parallelism is enabled.",
    )
    parser.add_argument(
        "--profile-slow",
        action="store_true",
        help="Report the slowest test durations after the run.",
    )
    return parser


def _pytest_available() -> bool:
    """Return whether pytest can be imported in the active environment."""

    return importlib.util.find_spec("pytest") is not None


def _xdist_available() -> bool:
    """Return whether pytest-xdist is importable in the active environment."""

    return importlib.util.find_spec("xdist") is not None


def _build_pytest_command(files: list[Path], args: argparse.Namespace) -> list[str]:
    """Build the concrete pytest command for the requested run."""

    cmd = [sys.executable, "-m", "pytest"]
    if args.verbose:
        cmd.append("-v")
    if args.failfast:
        cmd.append("-x")
    if args.profile_slow:
        cmd.extend(["--durations=20", "--durations-min=1.0"])

    can_parallelize = (
        not args.serial
        and len(files) > 1
        and _xdist_available()
    )
    if can_parallelize:
        workers = "auto" if args.jobs is None else str(max(1, int(args.jobs)))
        if workers != "1":
            cmd.extend(["-n", workers, "--dist", "loadfile"])

    cmd.extend(str(path) for path in files)
    return cmd


def _run_pytest(files: list[Path], args: argparse.Namespace) -> int:
    """Run the selected files through pytest."""

    completed = subprocess.run(
        _build_pytest_command(files, args),
        cwd=REPO_ROOT,
        check=False,
    )
    return int(completed.returncode)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    parser = _build_parser()
    args = parser.parse_args(argv)

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
