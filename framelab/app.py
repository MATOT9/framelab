"""Application entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path
import traceback
from typing import Any, Callable
import functools
import inspect
import weakref

from PySide6 import QtCore, QtGui, QtWidgets as qtw
from PySide6.QtCore import QTimer

from .icons import apply_app_identity, prepare_process_identity
from .mpl_config import ensure_matplotlib_config_dir
from .plugins import discover_plugin_manifests
from .plugins.selection import (
    PluginStartupDialog,
    load_selected_plugin_ids,
    save_selected_plugin_ids,
)
from .scan_settings import app_config_path
from .window import FrameLabWindow
from .stylesheets import DARK_THEME


_NUITKA_QT_SLOT_WRAPPERS: weakref.WeakKeyDictionary[
    object, dict[object, Callable[..., Any]]
] = weakref.WeakKeyDictionary()
_NUITKA_QT_SLOT_WRAPPERS_FALLBACK: dict[tuple[int, object], Callable[..., Any]] = {}
_NUITKA_QT_CALLABLE_WRAPPERS: weakref.WeakKeyDictionary[
    object, Callable[..., Any]
] = weakref.WeakKeyDictionary()
_NUITKA_QT_CALLABLE_WRAPPERS_FALLBACK: dict[int, Callable[..., Any]] = {}


def _selector_splash_path() -> Path:
    """Return the packaged selector-splash image path."""

    return Path(__file__).resolve().parent / "assets" / "framelab_splash.png"


def _create_selector_splash(
    app: qtw.QApplication,
) -> qtw.QSplashScreen | None:
    """Show the startup splash used before the plugin selector."""

    platform_name = ""
    try:
        platform_name = str(app.platformName()).strip().lower()
    except Exception:
        platform_name = ""
    if platform_name in {"offscreen", "minimal", "minimalegl"}:
        return None

    splash_path = _selector_splash_path()
    if not splash_path.exists():
        return None
    pixmap = QtGui.QPixmap(str(splash_path))
    if pixmap.isNull():
        return None

    splash = qtw.QSplashScreen(pixmap)
    splash.setObjectName("FrameLabSplash")
    splash.show()
    app.processEvents()
    return splash


def _close_selector_splash(
    splash: qtw.QSplashScreen | None,
    *,
    target: qtw.QWidget | None = None,
) -> None:
    """Close the selector splash without leaving a stray top-level window."""

    if splash is None:
        return
    try:
        _ = target
        splash.close()
    finally:
        splash.deleteLater()


def _startup_error_log_path() -> Path:
    """Return the persistent startup-error log path."""

    return app_config_path("startup_error.log")


def _record_startup_exception(title: str) -> Path | None:
    """Persist the active traceback for frozen-startup diagnostics."""

    formatted = traceback.format_exc()
    if formatted and formatted != "NoneType: None\n":
        print(formatted, file=sys.stderr, end="")

    path = _startup_error_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = f"{title}\n{'=' * len(title)}\n"
        path.write_text(header + formatted, encoding="utf-8")
    except Exception:
        return None
    return path


def _startup_error_message(exc: BaseException, *, log_path: Path | None) -> str:
    """Format one user-facing startup error message."""

    message = str(exc).strip() or type(exc).__name__
    if log_path is None:
        return message
    return f"{message}\n\nFull traceback saved to:\n{log_path}"


def _bound_qt_slot_parts(slot: object) -> tuple[object, object, str | None] | None:
    """Return normalized identity data for one bound Qt slot."""

    owner = getattr(slot, "__self__", None)
    if owner is None:
        owner = getattr(slot, "im_self", None)
    if owner is None:
        return None

    func = getattr(slot, "__func__", None)
    if func is None:
        func = getattr(slot, "im_func", None)
    name = getattr(slot, "__name__", None)
    key = func if func is not None else name if name else type(slot)
    return owner, key, name


def _make_general_qt_slot_wrapper(slot: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a generic Python callable for frozen PySide6 signal delivery."""

    if isinstance(slot, functools.partial):

        def wrapper(*args: Any, __slot=slot, **kwargs: Any) -> Any:
            return __slot(*args, **kwargs)

        wrapper.__name__ = "_framelab_qt_slot_wrapper_partial"
        return wrapper

    if inspect.isfunction(slot):

        def wrapper(*args: Any, __slot=slot, **kwargs: Any) -> Any:
            return __slot(*args, **kwargs)

        wrapper.__name__ = f"_framelab_qt_slot_wrapper_{getattr(slot, '__name__', 'callable')}"
        return wrapper

    return slot


def _make_nuitka_qt_slot_wrapper(slot: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a bound slot in a plain Python callable for frozen PySide6 builds."""

    parts = _bound_qt_slot_parts(slot)
    if parts is None:
        return slot

    owner, _key, name = parts
    func = getattr(slot, "__func__", None)
    if func is None:
        func = getattr(slot, "im_func", None)

    try:
        owner_ref = weakref.ref(owner)
        owner_value = None
    except TypeError:
        owner_ref = None
        owner_value = owner

    wrapper_name = name or "slot"

    if name:

        def wrapper(*args: Any, _name=name, **kwargs: Any) -> Any:
            target = owner_value if owner_ref is None else owner_ref()
            if target is None:
                return None
            return getattr(target, _name)(*args, **kwargs)

    elif callable(func):

        def wrapper(*args: Any, _func=func, **kwargs: Any) -> Any:
            target = owner_value if owner_ref is None else owner_ref()
            if target is None:
                return None
            return _func(target, *args, **kwargs)

    else:

        def wrapper(*args: Any, __slot=slot, **kwargs: Any) -> Any:
            return __slot(*args, **kwargs)

    wrapper.__name__ = f"_framelab_qt_slot_wrapper_{wrapper_name}"
    return wrapper


def _wrap_nuitka_qt_slot(slot: object) -> object:
    """Return a stable wrapper for bound methods in Nuitka PySide6 builds."""

    if slot is None or not callable(slot):
        return slot

    parts = _bound_qt_slot_parts(slot)
    if parts is None:
        return slot

    owner, key, _name = parts
    try:
        per_owner = _NUITKA_QT_SLOT_WRAPPERS.setdefault(owner, {})
    except TypeError:
        fallback_key = (id(owner), key)
        wrapper = _NUITKA_QT_SLOT_WRAPPERS_FALLBACK.get(fallback_key)
        if wrapper is None:
            wrapper = _make_nuitka_qt_slot_wrapper(slot)
            _NUITKA_QT_SLOT_WRAPPERS_FALLBACK[fallback_key] = wrapper
        return wrapper

    wrapper = per_owner.get(key)
    if wrapper is None:
        wrapper = _make_nuitka_qt_slot_wrapper(slot)
        per_owner[key] = wrapper
    return wrapper


def _wrap_nuitka_qt_callable(slot: object) -> object:
    """Return a stable wrapper for Python callables in frozen PySide6 builds."""

    if slot is None or not callable(slot):
        return slot

    wrapped_bound = _wrap_nuitka_qt_slot(slot)
    if wrapped_bound is not slot:
        return wrapped_bound

    if not (
        inspect.isfunction(slot)
        or isinstance(slot, functools.partial)
    ):
        return slot

    try:
        wrapper = _NUITKA_QT_CALLABLE_WRAPPERS.get(slot)
    except TypeError:
        key = id(slot)
        wrapper = _NUITKA_QT_CALLABLE_WRAPPERS_FALLBACK.get(key)
        if wrapper is None:
            wrapper = _make_general_qt_slot_wrapper(slot)
            _NUITKA_QT_CALLABLE_WRAPPERS_FALLBACK[key] = wrapper
        return wrapper

    if wrapper is None:
        wrapper = _make_general_qt_slot_wrapper(slot)
        _NUITKA_QT_CALLABLE_WRAPPERS[slot] = wrapper
    return wrapper


def _install_nuitka_pyside6_signal_workaround() -> None:
    """Wrap bound Qt slots before Nuitka's PySide6 hook sees them."""

    signal_instance = getattr(QtCore, "SignalInstance", None)
    if signal_instance is None:
        return

    current_connect = getattr(signal_instance, "connect", None)
    if current_connect is None:
        return

    current_module = str(getattr(current_connect, "__module__", "") or "")
    if current_module == __name__:
        return
    if current_module != "PySide6-postLoad":
        return

    current_disconnect = signal_instance.disconnect
    current_single_shot = QtCore.QTimer.singleShot

    raw_connect = getattr(current_connect, "__globals__", {}).get(
        "orig_connect",
        current_connect,
    )
    raw_disconnect = getattr(current_disconnect, "__globals__", {}).get(
        "orig_disconnect",
        current_disconnect,
    )
    raw_single_shot = getattr(current_single_shot, "__globals__", {}).get(
        "orig_singleShot",
        current_single_shot,
    )

    def patched_connect(self, slot, type=None):
        wrapped_slot = _wrap_nuitka_qt_callable(slot)
        connection_type = type or QtCore.Qt.ConnectionType.AutoConnection
        return raw_connect(self, wrapped_slot, connection_type)

    def patched_disconnect(self, slot=None):
        if slot is None:
            return raw_disconnect(self)
        return raw_disconnect(self, _wrap_nuitka_qt_callable(slot))

    def patched_single_shot(self, *args, **kwargs):
        if args:
            args = list(args)
            for index in range(len(args) - 1, -1, -1):
                if callable(args[index]):
                    args[index] = _wrap_nuitka_qt_callable(args[index])
                    break
        for key in ("callable", "functor", "slot"):
            candidate = kwargs.get(key)
            if callable(candidate):
                kwargs = dict(kwargs)
                kwargs[key] = _wrap_nuitka_qt_callable(candidate)
                break
        return raw_single_shot(self, *args, **kwargs)

    patched_connect.__module__ = __name__
    patched_disconnect.__module__ = __name__
    patched_single_shot.__module__ = __name__

    signal_instance.connect = patched_connect
    signal_instance.disconnect = patched_disconnect
    QtCore.QTimer.singleShot = patched_single_shot


def main() -> int:
    """Run the Qt application entry point.

    Returns
    -------
    int
        Process exit code from the Qt event loop.
    """
    _install_nuitka_pyside6_signal_workaround()
    prepare_process_identity()
    ensure_matplotlib_config_dir()
    app = qtw.QApplication(sys.argv)
    apply_app_identity(app)
    app.setStyleSheet(DARK_THEME)
    splash = _create_selector_splash(app)

    try:
        manifests = discover_plugin_manifests()
        selected_ids = load_selected_plugin_ids(manifests)
    except Exception as exc:
        _close_selector_splash(splash)
        log_path = _record_startup_exception("Plugin Startup Error")
        qtw.QMessageBox.critical(
            None,
            "Plugin Startup Error",
            _startup_error_message(exc, log_path=log_path),
        )
        return 1

    selector = PluginStartupDialog(
        manifests,
        selected_plugin_ids=selected_ids,
    )
    _close_selector_splash(splash, target=selector)
    if selector.exec() != qtw.QDialog.Accepted:
        return 0

    enabled_plugin_ids = selector.enabled_plugin_ids()
    save_selected_plugin_ids(enabled_plugin_ids)

    try:
        win = FrameLabWindow(enabled_plugin_ids=enabled_plugin_ids)
    except Exception as exc:
        log_path = _record_startup_exception("Plugin Load Error")
        qtw.QMessageBox.critical(
            None,
            "Plugin Load Error",
            _startup_error_message(exc, log_path=log_path),
        )
        return 1
    if win.workflow_state_controller.workspace_root is None:
        win._open_workflow_selection_dialog()
    win.showMaximized()
    return app.exec()
