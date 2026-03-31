from __future__ import annotations

from pathlib import Path

import pytest

from framelab.native import build_helper


pytestmark = [pytest.mark.core]


def test_build_plan_reports_missing_cmake(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(build_helper, "find_cmake_executable", lambda: None)

    with pytest.raises(RuntimeError, match="CMake"):
        build_helper.build_plan(repo_root=tmp_path)


def test_build_plan_forwards_active_python_and_output_dir(tmp_path: Path) -> None:
    plan = build_helper.build_plan(
        repo_root=tmp_path,
        python_executable="C:\\Python\\python.exe",
        build_dir=tmp_path / "native-build",
        output_dir=tmp_path / "out",
        cmake_executable="cmake",
    )

    configure_cmd = plan.configure_command()

    assert configure_cmd[:5] == [
        "cmake",
        "-S",
        str(tmp_path / "native"),
        "-B",
        str(tmp_path / "native-build"),
    ]
    assert "-DFRAMELAB_BUILD_PYTHON_MODULE=ON" in configure_cmd
    assert "-DPython3_EXECUTABLE=C:\\Python\\python.exe" in configure_cmd
    assert f"-DFRAMELAB_PYTHON_OUTPUT_DIR={tmp_path / 'out'}" in configure_cmd
    assert "-DCMAKE_BUILD_TYPE=Release" in configure_cmd


def test_build_commands_match_expected_cross_platform_shape(tmp_path: Path) -> None:
    plan = build_helper.build_plan(
        repo_root=tmp_path,
        python_executable="/usr/bin/python3",
        build_dir=tmp_path / "build",
        output_dir=tmp_path / "out",
        build_type="RelWithDebInfo",
        cmake_executable="cmake",
    )

    assert plan.build_command() == [
        "cmake",
        "--build",
        str(tmp_path / "build"),
        "--config",
        "RelWithDebInfo",
        "--parallel",
    ]


def test_build_plan_supports_cross_compile_toolchain_and_python_artifacts(
    tmp_path: Path,
) -> None:
    toolchain = tmp_path / "native" / "cmake" / "toolchains" / "mingw.cmake"
    toolchain.parent.mkdir(parents=True, exist_ok=True)
    toolchain.write_text("# toolchain\n", encoding="utf-8")

    plan = build_helper.build_plan(
        repo_root=tmp_path,
        build_dir=tmp_path / "build-win",
        output_dir=tmp_path / "out-win",
        cmake_executable="cmake",
        target_system="windows",
        toolchain_file=toolchain,
        python_include_dir=tmp_path / "py-win" / "include",
        python_numpy_include_dir=tmp_path / "py-win" / "numpy",
        python_library=tmp_path / "py-win" / "libs" / "libpython312.a",
    )

    configure_cmd = plan.configure_command()

    assert f"-DFRAMELAB_TARGET_SYSTEM=windows" in configure_cmd
    assert f"-DCMAKE_TOOLCHAIN_FILE={toolchain.resolve()}" in configure_cmd
    assert (
        f"-DFRAMELAB_PYTHON_INCLUDE_DIR={(tmp_path / 'py-win' / 'include').resolve()}"
        in configure_cmd
    )
    assert (
        f"-DFRAMELAB_PYTHON_NUMPY_INCLUDE_DIR={(tmp_path / 'py-win' / 'numpy').resolve()}"
        in configure_cmd
    )
    assert (
        f"-DFRAMELAB_PYTHON_LIBRARY={(tmp_path / 'py-win' / 'libs' / 'libpython312.a').resolve()}"
        in configure_cmd
    )


def test_run_build_executes_configure_then_build(tmp_path: Path) -> None:
    plan = build_helper.build_plan(
        repo_root=tmp_path,
        build_dir=tmp_path / "build",
        output_dir=tmp_path / "out",
        cmake_executable="cmake",
    )
    commands: list[list[str]] = []

    def _runner(command, check):
        assert check is True
        commands.append(list(command))
        return 0

    assert build_helper.run_build(plan, runner=_runner) == 0
    assert commands == [plan.configure_command(), plan.build_command()]


def test_run_build_removes_existing_native_extension_output(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    stale_output = output_dir / "_native.pyd"
    stale_output.write_bytes(b"old-binary")
    plan = build_helper.build_plan(
        repo_root=tmp_path,
        build_dir=tmp_path / "build",
        output_dir=output_dir,
        cmake_executable="cmake",
    )
    commands: list[list[str]] = []

    def _runner(command, check):
        assert check is True
        commands.append(list(command))
        return 0

    assert build_helper.run_build(plan, runner=_runner) == 0
    assert not stale_output.exists()
    assert commands == [plan.configure_command(), plan.build_command()]


def test_run_build_reports_locked_native_extension_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)
    locked_output = output_dir / "_native.pyd"
    locked_output.write_bytes(b"locked")
    plan = build_helper.build_plan(
        repo_root=tmp_path,
        build_dir=tmp_path / "build",
        output_dir=output_dir,
        cmake_executable="cmake",
    )
    original_unlink = Path.unlink

    def _unlink(self, *args, **kwargs):
        if self.resolve() == locked_output.resolve():
            raise PermissionError("locked")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _unlink)

    with pytest.raises(RuntimeError, match="Could not remove the existing native extension output"):
        build_helper.run_build(plan, runner=lambda command, check: 0)


def test_main_reports_missing_cmake_and_returns_nonzero(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setattr(build_helper, "find_cmake_executable", lambda: None)

    result = build_helper.main(["--repo-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert result == 1
    assert "CMake was not found on PATH" in captured.err
