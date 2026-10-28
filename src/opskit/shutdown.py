"""Stop events for long-running consumers.

Signal handlers can only be installed on the main thread. Workers running
elsewhere should pass in their own ``threading.Event`` and skip installation.
"""
from __future__ import annotations

import signal
import threading
from collections.abc import Callable


def install_stop_signals(stop_event: threading.Event) -> Callable[[], None]:
    """Point SIGINT and SIGTERM at ``stop_event`` and return a restorer.

    The previous handlers are put back when the returned callable runs.
    Installation is skipped when the interpreter refuses the change, which
    happens off the main thread.
    """
    previous: dict[signal.Signals, signal.Handlers] = {}

    def _handler(signum: int, _frame: object) -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, _handler)
        except (ValueError, OSError):
            continue

    def restore() -> None:
        for sig, old in previous.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError):
                continue

    return restore
