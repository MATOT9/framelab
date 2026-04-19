from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

import tools.build_nuitka_app as build_nuitka_app


pytestmark = [pytest.mark.core]


def _host_target() -> str:
    return "windows" if sys.platform == "win32" else "linux"


def _safe_toolchain(python_executable: str = sys.executable) -> build_nuitka_app.NuitkaToolchainInfo:
    return build_nuitka_app.NuitkaToolchainInfo(
        python_executable=python_executable,
        python_version=(3, 13, 7),
        nuitka_version="4.0.8",
    )


def _write_minimal_nuitka_repo(tmp_path: Path) -> tuple[Path, Path]:
    launcher_path = tmp_path / "launcher.py"
    launcher_path.write_text("print('FrameLab')\n", encoding="utf-8")

    assets_dir = tmp_path / "framelab" / "assets"
    help_dir = assets_dir / "help"
    plugins_dir = tmp_path / "framelab" / "plugins" / "data"
    help_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir.mkdir(parents=True, exist_ok=True)

    (assets_dir / "LabReport.mplstyle").write_text("axes.facecolor: black\n", encoding="utf-8")
    (assets_dir / "framelab_splash.png").write_bytes(b"png")
    (assets_dir / "acquisition_field_mapping.default.json").write_text("{}", encoding="utf-8")
    (assets_dir / "ebus_parameter_catalog.default.json").write_text("{}", encoding="utf-8")
    (assets_dir / "app_icon.png").write_bytes(b"png")
    (assets_dir / "app_icon.ico").write_bytes(b"ico")
    (help_dir / "index.html").write_text("<html></html>\n", encoding="utf-8")

    manifest_path = plugins_dir / "sample.plugin.json"
    manifest_path.write_text("{}", encoding="utf-8")

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    config_path = tools_dir / "nuitka_build.toml"
    config_path.write_text(
        """
[build]
main_script = "launcher.py"
output_root = "build/nuitka"
product_name = "FrameLab"
company_name = "FrameLab"
enable_plugins = ["pyside6"]

[include]
data_files = [
  "framelab/assets/LabReport.mplstyle",
  "framelab/assets/framelab_splash.png",
  "framelab/assets/acquisition_field_mapping.default.json",
  "framelab/assets/ebus_parameter_catalog.default.json",
]
data_dirs = ["framelab/assets/help"]
icon_globs = ["framelab/assets/app_icon.*"]
module_includes = ["framelab.native._native"]

[targets.linux]
output_filename = "FrameLab.bin"
folder_name = "FrameLab"
icon_path = "framelab/assets/app_icon.png"

[targets.windows]
output_filename = "FrameLab.exe"
folder_name = "FrameLab"
icon_path = "framelab/assets/app_icon.ico"
windows_console_mode = "disable"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config_path, manifest_path


def test_load_build_config_reads_target_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "nuitka.toml"
    config_path.write_text(
        """
[build]
product_name = "FrameLab"
company_name = "FrameLab"
enable_plugins = ["pyside6"]

[include]
data_files = []
data_dirs = []
icon_globs = []
module_includes = []

[targets.linux]
output_filename = "FrameLab.bin"
folder_name = "FrameLab"

[targets.windows]
output_filename = "FrameLab.exe"
folder_name = "FrameLab"
icon_path = "framelab/assets/app_icon.ico"
windows_console_mode = "disable"
extra_args = ["--clang"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = build_nuitka_app.load_build_config(
        config_path,
        repo_root=tmp_path,
    )

    assert config.product_name == "FrameLab"
    assert config.enable_plugins == ("pyside6",)
    assert config.targets["windows"].windows_console_mode == "disable"
    assert config.targets["windows"].extra_args == ("--clang",)


def test_discover_plugin_entrypoint_modules_includes_manifest_entrypoints() -> None:
    modules = set(build_nuitka_app.discover_plugin_entrypoint_modules())

    assert "framelab.plugins.measure.background_correction" in modules
    assert "framelab.plugins.data.session_manager" in modules


def test_required_data_inclusions_cover_expected_runtime_assets() -> None:
    config = build_nuitka_app.load_build_config()
    inclusions = {
        inclusion.target
        for inclusion in build_nuitka_app.required_data_inclusions(
            build_nuitka_app.REPO_ROOT,
            config,
        )
    }

    assert "framelab/assets/help" in inclusions
    assert "framelab/assets/LabReport.mplstyle" in inclusions
    assert "framelab/assets/framelab_splash.png" in inclusions
    assert "framelab/plugins/measure/background_correction.plugin.json" in inclusions


def test_resolve_target_rejects_cross_platform_windows_request() -> None:
    with pytest.raises(RuntimeError, match="Linux-to-Windows"):
        build_nuitka_app.resolve_target("windows", host_platform="linux")


def test_validate_nuitka_toolchain_rejects_known_bad_python_314_combo() -> None:
    with pytest.raises(RuntimeError, match="known-bad for FrameLab PySide6 standalone builds"):
        build_nuitka_app.validate_nuitka_toolchain(
            build_nuitka_app.NuitkaToolchainInfo(
                python_executable=sys.executable,
                python_version=(3, 14, 0),
                nuitka_version="4.0.8",
            ),
        )


def test_validate_host_build_requirements_requires_patchelf_on_linux(monkeypatch) -> None:
    monkeypatch.setattr(build_nuitka_app.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="patchelf"):
        build_nuitka_app.validate_host_build_requirements("linux")


def test_build_plan_marks_missing_native_backend_for_build(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path, manifest_path = _write_minimal_nuitka_repo(tmp_path)
    target = _host_target()
    fake_manifest = SimpleNamespace(
        entrypoint_module="framelab.plugins.data.sample",
        manifest_path=manifest_path,
    )
    monkeypatch.setattr(
        build_nuitka_app,
        "discover_plugin_manifests",
        lambda: [fake_manifest],
    )
    monkeypatch.setattr(
        build_nuitka_app,
        "probe_toolchain",
        lambda python_executable=None: _safe_toolchain(
            str(python_executable or sys.executable),
        ),
    )

    plan = build_nuitka_app.build_plan(
        target=target,
        config_path=config_path,
        repo_root=tmp_path,
        python_executable=sys.executable,
    )

    assert plan.should_build_native is True
    assert plan.output_dir == tmp_path / "build" / "nuitka" / target
    assert "--include-module=framelab.plugins.data.sample" in plan.nuitka_command
    assert "--include-module=framelab.native._native" in plan.nuitka_command
    assert (
        f"--include-data-files={manifest_path.resolve()}=framelab/plugins/data/sample.plugin.json"
        in plan.nuitka_command
    )
    assert (
        f"--output-dir={tmp_path / 'build' / 'nuitka' / target}"
        in plan.nuitka_command
    )


def test_run_build_executes_native_then_nuitka(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path, manifest_path = _write_minimal_nuitka_repo(tmp_path)
    target = _host_target()
    fake_manifest = SimpleNamespace(
        entrypoint_module="framelab.plugins.data.sample",
        manifest_path=manifest_path,
    )
    monkeypatch.setattr(
        build_nuitka_app,
        "discover_plugin_manifests",
        lambda: [fake_manifest],
    )
    monkeypatch.setattr(
        build_nuitka_app,
        "probe_toolchain",
        lambda python_executable=None: _safe_toolchain(
            str(python_executable or sys.executable),
        ),
    )
    plan = build_nuitka_app.build_plan(
        target=target,
        config_path=config_path,
        repo_root=tmp_path,
        python_executable=sys.executable,
    )

    events: list[tuple[str, object]] = []

    def _native_plan_builder(**kwargs):
        events.append(("native-plan", dict(kwargs)))
        return "native-plan"

    def _native_runner(plan_obj):
        events.append(("native-run", plan_obj))
        return 0

    def _runner(command, check, cwd):
        events.append(
            (
                "nuitka-run",
                (
                    list(command),
                    check,
                    cwd,
                    os.environ.get("PYTHON_BASIC_REPL"),
                    os.environ.get("PYTHONPATH"),
                ),
            ),
        )
        return 0

    assert (
        build_nuitka_app.run_build(
            plan,
            runner=_runner,
            native_plan_builder=_native_plan_builder,
            native_runner=_native_runner,
        )
        == 0
    )
    assert events[0] == (
        "native-plan",
        {
            "repo_root": tmp_path,
            "python_executable": sys.executable,
            "build_type": "Release",
        },
    )
    assert events[1] == ("native-run", "native-plan")
    assert events[2][0] == "nuitka-run"
    assert events[2][1][3] == "1"
    assert str(build_nuitka_app.NUITKA_SUBPROCESS_PYTHONPATHS[0]) in events[2][1][4]


def test_run_build_rejects_missing_native_backend_when_skipped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path, manifest_path = _write_minimal_nuitka_repo(tmp_path)
    target = _host_target()
    fake_manifest = SimpleNamespace(
        entrypoint_module="framelab.plugins.data.sample",
        manifest_path=manifest_path,
    )
    monkeypatch.setattr(
        build_nuitka_app,
        "discover_plugin_manifests",
        lambda: [fake_manifest],
    )
    monkeypatch.setattr(
        build_nuitka_app,
        "probe_toolchain",
        lambda python_executable=None: _safe_toolchain(
            str(python_executable or sys.executable),
        ),
    )
    plan = build_nuitka_app.build_plan(
        target=target,
        config_path=config_path,
        repo_root=tmp_path,
    )

    with pytest.raises(RuntimeError, match="native backend is missing"):
        build_nuitka_app.run_build(
            plan,
            skip_native_build=True,
            runner=lambda command, check, cwd: 0,
        )
