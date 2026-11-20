"""Run blocking work (network, file parsing, SVG rendering) off the UI thread.

A tiny wrapper over ``QThreadPool`` so views can do::

    runner.run(api.list_blueprints, on_done=self._populate, on_error=self._error)
"""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

__all__ = ["TaskRunner", "WorkerSignals"]


class WorkerSignals(QObject):
    """Signals emitted by a background task."""

    finished = Signal(object)
    failed = Signal(str)
    done = Signal()


class _Worker(QRunnable):
    def __init__(self, fn, args: tuple, kwargs: dict) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:  # noqa: D102 - QRunnable entry point
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - surface everything to the UI
            traceback.print_exc()
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.finished.emit(result)
        finally:
            self.signals.done.emit()


class TaskRunner(QObject):
    """Owns a thread pool and keeps workers alive until they finish."""

    def __init__(self, max_threads: int = 4, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_threads)
        self._live: set[_Worker] = set()

    def run(self, fn, *args, on_done=None, on_error=None, on_finished=None, **kwargs) -> _Worker:
        """Schedule ``fn(*args, **kwargs)``; callbacks fire on the UI thread."""
        worker = _Worker(fn, args, kwargs)
        if on_done is not None:
            worker.signals.finished.connect(on_done)
        if on_error is not None:
            worker.signals.failed.connect(on_error)
        if on_finished is not None:
            worker.signals.done.connect(on_finished)
        worker.signals.done.connect(lambda w=worker: self._live.discard(w))
        self._live.add(worker)
        self._pool.start(worker)
        return worker

    def wait(self, timeout_ms: int = 5000) -> bool:
        """Block until all queued work finishes (used on shutdown)."""
        return self._pool.waitForDone(timeout_ms)
