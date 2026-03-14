"""FrameLab package."""

from __future__ import annotations


def main() -> int:
    """Run the Qt application entry point.

    Returns
    -------
    int
        Process exit code from the Qt event loop.
    """
    from .app import main as run_main

    return run_main()


__all__ = ["main"]
