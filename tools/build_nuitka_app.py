"""Build FrameLab as a standalone Nuitka application directory."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import importlib.metadata
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from framelab.native import build_helper as native_build_helper
from framelab.plugins import discover_plugin_manifests


DEFAULT_CONFIG_PATH = REPO_ROOT / "tools" / "nuitka_build.toml"
SUPPORTED_TARGETS = ("linux", "windows")
WINDOWS_CONSOLE_MODES = {"force", "disable", "attach", "hide"}
NATIVE_EXTENSION_GLOBS = {
    "linux": ("_native*.so",),
    "windows": ("_native*.pyd",),
}
KNOWN_BAD_PYSIDE6_TOOLCHAIN_MESSAGE = (
    "Selected Nuitka toolchain is known-bad for FrameLab PySide6 standalone "
    "builds: Python {python_version} with Nuitka {nuitka_version}. This "
    "combination crashes at runtime while connecting Qt signals from frozen "
    "code via PySide6-postLoad. Use Python 3.13 for release builds, or point "
    "the wrapper at a supported interpreter with --python."
)
NUITKA_SUBPROCESS_PYTHONPATHS = (
    Path(__file__).resolve().parent / "nuitka_shims",
)


@contextmanager
def _temporary_subprocess_env(*, python_basic_repl: str = "1"):
    """Temporarily export env vars for wrapper-spawned Python subprocesses."""

    previous_basic_repl = os.environ.get("PYTHON_BASIC_REPL")
    previous_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath_entries = [
        str(path)
        for path in NUITKA_SUBPROCESS_PYTHONPATHS
        if path.exists()
    ]

    os.environ["PYTHON_BASIC_REPL"] = python_basic_repl
    if pythonpath_entries:
        combined_entries = list(pythonpath_entries)
        if previous_pythonpath:
            combined_entries.append(previous_pythonpath)
        os.environ["PYTHONPATH"] = os.pathsep.join(combined_entries)
    try:
        yield
    finally:
        if previous_basic_repl is None:
            os.environ.pop("PYTHON_BASIC_REPL", None)
        else:
            os.environ["PYTHON_BASIC_REPL"] = previous_basic_repl

        if previous_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = previous_pythonpath


@dataclass(frozen=True, slots=True)
class NuitkaTargetConfig:
    """Target-specific Nuitka options."""

    output_filename: str
    folder_name: str
    icon_path: str | None = None
    windows_console_mode: str | None = None
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NuitkaBuildConfig:
    """Parsed repo-owned Nuitka wrapper configuration."""

    main_script: str
    output_root: str
    product_name: str
    company_name: str | None
    file_version: str | None
    enable_plugins: tuple[str, ...]
    include_qt_plugins: tuple[str, ...]
    noinclude_qt_plugins: tuple[str, ...]
    noinclude_qt_translations: bool
    nofollow_import_to: tuple[str, ...]
    include_distribution_metadata: tuple[str, ...]
    extra_args: tuple[str, ...]
    include_data_files: tuple[str, ...]
    include_data_dirs: tuple[str, ...]
    icon_globs: tuple[str, ...]
    module_includes: tuple[str, ...]
    smoke_source: str
    targets: dict[str, NuitkaTargetConfig]


@dataclass(frozen=True, slots=True)
class NuitkaToolchainInfo:
    """Resolved Python/Nuitka toolchain used for one build."""

    python_executable: str
    python_version: tuple[int, int, int]
    nuitka_version: str

    @property
    def python_version_text(self) -> str:
        return ".".join(str(part) for part in self.python_version)

    @property
    def summary(self) -> str:
        return (
            f"Python {self.python_version_text} "
            f"/ Nuitka {self.nuitka_version}"
        )


@dataclass(frozen=True, slots=True)
class DataInclusion:
    """One explicit non-code asset inclusion for Nuitka."""

    source: Path
    target: str
    kind: str

    def nuitka_arg(self) -> str:
        """Return the corresponding Nuitka command-line argument."""

        if self.kind == "dir":
            return f"--include-data-dir={self.source}={self.target}"
        return f"--include-data-files={self.source}={self.target}"


@dataclass(frozen=True, slots=True)
class NuitkaBuildPlan:
    """Resolved build inputs and command lines for one target."""

    repo_root: Path
    config_path: Path
    target: str
    toolchain: NuitkaToolchainInfo
    python_executable: str
    main_script: Path
    output_dir: Path
    output_folder_name: str
    output_filename: str
    dist_dir: Path
    should_build_native: bool
    native_extension_path: Path | None
    native_build_command: tuple[str, ...]
    plugin_entrypoint_modules: tuple[str, ...]
    data_inclusions: tuple[DataInclusion, ...]
    module_includes: tuple[str, ...]
    nuitka_command: tuple[str, ...]


def repo_root_from_file(file_path: str | Path) -> Path:
    """Return the repository root from one file path inside ``tools/``."""

    return Path(file_path).resolve().parents[1]


def _require_mapping(raw: object, *, key: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RuntimeError(f"Expected '{key}' to be a TOML table.")
    return dict(raw)


def _clean_optional_string(raw: object, *, key: str) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text


def _clean_string_list(raw: object, *, key: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise RuntimeError(f"Expected '{key}' to be a list of strings.")
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in raw:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return tuple(cleaned)


def _resolved_executable_path(command: str) -> Path | None:
    text = str(command).strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_absolute() or "/" in text:
        return candidate.resolve()
    located = shutil.which(text)
    return Path(located).resolve() if located else None


def _current_nuitka_version() -> str:
    for distribution_name in ("Nuitka", "nuitka"):
        try:
            return importlib.metadata.version(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            continue
    raise RuntimeError(
        "Nuitka is not installed for the selected Python interpreter.",
    )


def probe_toolchain(
    python_executable: str | None = None,
) -> NuitkaToolchainInfo:
    """Return Python/Nuitka version info for the selected interpreter."""

    python_cmd = str(python_executable or sys.executable).strip() or sys.executable
    current_path = _resolved_executable_path(sys.executable)
    selected_path = _resolved_executable_path(python_cmd)

    if current_path is not None and selected_path == current_path:
        return NuitkaToolchainInfo(
            python_executable=python_cmd,
            python_version=tuple(sys.version_info[:3]),
            nuitka_version=_current_nuitka_version(),
        )

    probe_code = """
import importlib.metadata
import json
import sys

for distribution_name in ("Nuitka", "nuitka"):
    try:
        nuitka_version = importlib.metadata.version(distribution_name)
        break
    except importlib.metadata.PackageNotFoundError:
        nuitka_version = None

if nuitka_version is None:
    raise SystemExit("Nuitka is not installed for the selected Python interpreter.")

print(
    json.dumps(
        {
            "python_version": list(sys.version_info[:3]),
            "nuitka_version": nuitka_version,
        }
    )
)
""".strip()
    try:
        with _temporary_subprocess_env():
            completed = subprocess.run(
                [python_cmd, "-c", probe_code],
                check=True,
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Selected Python interpreter does not exist or is not executable: {python_cmd}",
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = stderr or str(exc)
        raise RuntimeError(
            f"Failed to inspect the selected Python/Nuitka toolchain for '{python_cmd}': {detail}",
        ) from exc

    try:
        payload = json.loads((completed.stdout or "").strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse the selected toolchain info for '{python_cmd}'.",
        ) from exc

    python_version = tuple(int(part) for part in payload["python_version"])
    nuitka_version = str(payload["nuitka_version"]).strip()
    if len(python_version) != 3 or not nuitka_version:
        raise RuntimeError(
            f"Selected toolchain probe for '{python_cmd}' returned incomplete version data.",
        )
    return NuitkaToolchainInfo(
        python_executable=python_cmd,
        python_version=python_version,
        nuitka_version=nuitka_version,
    )


def validate_nuitka_toolchain(toolchain: NuitkaToolchainInfo) -> None:
    """Reject known-bad Python/Nuitka combos for FrameLab standalone builds."""

    if (
        toolchain.python_version[:2] >= (3, 14)
        and toolchain.nuitka_version.startswith("4.0.")
    ):
        raise RuntimeError(
            KNOWN_BAD_PYSIDE6_TOOLCHAIN_MESSAGE.format(
                python_version=toolchain.python_version_text,
                nuitka_version=toolchain.nuitka_version,
            ),
        )


def validate_host_build_requirements(target: str) -> None:
    """Check host-side tools that standalone packaging requires."""

    if target == "linux" and shutil.which("patchelf") is None:
        raise RuntimeError(
            "Linux standalone builds require 'patchelf' on PATH. "
            "Install it first, then rerun the Nuitka wrapper.",
        )


def load_build_config(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    *,
    repo_root: str | Path | None = None,
) -> NuitkaBuildConfig:
    """Load the repo-owned Nuitka wrapper configuration."""

    resolved_repo_root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else repo_root_from_file(__file__)
    )
    resolved_config_path = Path(config_path)
    if not resolved_config_path.is_absolute():
        resolved_config_path = resolved_repo_root / resolved_config_path
    resolved_config_path = resolved_config_path.resolve()
    if not resolved_config_path.exists():
        raise RuntimeError(
            f"Nuitka config file does not exist: {resolved_config_path}",
        )

    with resolved_config_path.open("rb") as handle:
        payload = tomllib.load(handle)

    build_table = _require_mapping(payload.get("build"), key="build")
    include_table = _require_mapping(payload.get("include"), key="include")
    targets_table = _require_mapping(payload.get("targets"), key="targets")

    product_name = (
        _clean_optional_string(build_table.get("product_name"), key="build.product_name")
        or "FrameLab"
    )

    targets: dict[str, NuitkaTargetConfig] = {}
    for target in SUPPORTED_TARGETS:
        target_table = _require_mapping(targets_table.get(target), key=f"targets.{target}")
        windows_console_mode = _clean_optional_string(
            target_table.get("windows_console_mode"),
            key=f"targets.{target}.windows_console_mode",
        )
        if windows_console_mode is not None and windows_console_mode not in WINDOWS_CONSOLE_MODES:
            supported = ", ".join(sorted(WINDOWS_CONSOLE_MODES))
            raise RuntimeError(
                f"Unsupported windows console mode '{windows_console_mode}'. "
                f"Expected one of: {supported}",
            )
        default_output_filename = (
            f"{product_name}.exe" if target == "windows" else f"{product_name}.bin"
        )
        targets[target] = NuitkaTargetConfig(
            output_filename=(
                _clean_optional_string(
                    target_table.get("output_filename"),
                    key=f"targets.{target}.output_filename",
                )
                or default_output_filename
            ),
            folder_name=(
                _clean_optional_string(
                    target_table.get("folder_name"),
                    key=f"targets.{target}.folder_name",
                )
                or product_name
            ),
            icon_path=_clean_optional_string(
                target_table.get("icon_path"),
                key=f"targets.{target}.icon_path",
            ),
            windows_console_mode=windows_console_mode,
            extra_args=_clean_string_list(
                target_table.get("extra_args"),
                key=f"targets.{target}.extra_args",
            ),
        )

    smoke_source = str(build_table.get("smoke_source", "print('FrameLab Nuitka smoke')"))
    smoke_source = smoke_source.strip() or "print('FrameLab Nuitka smoke')"

    return NuitkaBuildConfig(
        main_script=(
            _clean_optional_string(build_table.get("main_script"), key="build.main_script")
            or "launcher.py"
        ),
        output_root=(
            _clean_optional_string(build_table.get("output_root"), key="build.output_root")
            or "build/nuitka"
        ),
        product_name=product_name,
        company_name=_clean_optional_string(
            build_table.get("company_name"),
            key="build.company_name",
        ),
        file_version=_clean_optional_string(
            build_table.get("file_version"),
            key="build.file_version",
        ),
        enable_plugins=_clean_string_list(
            build_table.get("enable_plugins"),
            key="build.enable_plugins",
        ),
        include_qt_plugins=_clean_string_list(
            build_table.get("include_qt_plugins"),
            key="build.include_qt_plugins",
        ),
        noinclude_qt_plugins=_clean_string_list(
            build_table.get("noinclude_qt_plugins"),
            key="build.noinclude_qt_plugins",
        ),
        noinclude_qt_translations=bool(
            build_table.get("noinclude_qt_translations", False),
        ),
        nofollow_import_to=_clean_string_list(
            build_table.get("nofollow_import_to"),
            key="build.nofollow_import_to",
        ),
        include_distribution_metadata=_clean_string_list(
            build_table.get("include_distribution_metadata"),
            key="build.include_distribution_metadata",
        ),
        extra_args=_clean_string_list(
            build_table.get("extra_args"),
            key="build.extra_args",
        ),
        include_data_files=_clean_string_list(
            include_table.get("data_files"),
            key="include.data_files",
        ),
        include_data_dirs=_clean_string_list(
            include_table.get("data_dirs"),
            key="include.data_dirs",
        ),
        icon_globs=_clean_string_list(
            include_table.get("icon_globs"),
            key="include.icon_globs",
        ),
        module_includes=_clean_string_list(
            include_table.get("module_includes"),
            key="include.module_includes",
        ),
        smoke_source=smoke_source,
        targets=targets,
    )


def resolve_target(requested_target: str, *, host_platform: str | None = None) -> str:
    """Resolve the requested target to a supported host-native target."""

    platform_name = host_platform or sys.platform
    normalized = str(requested_target or "auto").strip().lower() or "auto"
    if normalized == "auto":
        if platform_name.startswith("linux"):
            return "linux"
        if platform_name == "win32":
            return "windows"
        raise RuntimeError(
            "FrameLab Nuitka packaging currently supports only Linux and Windows hosts.",
        )
    if normalized not in SUPPORTED_TARGETS:
        supported = ", ".join(("auto", *SUPPORTED_TARGETS))
        raise RuntimeError(f"Unsupported target '{normalized}'. Expected one of: {supported}")
    if normalized == "windows" and platform_name != "win32":
        raise RuntimeError(
            "Linux-to-Windows freezing is not supported in v1. Build the Windows app on Windows.",
        )
    if normalized == "linux" and not platform_name.startswith("linux"):
        raise RuntimeError(
            "Windows-to-Linux freezing is not supported in v1. Build the Linux app on Linux.",
        )
    return normalized


def _resolve_repo_path(repo_root: Path, raw_path: str) -> Path:
    path = Path(str(raw_path).strip())
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _repo_relative_target(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise RuntimeError(
            f"Expected path '{path}' to live under repository root '{repo_root}'.",
        ) from exc


def discover_plugin_entrypoint_modules() -> tuple[str, ...]:
    """Return unique plugin entrypoint modules from the manifest set."""

    modules = {
        str(manifest.entrypoint_module).strip()
        for manifest in discover_plugin_manifests()
        if str(manifest.entrypoint_module).strip()
    }
    return tuple(sorted(modules))


def resolve_native_extension_path(repo_root: Path, target: str) -> Path | None:
    """Return the compiled native extension path for one supported target."""

    native_dir = repo_root / "framelab" / "native"
    candidates: list[Path] = []
    for pattern in NATIVE_EXTENSION_GLOBS[target]:
        candidates.extend(sorted(native_dir.glob(pattern)))
    return candidates[0].resolve() if candidates else None


def required_data_inclusions(
    repo_root: str | Path,
    config: NuitkaBuildConfig,
) -> tuple[DataInclusion, ...]:
    """Return the explicit non-code assets the build must carry."""

    resolved_repo_root = Path(repo_root).resolve()
    inclusions: dict[str, DataInclusion] = {}

    def _add_file(path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_file():
            raise RuntimeError(f"Required Nuitka data file is missing: {resolved}")
        target = _repo_relative_target(resolved_repo_root, resolved)
        inclusions[target] = DataInclusion(resolved, target, "file")

    def _add_dir(path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_dir():
            raise RuntimeError(f"Required Nuitka data directory is missing: {resolved}")
        target = _repo_relative_target(resolved_repo_root, resolved)
        inclusions[target] = DataInclusion(resolved, target, "dir")

    for raw_file in config.include_data_files:
        _add_file(_resolve_repo_path(resolved_repo_root, raw_file))
    for raw_dir in config.include_data_dirs:
        _add_dir(_resolve_repo_path(resolved_repo_root, raw_dir))

    for raw_glob in config.icon_globs:
        matches = sorted(resolved_repo_root.glob(raw_glob))
        if not matches:
            raise RuntimeError(f"Nuitka icon glob matched no files: {raw_glob}")
        for path in matches:
            _add_file(path)

    for manifest in discover_plugin_manifests():
        _add_file(Path(manifest.manifest_path))

    return tuple(inclusions[target] for target in sorted(inclusions))


def build_plan(
    *,
    target: str = "auto",
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    python_executable: str | None = None,
    nuitka_extra_args: Sequence[str] = (),
    repo_root: str | Path | None = None,
) -> NuitkaBuildPlan:
    """Return a fully resolved standalone-build plan."""

    resolved_repo_root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else repo_root_from_file(__file__)
    )
    config = load_build_config(config_path, repo_root=resolved_repo_root)
    resolved_target = resolve_target(target)
    target_config = config.targets[resolved_target]

    main_script = _resolve_repo_path(resolved_repo_root, config.main_script)
    if not main_script.exists():
        raise RuntimeError(f"Main script does not exist: {main_script}")

    output_dir = _resolve_repo_path(
        resolved_repo_root,
        str(Path(config.output_root) / resolved_target),
    )
    dist_dir = output_dir / f"{target_config.folder_name}.dist"

    icon_path = (
        _resolve_repo_path(resolved_repo_root, target_config.icon_path)
        if target_config.icon_path
        else None
    )
    if icon_path is not None and not icon_path.exists():
        raise RuntimeError(f"Configured target icon does not exist: {icon_path}")

    plugin_entrypoint_modules = discover_plugin_entrypoint_modules()
    data_inclusions = required_data_inclusions(resolved_repo_root, config)
    native_extension_path = resolve_native_extension_path(resolved_repo_root, resolved_target)
    should_build_native = native_extension_path is None

    module_includes = tuple(
        sorted(
            {
                *config.module_includes,
                *plugin_entrypoint_modules,
            },
        ),
    )

    python_cmd = str(python_executable or sys.executable).strip() or sys.executable
    toolchain = probe_toolchain(python_cmd)
    command: list[str] = [
        python_cmd,
        "-m",
        "nuitka",
        "--mode=standalone",
        f"--output-dir={output_dir}",
        f"--output-folder-name={target_config.folder_name}",
        f"--output-filename={target_config.output_filename}",
        f"--product-name={config.product_name}",
    ]
    if config.company_name:
        command.append(f"--company-name={config.company_name}")
    if config.file_version:
        command.append(f"--file-version={config.file_version}")
    for plugin_name in config.enable_plugins:
        command.append(f"--enable-plugin={plugin_name}")
    for qt_plugin_name in config.include_qt_plugins:
        command.append(f"--include-qt-plugins={qt_plugin_name}")
    for qt_plugin_name in config.noinclude_qt_plugins:
        command.append(f"--noinclude-qt-plugins={qt_plugin_name}")
    if config.noinclude_qt_translations:
        command.append("--noinclude-qt-translations")
    for pattern in config.nofollow_import_to:
        command.append(f"--nofollow-import-to={pattern}")
    for distribution_name in config.include_distribution_metadata:
        command.append(f"--include-distribution-metadata={distribution_name}")
    if resolved_target == "windows" and target_config.windows_console_mode:
        command.append(
            f"--windows-console-mode={target_config.windows_console_mode}",
        )
    if resolved_target == "windows" and icon_path is not None:
        command.append(f"--windows-icon-from-ico={icon_path}")
    for inclusion in data_inclusions:
        command.append(inclusion.nuitka_arg())
    for module_name in module_includes:
        command.append(f"--include-module={module_name}")
    command.extend(config.extra_args)
    command.extend(target_config.extra_args)
    command.extend(str(arg).strip() for arg in nuitka_extra_args if str(arg).strip())
    command.append(str(main_script))

    native_build_command = (
        python_cmd,
        str(resolved_repo_root / "tools" / "build_native_backend.py"),
        "--build-type",
        "Release",
    )

    return NuitkaBuildPlan(
        repo_root=resolved_repo_root,
        config_path=_resolve_repo_path(resolved_repo_root, str(config_path)),
        target=resolved_target,
        toolchain=toolchain,
        python_executable=python_cmd,
        main_script=main_script,
        output_dir=output_dir,
        output_folder_name=target_config.folder_name,
        output_filename=target_config.output_filename,
        dist_dir=dist_dir,
        should_build_native=should_build_native,
        native_extension_path=native_extension_path,
        native_build_command=native_build_command,
        plugin_entrypoint_modules=plugin_entrypoint_modules,
        data_inclusions=data_inclusions,
        module_includes=module_includes,
        nuitka_command=tuple(command),
    )


def _format_plan(plan: NuitkaBuildPlan) -> str:
    """Return a readable preflight report for ``--check``."""

    lines = [
        f"Target: {plan.target}",
        f"Config: {plan.config_path}",
        f"Output root: {plan.output_dir}",
        f"Dist dir: {plan.dist_dir}",
        f"Main script: {plan.main_script}",
        f"Toolchain: {plan.toolchain.summary}",
    ]
    if plan.native_extension_path is not None:
        lines.append(f"Native backend: {plan.native_extension_path}")
    else:
        lines.append(
            "Native backend: missing, will build before Nuitka with "
            f"{shlex.join(plan.native_build_command)}",
        )
    lines.extend(
        [
            f"Plugin entrypoints: {len(plan.plugin_entrypoint_modules)}",
            f"Explicit data inclusions: {len(plan.data_inclusions)}",
            "Nuitka command:",
            shlex.join(plan.nuitka_command),
        ],
    )
    return "\n".join(lines)


def clean_output_dir(output_dir: str | Path) -> None:
    """Remove one target output directory when requested."""

    shutil.rmtree(Path(output_dir), ignore_errors=True)


def run_build(
    plan: NuitkaBuildPlan,
    *,
    skip_native_build: bool = False,
    runner=subprocess.run,
    native_plan_builder=native_build_helper.build_plan,
    native_runner=native_build_helper.run_build,
) -> int:
    """Execute one resolved Nuitka build plan."""

    validate_nuitka_toolchain(plan.toolchain)
    if plan.should_build_native:
        if skip_native_build:
            raise RuntimeError(
                "FrameLab native backend is missing and --skip-native-build was set. "
                "Build the native backend first or allow the wrapper to build it.",
            )
        native_plan = native_plan_builder(
            repo_root=plan.repo_root,
            python_executable=plan.python_executable,
            build_type="Release",
        )
        native_runner(native_plan)
    with _temporary_subprocess_env():
        runner(
            list(plan.nuitka_command),
            check=True,
            cwd=str(plan.repo_root),
        )
    return 0


def run_smoke_build(
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    python_executable: str | None = None,
    repo_root: str | Path | None = None,
    runner=subprocess.run,
) -> int:
    """Run a tiny standalone Nuitka compile as a fast toolchain smoke test."""

    resolved_repo_root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else repo_root_from_file(__file__)
    )
    config = load_build_config(config_path, repo_root=resolved_repo_root)
    python_cmd = str(python_executable or sys.executable).strip() or sys.executable
    validate_nuitka_toolchain(probe_toolchain(python_cmd))
    validate_host_build_requirements(resolve_target("auto"))

    with tempfile.TemporaryDirectory(prefix="framelab-nuitka-smoke-") as temp_root_text:
        temp_root = Path(temp_root_text)
        script_path = temp_root / "framelab_nuitka_smoke.py"
        output_dir = temp_root / "build"
        script_path.write_text(config.smoke_source + "\n", encoding="utf-8")
        with _temporary_subprocess_env():
            runner(
                [
                    python_cmd,
                    "-m",
                    "nuitka",
                    "--mode=standalone",
                    f"--output-dir={output_dir}",
                    str(script_path),
                ],
                check=True,
                cwd=str(temp_root),
            )
        dist_dir = output_dir / "framelab_nuitka_smoke.dist"
        if not dist_dir.exists():
            raise RuntimeError(
                "Nuitka smoke build finished without creating the expected dist directory.",
            )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build FrameLab as a standalone directory app with Nuitka.",
    )
    parser.add_argument(
        "--target",
        choices=("auto", *SUPPORTED_TARGETS),
        default="auto",
        help="Host-native target to build (default: auto-detect from current OS).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the repo-owned Nuitka wrapper config TOML file.",
    )
    parser.add_argument(
        "--python",
        dest="python_executable",
        default=sys.executable,
        help=(
            "Python interpreter used to run Nuitka and, when needed, the native "
            "backend build helper."
        ),
    )
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--check",
        action="store_true",
        help="Validate config and inputs, then print the resolved Nuitka command.",
    )
    action_group.add_argument(
        "--smoke",
        action="store_true",
        help="Run a tiny standalone Nuitka smoke compile in a temporary directory.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the target output directory before building.",
    )
    parser.add_argument(
        "--skip-native-build",
        action="store_true",
        help="Do not auto-build the FrameLab native backend when it is missing.",
    )
    parser.add_argument(
        "--nuitka-extra-arg",
        action="append",
        default=[],
        help="Extra argument to append to the final Nuitka command. May be repeated.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        if args.smoke:
            run_smoke_build(
                config_path=args.config,
                python_executable=args.python_executable,
            )
            print("Nuitka smoke build completed successfully.")
            return 0

        plan = build_plan(
            target=args.target,
            config_path=args.config,
            python_executable=args.python_executable,
            nuitka_extra_args=args.nuitka_extra_arg,
        )
        validate_nuitka_toolchain(plan.toolchain)
        if args.clean:
            clean_output_dir(plan.output_dir)
        if args.check:
            print(_format_plan(plan))
            return 0
        validate_host_build_requirements(plan.target)
        run_build(
            plan,
            skip_native_build=args.skip_native_build,
        )
        print(f"Nuitka build completed: {plan.dist_dir}")
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
