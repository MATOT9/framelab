from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


pytestmark = [pytest.mark.fast, pytest.mark.core]


def _load_runner_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "tests.py"
    spec = importlib.util.spec_from_file_location("framelab_test_runner", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_defaults_to_fast_suite(monkeypatch) -> None:
    runner = _load_runner_module()
    files = [
        runner.TESTS_DIR / "test_metrics_state.py",
        runner.TESTS_DIR / "test_plugin_registry.py",
        runner.TESTS_DIR / "test_analysis_page_ui.py",
    ]
    monkeypatch.setattr(runner, "_all_test_files", lambda: files)

    args = runner._build_parser().parse_args([])
    selected = runner._selected_files(args)

    assert [path.name for path in selected] == [
        "test_metrics_state.py",
        "test_plugin_registry.py",
    ]


def test_changed_suite_includes_mapped_tests_and_smoke(monkeypatch) -> None:
    runner = _load_runner_module()
    files = [
        runner.TESTS_DIR / "test_icons.py",
        runner.TESTS_DIR / "test_metrics_state.py",
        runner.TESTS_DIR / "test_plugin_registry.py",
        runner.TESTS_DIR / "test_ui_settings.py",
    ]
    monkeypatch.setattr(runner, "_all_test_files", lambda: files)
    monkeypatch.setattr(
        runner,
        "_git_changed_paths",
        lambda: [runner.REPO_ROOT / "framelab" / "icons.py"],
    )

    args = runner._build_parser().parse_args(["--suite", "changed"])
    selected = runner._selected_files(args)

    assert [path.name for path in selected] == [
        "test_icons.py",
        "test_metrics_state.py",
        "test_plugin_registry.py",
        "test_ui_settings.py",
    ]


def test_runner_builds_xdist_command_for_multi_file_run(monkeypatch) -> None:
    runner = _load_runner_module()
    monkeypatch.setattr(runner, "_xdist_available", lambda: True)
    args = runner._build_parser().parse_args(["--profile-slow"])
    files = [
        runner.TESTS_DIR / "test_metrics_state.py",
        runner.TESTS_DIR / "test_plugin_registry.py",
    ]

    cmd = runner._build_pytest_command(files, args)

    assert "-n" in cmd
    assert "--dist" in cmd
    assert "--durations=20" in cmd


def test_runner_falls_back_to_serial_when_xdist_is_unavailable(monkeypatch) -> None:
    runner = _load_runner_module()
    monkeypatch.setattr(runner, "_xdist_available", lambda: False)
    args = runner._build_parser().parse_args(["--jobs", "4"])
    files = [
        runner.TESTS_DIR / "test_metrics_state.py",
        runner.TESTS_DIR / "test_plugin_registry.py",
    ]

    cmd = runner._build_pytest_command(files, args)

    assert "-n" not in cmd
    assert "--dist" not in cmd
