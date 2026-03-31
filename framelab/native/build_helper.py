"""Helpers for configuring and building the native extension module."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Sequence


DEFAULT_BUILD_TYPE = "Release"
DEFAULT_ENABLE_IPO = sys.platform != "win32"
EXTENSION_OUTPUT_GLOBS = ("_native*.pyd", "_native*.so")
_VALID_TARGET_SYSTEMS = {"native", "linux", "windows"}


@dataclass(frozen=True, slots=True)
class NativeBuildPlan:
    """Concrete configure/build commands for the native extension."""

    cmake_executable: str
    native_dir: Path
    build_dir: Path
    output_dir: Path
    python_executable: str
    build_type: str = DEFAULT_BUILD_TYPE
    enable_ipo: bool = DEFAULT_ENABLE_IPO
    target_system: str = "native"
    generator: str | None = None
    platform: str | None = None
    toolchain_file: Path | None = None
    python_include_dir: Path | None = None
    python_library: Path | None = None
    python_numpy_include_dir: Path | None = None

    def configure_command(self) -> list[str]:
        """Return the CMake configure command."""

        command = [self.cmake_executable]
        if self.generator:
            command.extend(["-G", self.generator])
        if self.platform:
            command.extend(["-A", self.platform])
        command.extend(
            [
                "-S",
                str(self.native_dir),
                "-B",
                str(self.build_dir),
                "-DFRAMELAB_BUILD_PYTHON_MODULE=ON",
                f"-DFRAMELAB_ENABLE_IPO={'ON' if self.enable_ipo else 'OFF'}",
                f"-DPython3_EXECUTABLE={self.python_executable}",
                f"-DFRAMELAB_PYTHON_OUTPUT_DIR={self.output_dir}",
                f"-DCMAKE_BUILD_TYPE={self.build_type}",
            ]
        )
        if self.target_system != "native":
            command.append(f"-DFRAMELAB_TARGET_SYSTEM={self.target_system}")
        if self.toolchain_file is not None:
            command.append(f"-DCMAKE_TOOLCHAIN_FILE={self.toolchain_file}")
        if self.python_include_dir is not None:
            command.append(f"-DFRAMELAB_PYTHON_INCLUDE_DIR={self.python_include_dir}")
        if self.python_library is not None:
            command.append(f"-DFRAMELAB_PYTHON_LIBRARY={self.python_library}")
        if self.python_numpy_include_dir is not None:
            command.append(
                f"-DFRAMELAB_PYTHON_NUMPY_INCLUDE_DIR={self.python_numpy_include_dir}"
            )
        return command

    def build_command(self) -> list[str]:
        """Return the CMake build command."""

        return [
            self.cmake_executable,
            "--build",
            str(self.build_dir),
            "--config",
            self.build_type,
            "--parallel",
        ]


def repo_root_from_file(file_path: str | Path) -> Path:
    """Return the repository root relative to one helper module path."""

    return Path(file_path).resolve().parents[2]


def find_cmake_executable() -> str | None:
    """Return the discovered CMake executable, if any."""

    return shutil.which("cmake")


def default_cross_toolchain_file(
    *,
    repo_root: str | Path | None = None,
    target_system: str = "native",
) -> Path | None:
    """Return the default bundled toolchain file for a cross target, if any."""

    normalized_target = str(target_system or "native").strip().lower()
    if normalized_target != "windows":
        return None
    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else repo_root_from_file(__file__)
    )
    candidate = root / "native" / "cmake" / "toolchains" / "mingw-w64-x86_64.cmake"
    return candidate if candidate.exists() else None


def build_plan(
    *,
    repo_root: str | Path | None = None,
    python_executable: str | None = None,
    build_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    build_type: str = DEFAULT_BUILD_TYPE,
    enable_ipo: bool = DEFAULT_ENABLE_IPO,
    cmake_executable: str | None = None,
    target_system: str = "native",
    generator: str | None = None,
    platform: str | None = None,
    toolchain_file: str | Path | None = None,
    python_include_dir: str | Path | None = None,
    python_library: str | Path | None = None,
    python_numpy_include_dir: str | Path | None = None,
) -> NativeBuildPlan:
    """Return a fully resolved native-extension build plan."""

    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else repo_root_from_file(__file__)
    )
    native_dir = root / "native"
    resolved_build_dir = (
        Path(build_dir).resolve()
        if build_dir is not None
        else native_dir / "build"
    )
    resolved_output_dir = (
        Path(output_dir).resolve()
        if output_dir is not None
        else root / "framelab" / "native"
    )
    normalized_target_system = str(target_system or "native").strip().lower()
    if normalized_target_system not in _VALID_TARGET_SYSTEMS:
        raise RuntimeError(
            "target_system must be one of: native, linux, windows",
        )
    resolved_toolchain_file = (
        Path(toolchain_file).resolve()
        if toolchain_file is not None
        else (
            default_cross_toolchain_file(
                repo_root=root,
                target_system=normalized_target_system,
            )
            if normalized_target_system != "native" and sys.platform != "win32"
            else None
        )
    )
    cmake_path = cmake_executable or find_cmake_executable()
    if not cmake_path:
        raise RuntimeError(
            "CMake was not found on PATH. Install CMake and ensure `cmake` is "
            "available before building the FrameLab native backend.",
        )
    if (python_include_dir is None) != (python_numpy_include_dir is None):
        raise RuntimeError(
            "Provide both --python-include-dir and --python-numpy-include-dir "
            "together when overriding target Python artifacts.",
        )
    if resolved_toolchain_file is not None and not resolved_toolchain_file.exists():
        raise RuntimeError(
            f"Requested toolchain file does not exist: {resolved_toolchain_file}",
        )
    return NativeBuildPlan(
        cmake_executable=cmake_path,
        native_dir=native_dir,
        build_dir=resolved_build_dir,
        output_dir=resolved_output_dir,
        python_executable=python_executable or sys.executable,
        build_type=str(build_type or DEFAULT_BUILD_TYPE),
        enable_ipo=bool(enable_ipo),
        target_system=normalized_target_system,
        generator=(str(generator).strip() or None) if generator is not None else None,
        platform=(str(platform).strip() or None) if platform is not None else None,
        toolchain_file=resolved_toolchain_file,
        python_include_dir=(
            Path(python_include_dir).resolve()
            if python_include_dir is not None
            else None
        ),
        python_library=(
            Path(python_library).resolve()
            if python_library is not None
            else None
        ),
        python_numpy_include_dir=(
            Path(python_numpy_include_dir).resolve()
            if python_numpy_include_dir is not None
            else None
        ),
    )


def _extension_output_candidates(output_dir: Path) -> list[Path]:
    """Return built-extension candidates currently present in one output dir."""

    seen: set[Path] = set()
    candidates: list[Path] = []
    for pattern in EXTENSION_OUTPUT_GLOBS:
        for path in sorted(output_dir.glob(pattern)):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(path)
    return candidates


def _remove_existing_extension_outputs(output_dir: Path) -> None:
    """Remove stale extension outputs before rebuilding in-place."""

    output_dir.mkdir(parents=True, exist_ok=True)
    for path in _extension_output_candidates(output_dir):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise RuntimeError(
                "Could not remove the existing native extension output "
                f"`{path}` before rebuild. It is likely loaded by a running "
                "FrameLab or python.exe process. Close those processes or "
                "build to a different `--output-dir` and try again.",
            ) from exc


def run_build(
    plan: NativeBuildPlan,
    *,
    runner=subprocess.run,
) -> int:
    """Execute one native-extension build plan."""

    _remove_existing_extension_outputs(plan.output_dir)
    runner(plan.configure_command(), check=True)
    runner(plan.build_command(), check=True)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure and build the FrameLab native extension module.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root that contains the `native/` directory.",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=None,
        help="Build directory to pass to CMake.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory where the compiled extension should be written.",
    )
    parser.add_argument(
        "--build-type",
        default=DEFAULT_BUILD_TYPE,
        help="CMake build configuration to produce (default: Release).",
    )
    parser.add_argument(
        "--enable-ipo",
        action="store_true",
        default=DEFAULT_ENABLE_IPO,
        help=(
            "Enable IPO/LTO for the native build. Disabled by default on "
            "Windows for conservative extension builds."
        ),
    )
    parser.add_argument(
        "--disable-ipo",
        action="store_false",
        dest="enable_ipo",
        help="Disable IPO/LTO for the native build.",
    )
    parser.add_argument(
        "--python",
        dest="python_executable",
        default=sys.executable,
        help="Python interpreter CMake should bind the extension against.",
    )
    parser.add_argument(
        "--target-system",
        choices=sorted(_VALID_TARGET_SYSTEMS),
        default="native",
        help="Target system for the native build (default: native).",
    )
    parser.add_argument(
        "--generator",
        default=None,
        help="Optional CMake generator name, for example 'Ninja' or 'Visual Studio 17 2022'.",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="Optional CMake generator platform value passed with -A.",
    )
    parser.add_argument(
        "--toolchain-file",
        type=Path,
        default=None,
        help="Optional CMake toolchain file for cross compilation.",
    )
    parser.add_argument(
        "--python-include-dir",
        type=Path,
        default=None,
        help="Optional target Python include directory for explicit/native-cross artifact selection.",
    )
    parser.add_argument(
        "--python-library",
        type=Path,
        default=None,
        help="Optional target Python library or import library path.",
    )
    parser.add_argument(
        "--python-numpy-include-dir",
        type=Path,
        default=None,
        help="Optional target NumPy include directory for explicit/native-cross artifact selection.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for building the native extension module."""

    args = _parser().parse_args(argv)
    try:
        plan = build_plan(
            repo_root=args.repo_root,
            python_executable=args.python_executable,
            build_dir=args.build_dir,
            output_dir=args.output_dir,
            build_type=args.build_type,
            enable_ipo=args.enable_ipo,
            target_system=args.target_system,
            generator=args.generator,
            platform=args.platform,
            toolchain_file=args.toolchain_file,
            python_include_dir=args.python_include_dir,
            python_library=args.python_library,
            python_numpy_include_dir=args.python_numpy_include_dir,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        return run_build(plan)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(
            f"Native backend build failed with exit code {exc.returncode}.",
            file=sys.stderr,
        )
        return int(exc.returncode or 1)
