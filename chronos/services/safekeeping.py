"""Safekeeping — backups, restore, undo, health and storage.

Backups (the `backups` folder beside your archive):
- **daily**: the first time Chronos opens each day;
- **safety copies**: just before anything that removes or rewrites data —
  removing items, merging duplicates, restoring, upgrading the database;
- **yours**: "Back up now" (kept until you delete them), or a **full backup**
  — the database, settings and every saved page in one .zip, wherever you
  choose (a USB stick, another drive).
A backup is a consistent copy made with SQLite's own backup function, so it's
right even while Chronos is running. Old daily copies thin out (the last 7
days, then one a week for 4 weeks); the last 10 safety copies are kept.

Removed items' saved pages go to `archives/.removed` first, so "Undo" and
"Restore" bring them back; they're cleared after 30 days (or when you choose).

Health: the database's own integrity check, links between tables, the search
index, saved files missing or damaged, files nothing uses — and repairs that
never delete: the search index is rebuilt, missing files are brought back from
`.removed` when they're there, unused files are moved aside.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

KEEP_DAILY_DAYS = 7
KEEP_WEEKLY = 4
KEEP_SAFETY = 10
REMOVED_DAYS = 30
SAFETY_REASONS = ("before-remove", "before-merge", "before-restore", "before-upgrade",
                  "before-repair")


@dataclass
class BackupInfo:
    path: Path
    created: int
    reason: str
    items: int
    version: int
    size: int

    @property
    def label(self) -> str:
        when = datetime.fromtimestamp(self.created).strftime("%Y-%m-%d %H:%M")
        why = {"daily": "Daily", "manual": "Yours", "full": "Full backup",
               "before-remove": "Before removing items",
               "before-merge": "Before merging duplicates",
               "before-restore": "Before a restore",
               "before-upgrade": "Before an upgrade",
               "before-repair": "Before a repair"}.get(self.reason, self.reason)
        return f"{when} — {why} ({self.items:,} items)"


@dataclass
class HealthReport:
    ok: bool = True
    lines: List[str] = field(default_factory=list)       # what was checked, in words
    problems: List[str] = field(default_factory=list)
    missing_files: List[int] = field(default_factory=list)   # bookmark ids
    damaged_files: List[int] = field(default_factory=list)
    orphan_files: List[Path] = field(default_factory=list)
    fts_bad: bool = False
    db_bad: bool = False

    def text(self) -> str:
        head = ("Everything checked is healthy." if self.ok and not self.problems
                else f"{len(self.problems)} thing{'s' if len(self.problems) != 1 else ''} to look at:")
        out = [head] + [f"  • {p}" for p in self.problems]
        out += ["", "Checked:"] + [f"  ✓ {l}" for l in self.lines]
        return "\n".join(out)

    @property
    def repairable(self) -> bool:
        return bool(self.fts_bad or self.missing_files or self.orphan_files)


def _now() -> int:
    return int(time.time())


def sqlite_copy(src: sqlite3.Connection, dest: Path) -> None:
    """A consistent copy of a live database (WAL included), written atomically."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    if tmp.exists():
        tmp.unlink()
    dst = sqlite3.connect(str(tmp))
    try:
        src.backup(dst)
    finally:
        dst.close()
    tmp.replace(dest)


class Safekeeping:
    def __init__(self, ctx):
        self.ctx = ctx
        self.app_dir = Path(ctx.config.app_dir)
        self.dir = self.app_dir / "backups"
        self.archives = Path(ctx.config.archives_dir)
        self.removed = self.archives / ".removed"

    # ------------------------------------------------------------------ #
    # Backups
    # ------------------------------------------------------------------ #
    def _meta(self, reason: str) -> dict:
        from .. import __version__
        st = self.ctx.storage
        return {"created": _now(), "reason": reason, "items": st.count(),
                "version": st.version, "chronos": __version__}

    def backup(self, reason: str = "manual") -> Path:
        st = self.ctx.storage
        st.conn.commit()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self.dir / f"chronos-{stamp}-{reason}.db"
        n = 1
        while dest.exists():
            dest = self.dir / f"chronos-{stamp}-{reason}-{n}.db"; n += 1
        sqlite_copy(st.conn, dest)
        meta = self._meta(reason)
        dest.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if self.ctx.config.settings_path.exists():
            shutil.copy2(self.ctx.config.settings_path, dest.with_suffix(".settings.json"))
        self.prune()
        return dest

    def list(self) -> List[BackupInfo]:
        out = []
        if not self.dir.exists():
            return out
        for p in self.dir.glob("chronos-*.db"):
            meta = {}
            try:
                meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            out.append(BackupInfo(p, int(meta.get("created") or p.stat().st_mtime),
                                  meta.get("reason", "manual"), int(meta.get("items") or 0),
                                  int(meta.get("version") or 0), p.stat().st_size))
        for p in self.dir.glob("chronos-full-*.zip"):
            out.append(BackupInfo(p, int(p.stat().st_mtime), "full", 0, 0, p.stat().st_size))
        out.sort(key=lambda b: b.created, reverse=True)
        return out

    def _delete(self, b: BackupInfo) -> None:
        for p in (b.path, b.path.with_suffix(".json"), b.path.with_suffix(".settings.json")):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    def prune(self, now: Optional[int] = None) -> int:
        """Thin out old automatic copies. Your own backups are never removed."""
        now = now or _now()
        gone = 0
        backups = self.list()
        daily = [b for b in backups if b.reason == "daily"]
        weeks_kept = set()
        for b in daily:                                         # newest first
            age = now - b.created
            if age <= KEEP_DAILY_DAYS * 86400:
                continue
            week = datetime.fromtimestamp(b.created).isocalendar()[:2]
            if age <= (KEEP_DAILY_DAYS + 7 * KEEP_WEEKLY) * 86400 and week not in weeks_kept:
                weeks_kept.add(week)
                continue
            self._delete(b); gone += 1
        safety = [b for b in backups if b.reason in SAFETY_REASONS]
        for b in safety[KEEP_SAFETY:]:
            self._delete(b); gone += 1
        return gone

    def daily_if_due(self, hours: float = 20) -> Optional[Path]:
        last = [b for b in self.list() if b.reason in ("daily", "manual", "full")]
        if last and _now() - last[0].created < hours * 3600:
            return None
        if self.ctx.storage.count() == 0:
            return None
        return self.backup("daily")

    def full_backup(self, folder, progress: Optional[Callable[[int, int], None]] = None) -> Path:
        """Database, settings and every saved page in one .zip, in `folder`."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"chronos-full-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        tmpdir = Path(tempfile.mkdtemp(prefix="chronos_full_"))
        try:
            db = tmpdir / "bookmarks.db"
            self.ctx.storage.conn.commit()
            sqlite_copy(self.ctx.storage.conn, db)
            files = [p for p in self.archives.glob("*") if p.is_file()]
            part = dest.with_name(dest.name + ".part")
            with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                z.write(db, "bookmarks.db")
                z.writestr("chronos-backup.json", json.dumps(self._meta("full"), indent=2))
                if self.ctx.config.settings_path.exists():
                    z.write(self.ctx.config.settings_path, "settings.json")
                for i, f in enumerate(files, 1):
                    # saved pages are gzipped already: store, don't squeeze twice
                    z.write(f, f"archives/{f.name}", compress_type=zipfile.ZIP_STORED)
                    if progress:
                        progress(i, len(files))
            part.replace(dest)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return dest

    # ------------------------------------------------------------------ #
    # Restore and undo
    # ------------------------------------------------------------------ #
    def restore(self, path) -> Path:
        """Put your archive back as it was in a backup (.db, or a full .zip).
        A safety copy of how it is now is made first. Returns that copy."""
        path = Path(path)
        safety = self.backup("before-restore")
        tmpdir = None
        try:
            src_db = path
            if path.suffix.lower() == ".zip":
                tmpdir = Path(tempfile.mkdtemp(prefix="chronos_restore_"))
                with zipfile.ZipFile(path) as z:
                    names = set(z.namelist())
                    if "bookmarks.db" not in names:
                        raise ValueError("This .zip isn't a Chronos full backup.")
                    z.extract("bookmarks.db", tmpdir)
                    self.archives.mkdir(parents=True, exist_ok=True)
                    for n in names:
                        if n.startswith("archives/") and not n.endswith("/"):
                            target = self.archives / Path(n).name
                            if not target.exists():
                                with z.open(n) as s, open(target, "wb") as d:
                                    shutil.copyfileobj(s, d, 1 << 20)
                src_db = tmpdir / "bookmarks.db"
            src = sqlite3.connect(str(src_db))
            try:
                ok = src.execute("PRAGMA quick_check").fetchone()[0]
                if ok != "ok":
                    raise ValueError(f"That backup is damaged ({ok}); nothing was changed.")
                st = self.ctx.storage
                st.conn.commit()
                src.backup(st.conn)                       # replaces the live database
            finally:
                src.close()
            from ..core.migrations import apply_migrations
            st.version = apply_migrations(st.conn)          # an older backup is upgraded
            self._bring_back_files()
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
        return safety

    def _bring_back_files(self) -> int:
        """Saved pages the database expects that were set aside: move them back."""
        back = 0
        for a in self.ctx.storage.all_archives():
            p = Path(a["path"])
            if not p.exists():
                aside = self.removed / p.name
                if aside.exists():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(aside), str(p))
                    back += 1
        return back

    def last_safety(self, reason: str) -> Optional[BackupInfo]:
        for b in self.list():
            if b.reason == reason:
                return b
        return None

    # ------------------------------------------------------------------ #
    # Removed files
    # ------------------------------------------------------------------ #
    def set_aside(self, path: Path) -> None:
        """Move a saved page to .removed instead of deleting it."""
        path = Path(path)
        if not path.exists():
            return
        self.removed.mkdir(parents=True, exist_ok=True)
        target = self.removed / path.name
        if target.exists():
            path.unlink()
        else:
            shutil.move(str(path), str(target))
        os.utime(target, None)                            # "removed at" = now

    def empty_removed(self, older_than_days: Optional[int] = REMOVED_DAYS) -> int:
        n = 0
        if not self.removed.exists():
            return 0
        limit = _now() - (older_than_days or 0) * 86400
        for f in self.removed.iterdir():
            if f.is_file() and (older_than_days is None or f.stat().st_mtime < limit):
                f.unlink(); n += 1
        return n

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #
    def check(self, deep: bool = False,
              progress: Optional[Callable[[int, int], None]] = None) -> HealthReport:
        r = HealthReport()
        c = self.ctx.storage.conn
        res = [row[0] for row in c.execute(
            "PRAGMA integrity_check" if deep else "PRAGMA quick_check").fetchall()]
        if res != ["ok"]:
            r.ok = False; r.db_bad = True
            r.problems.append("The database reports damage: " + "; ".join(res[:3])
                              + ". Restore from a backup (Safekeeping, Restore).")
        r.lines.append("the database file " + ("(full check)" if deep else "(quick check)"))
        fk = c.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            r.ok = False
            r.problems.append(f"{len(fk)} record(s) point at items that no longer exist.")
        r.lines.append("links between items, quotes, takeaways and copies")
        try:
            c.execute("INSERT INTO bookmarks_fts(bookmarks_fts) VALUES('integrity-check')")
            # how many items the index really holds (the table itself reads from
            # the items, so counting it would always agree)
            n_fts = c.execute("SELECT COUNT(*) FROM bookmarks_fts_docsize").fetchone()[0]
            n_bm = c.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
            if n_fts != n_bm:
                raise sqlite3.DatabaseError(f"{n_fts} indexed of {n_bm}")
        except sqlite3.DatabaseError as e:
            r.ok = False; r.fts_bad = True
            r.problems.append(f"The search index is out of step ({e}); repair rebuilds it.")
        r.lines.append("the search index")
        archives = self.ctx.storage.all_archives()
        referenced = set()
        for i, a in enumerate(archives, 1):
            p = Path(a["path"]); referenced.add(p.name)
            if not p.exists():
                r.missing_files.append(a["bookmark_id"])
            elif deep:
                try:
                    with gzip.open(p, "rb") as f:
                        if hashlib.sha1(f.read()).hexdigest() != a["sha1"]:
                            r.damaged_files.append(a["bookmark_id"])
                except (OSError, EOFError, gzip.BadGzipFile):
                    r.damaged_files.append(a["bookmark_id"])
            if progress:
                progress(i, len(archives))
        if r.missing_files:
            r.ok = False
            aside = sum(1 for a in archives if a["bookmark_id"] in set(r.missing_files)
                        and (self.removed / Path(a["path"]).name).exists())
            r.problems.append(f"{len(r.missing_files):,} saved page(s) are missing from disk"
                              + (f" ({aside:,} can be brought back)" if aside else "") + ".")
        if r.damaged_files:
            r.ok = False
            r.problems.append(f"{len(r.damaged_files):,} saved page(s) are damaged; "
                              "save them again (Fetch, “Also try again”).")
        r.lines.append(f"{len(archives):,} saved pages" + (" (each one read and verified)"
                                                          if deep else " (present on disk)"))
        if self.archives.exists():
            r.orphan_files = [f for f in self.archives.glob("*.gz") if f.name not in referenced]
        if r.orphan_files:
            r.problems.append(f"{len(r.orphan_files):,} saved file(s) aren’t used by any "
                              "item; repair moves them aside (nothing is deleted).")
        r.lines.append("files nothing uses")
        try:
            json.loads(self.ctx.config.settings_path.read_text(encoding="utf-8")) \
                if self.ctx.config.settings_path.exists() else None
            r.lines.append("your settings")
        except (OSError, ValueError):
            r.ok = False
            r.problems.append("Your settings file can't be read; defaults are in use.")
        free = shutil.disk_usage(self.app_dir).free
        if free < (1 << 30):
            r.problems.append(f"Only {free >> 20:,} MB free on this drive.")
        r.lines.append(f"free space ({free / (1 << 30):,.1f} GB)")
        return r

    def repair(self, report: Optional[HealthReport] = None) -> List[str]:
        """Fix what can be fixed without deleting anything. A safety copy first."""
        report = report or self.check()
        done = []
        if not report.repairable:
            return ["Nothing needed repairing."]
        self.backup("before-repair")
        c = self.ctx.storage.conn
        if report.fts_bad:
            c.execute("INSERT INTO bookmarks_fts(bookmarks_fts) VALUES('rebuild')")
            c.commit()
            done.append("The search index was rebuilt.")
        if report.missing_files:
            back = self._bring_back_files()
            if back:
                done.append(f"{back:,} saved page(s) were brought back.")
            left = len(report.missing_files) - back
            if left:
                done.append(f"{left:,} saved page(s) are gone for good; save them again "
                            "with Fetch (“Also try again”).")
                for bid in report.missing_files:
                    rec = self.ctx.storage.get_archive(bid)
                    if rec and not Path(rec["path"]).exists():
                        self.ctx.storage.delete_archive(bid)
        if report.orphan_files:
            for f in report.orphan_files:
                self.set_aside(f)
            done.append(f"{len(report.orphan_files):,} unused file(s) were moved to "
                        "archives/.removed.")
        return done

    # ------------------------------------------------------------------ #
    # Storage
    # ------------------------------------------------------------------ #
    @staticmethod
    def _size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return 0

    def usage(self) -> Dict[str, object]:
        db = self.ctx.config.db_path
        wal = Path(str(db) + "-wal")
        st = self.ctx.storage
        per_site = st.conn.execute(
            """SELECT b.domain d, COUNT(*) n, SUM(a.bytes) raw FROM archives a
               JOIN bookmarks b ON b.id = a.bookmark_id
               GROUP BY b.domain ORDER BY raw DESC LIMIT 12""").fetchall()
        live = sum(f.stat().st_size for f in self.archives.glob("*.gz")) \
            if self.archives.exists() else 0
        return {
            "database": self._size(db), "journal": self._size(wal),
            "saved_pages": live, "saved_count": st.archive_count(),
            "removed": self._size(self.removed), "backups": self._size(self.dir),
            "backup_count": len(self.list()),
            "favicons": self._size(Path(getattr(self.ctx.config, "favicons_dir", ""))),
            "per_site": [(r["d"], r["n"], r["raw"] or 0) for r in per_site],
            "free": shutil.disk_usage(self.app_dir).free,
        }

    def compact(self) -> int:
        """Give back space left by removed items (VACUUM). Returns bytes saved."""
        db = self.ctx.config.db_path
        before = self._size(db) + self._size(Path(str(db) + "-wal"))
        c = self.ctx.storage.conn
        c.commit()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.execute("VACUUM")
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        after = self._size(db) + self._size(Path(str(db) + "-wal"))
        return max(0, before - after)


def size_text(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"
