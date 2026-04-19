"""Minimal curses loader for build-time Python subprocesses.

This mirrors the stdlib module shape closely enough for ``_pyrepl`` while being
more tolerant of conda-style linker scripts such as ``libncursesw.so``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from pathlib import Path
import re


class error(Exception):
    """Mirror the stdlib module's exported error type."""


def _is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def _iter_loadable_candidates(path_text: str):
    path = Path(path_text)
    seen: set[str] = set()

    def _yield(candidate: Path | str):
        text = str(candidate)
        if not text or text in seen:
            return
        seen.add(text)
        yield text

    if not path.is_absolute():
        yield from _yield(path_text)
        return

    yield from _yield(path)
    if _is_elf(path):
        return

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""

    for token in re.findall(r"(lib[^\s\)]+\.so(?:\.\d+)*)", text):
        yield from _yield(path.with_name(token))

    if path.name.endswith(".so"):
        for sibling in sorted(path.parent.glob(f"{path.name}.*")):
            if _is_elf(sibling):
                yield from _yield(sibling)

    resolved = path.resolve()
    if resolved != path and _is_elf(resolved):
        yield from _yield(resolved)


def _load_clib() -> tuple[str, object]:
    for lib_name in ("ncursesw", "ncurses", "curses"):
        path = ctypes.util.find_library(lib_name)
        if not path:
            continue

        for candidate in _iter_loadable_candidates(path):
            try:
                return candidate, ctypes.cdll.LoadLibrary(candidate)
            except OSError:
                continue

    raise ModuleNotFoundError("curses library not found", name="_pyrepl._minimal_curses")


_clibpath, clib = _load_clib()

clib.setupterm.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
clib.setupterm.restype = ctypes.c_int

clib.tigetstr.argtypes = [ctypes.c_char_p]
clib.tigetstr.restype = ctypes.c_ssize_t

clib.tparm.argtypes = [ctypes.c_char_p] + 9 * [ctypes.c_int]  # type: ignore[operator]
clib.tparm.restype = ctypes.c_char_p

OK = 0
ERR = -1


def setupterm(termstr, fd):
    err = ctypes.c_int(0)
    result = clib.setupterm(termstr, fd, ctypes.byref(err))
    if result == ERR:
        raise error(f"setupterm() failed (err={err.value})")


def tigetstr(cap):
    if not isinstance(cap, bytes):
        cap = cap.encode("ascii")
    result = clib.tigetstr(cap)
    if result == ERR:
        return None
    return ctypes.cast(result, ctypes.c_char_p).value


def tparm(value, i1=0, i2=0, i3=0, i4=0, i5=0, i6=0, i7=0, i8=0, i9=0):
    result = clib.tparm(value, i1, i2, i3, i4, i5, i6, i7, i8, i9)
    if result is None:
        raise error("tparm() returned NULL")
    return result
