"""Background fetch worker — owns its OWN SQLite connection.

sqlite3 connections are thread-bound. The worker therefore builds a fresh
ApplicationContext (hence a fresh connection) inside run(), on the worker
thread, does the gated fetch+store, and closes it. WAL mode lets the GUI thread
keep reading the same database file concurrently. The main-thread context is
never touched from here.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core.context import ApplicationContext


class FetchWorker(QThread):
    done = Signal(int)          # bookmark id, on success
    failed = Signal(int, str)   # bookmark id, error message

    def __init__(self, app_dir: Path, bookmark_id: int, parent=None):
        super().__init__(parent)
        self._app_dir = Path(app_dir)
        self._bid = bookmark_id

    def run(self) -> None:
        ctx = None
        try:
            ctx = ApplicationContext.for_dir(self._app_dir)  # own connection
            from ..web.fetch_queue import FetchEngine
            out = FetchEngine(ctx).fetch_one(self._bid)      # follows the site's rule
            if out.ok:
                self.done.emit(self._bid)
            else:
                self.failed.emit(self._bid, out.reason or out.status)
        except Exception as e:  # NetworkDisabled or fetch/parse error
            self.failed.emit(self._bid, str(e))
        finally:
            if ctx is not None:
                ctx.close()


class TaskWorker(QThread):
    """Run any `fn(ctx) -> str` on a worker thread with its own context
    (own SQLite connection). Used for imports, link checks, merges, tagging —
    anything that could take long enough to freeze the window."""
    done = Signal(str)       # summary sentence
    failed = Signal(str)     # error message

    def __init__(self, app_dir: Path, fn, parent=None):
        super().__init__(parent)
        self._app_dir = Path(app_dir)
        self._fn = fn

    def run(self) -> None:
        ctx = None
        try:
            ctx = ApplicationContext.for_dir(self._app_dir)
            self.done.emit(str(self._fn(ctx)))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}" if not str(e) else str(e))
        finally:
            if ctx is not None:
                ctx.close()


class Job(QThread):
    """Run `fn(ctx) -> anything` on a worker thread with its own context and
    hand the result back (used by the Your archive window)."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, app_dir: Path, fn, parent=None):
        super().__init__(parent)
        self._app_dir = Path(app_dir)
        self._fn = fn

    def run(self) -> None:
        ctx = None
        try:
            ctx = ApplicationContext.for_dir(self._app_dir)
            self.done.emit(self._fn(ctx))
        except Exception as e:
            self.failed.emit(str(e) or type(e).__name__)
        finally:
            if ctx is not None:
                ctx.close()
