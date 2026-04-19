"""Build-time _pyrepl shim for Nuitka subprocesses.

This package sits on PYTHONPATH only while the FrameLab Nuitka wrapper runs.
It extends the real stdlib package path and overrides only
``_pyrepl._minimal_curses`` to work around conda environments where
``libncursesw.so`` is a linker script rather than a loadable ELF library.
"""

from pkgutil import extend_path


__path__ = extend_path(__path__, __name__)
