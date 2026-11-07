"""v0.38 "Safekeeping": backups (daily, safety copies, yours, full .zip),
restore and Undo, old copies thinned, a copy before every upgrade, health
checks that find real damage and repairs that never delete, storage use and
compacting — and the Your archive window.
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402

PAGE = "<html><body><article><p>Brahui is a Dravidian language, ڈ ڑ.</p></article></body></html>"


def _ctx():
    tmp = Path(tempfile.mkdtemp(prefix="chronos_safe_")).resolve()
    return tmp, ApplicationContext.for_dir(tmp / "h")


def _fill(ctx, n=5):
    ids = []
    for i in range(n):
        bid, _ = ctx.storage.upsert_bookmark(Bookmark(
            url=f"https://example.org/{i}", title=f"Item {i}", date_added=1700000000 + i,
            browser="F", tags=["brahui"]))
        ctx.archive.archive_from_html(bid, PAGE.replace("Brahui", f"Brahui {i}"),
                                      f"https://example.org/{i}")
        ctx.snippets.capture(bid, f"Dravidian {i}")
        ids.append(bid)
    ctx.storage.conn.commit()
    return ids


class BackupRestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ctx = _ctx()
        self.ids = _fill(self.ctx)
        self.sk = self.ctx.safekeeping

    def tearDown(self):
        self.ctx.close()

    def test_backup_then_restore(self):
        b = self.sk.backup("manual")
        self.assertTrue(b.exists())
        meta = json.loads(b.with_suffix(".json").read_text("utf-8"))
        self.assertEqual((meta["reason"], meta["items"]), ("manual", 5))
        self.ctx.storage.delete_bookmark(self.ids[0])
        self.ctx.storage.conn.commit()
        self.assertEqual(self.ctx.storage.count(), 4)
        safety = self.sk.restore(b)
        self.assertEqual(self.ctx.storage.count(), 5)                   # back
        self.assertIn("before-restore", safety.name)
        self.assertEqual(json.loads(safety.with_suffix(".json").read_text("utf-8"))["items"], 4)
        self.assertEqual(len(self.ctx.snippets.for_bookmark(self.ids[0])), 1)
        self.assertTrue(self.ctx.search.search("Dravidian"))           # index restored too

    def test_remove_then_undo_brings_back_page_and_quotes(self):
        path = Path(self.ctx.storage.get_archive(self.ids[1])["path"])
        r = self.ctx.removal.remove_many([self.ids[1]])
        self.assertEqual(r.removed, 1)
        self.assertFalse(path.exists())
        self.assertTrue((self.sk.removed / path.name).exists())          # set aside
        b = self.sk.last_safety("before-remove")
        self.assertIsNotNone(b)
        self.sk.restore(b.path)
        self.assertIsNotNone(self.ctx.storage.get(self.ids[1]))
        self.assertTrue(path.exists())                                   # file moved back
        self.assertIn("Brahui 1", self.ctx.archive.read_html(self.ids[1]))
        self.assertEqual(len(self.ctx.snippets.for_bookmark(self.ids[1])), 1)

    def test_damaged_backup_changes_nothing(self):
        bad = self.tmp / "bad.db"
        bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
        with self.assertRaises(Exception):
            self.sk.restore(bad)
        self.assertEqual(self.ctx.storage.count(), 5)

    def test_merge_makes_a_safety_copy(self):
        self.ctx.storage.upsert_bookmark(Bookmark(url="https://example.org/0", title="dup",
                                                  date_added=1, browser="Chrome"))
        self.ctx.storage.conn.commit()
        self.ctx.curation.merge_all()
        self.assertIsNotNone(self.sk.last_safety("before-merge"))

    def test_daily_once(self):
        self.assertIsNotNone(self.sk.daily_if_due())
        self.assertIsNone(self.sk.daily_if_due())

    def test_old_copies_thin_out_yours_stay(self):
        now = int(time.time())
        day = 86400

        def fake(reason, age_days, i):
            p = self.sk.dir / f"chronos-fake{i:03d}-{reason}.db"
            self.sk.dir.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")
            p.with_suffix(".json").write_text(json.dumps(
                {"created": now - int(age_days * day), "reason": reason, "items": 1}))
        for d in range(60):                       # two months of daily copies
            fake("daily", d + 0.5, d)
        fake("manual", 400, 100)
        for i in range(15):
            fake("before-remove", i, 200 + i)
        self.sk.prune(now)
        left = self.sk.list()
        daily = [b for b in left if b.reason == "daily"]
        self.assertLessEqual(len(daily), 7 + 4 + 1)
        self.assertTrue(any(now - b.created < day for b in daily))         # yesterday kept
        self.assertFalse(any(now - b.created > 40 * day for b in daily))   # old ones go
        self.assertEqual(len([b for b in left if b.reason == "manual"]), 1)
        self.assertEqual(len([b for b in left if b.reason == "before-remove"]), 10)

    def test_full_backup_restores_into_a_new_place(self):
        z = self.sk.full_backup(self.tmp / "usb")
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
        self.assertIn("bookmarks.db", names)
        self.assertEqual(len([n for n in names if n.startswith("archives/")]), 5)
        t2, ctx2 = _ctx()
        try:
            ctx2.safekeeping.restore(z)
            self.assertEqual(ctx2.storage.count(), 5)
            self.assertIn("Brahui 3", ctx2.archive.read_html(self.ids[3]) or
                          ctx2.archive.read_html(ctx2.storage.get_by_url("https://example.org/3").id))
        finally:
            ctx2.close()

    def test_compact_gives_space_back(self):
        for i in range(300):
            self.ctx.storage.upsert_bookmark(Bookmark(
                url=f"https://big.example/{i}", title="x", date_added=1, browser="F",
                page_text="Brahui " * 400))
        self.ctx.storage.conn.commit()
        big = [b.id for b in self.ctx.storage.bookmarks_by_domain("big.example", 1000)]
        self.ctx.removal.remove_many(big, safety_copy=False)
        self.assertGreater(self.sk.compact(), 100_000)

    def test_usage(self):
        u = self.sk.usage()
        self.assertEqual(u["saved_count"], 5)
        self.assertGreater(u["database"], 0)
        self.assertEqual(u["per_site"][0][0], "example.org")


class UpgradeTest(unittest.TestCase):
    def test_a_copy_before_every_upgrade(self):
        from chronos.core import migrations
        from chronos.core.storage import Storage
        tmp = Path(tempfile.mkdtemp()).resolve()
        db = tmp / "bookmarks.db"
        con = sqlite3.connect(db); con.row_factory = sqlite3.Row
        migrations.get_db_version(con)
        for v, fn in sorted(migrations.MIGRATIONS, key=lambda m: m[0]):
            if v > 9:
                break
            fn(con); migrations.set_db_version(con, v)
        con.execute("INSERT INTO bookmarks (browser,title,url,date_added,year,month) "
                    "VALUES ('F','kept','https://kept.org',1,2023,1)")
        con.commit(); con.close()
        s = Storage(db)
        s.close()
        copies = list((tmp / "backups").glob("*before-upgrade.db"))
        self.assertEqual(len(copies), 1)
        old = sqlite3.connect(copies[0])
        self.assertEqual(old.execute("SELECT version FROM schema_version").fetchone()[0], 9)
        self.assertEqual(old.execute("SELECT title FROM bookmarks").fetchone()[0], "kept")
        old.close()
        Storage(db).close()                                     # already current: no copy
        self.assertEqual(len(list((tmp / "backups").glob("*before-upgrade.db"))), 1)


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.ctx = _ctx()
        self.ids = _fill(self.ctx)
        self.sk = self.ctx.safekeeping

    def tearDown(self):
        self.ctx.close()

    def test_healthy(self):
        r = self.sk.check(deep=True)
        self.assertTrue(r.ok, r.text())
        self.assertIn("each one read and verified", r.text())

    def test_search_index_out_of_step_is_rebuilt(self):
        c = self.ctx.storage.conn
        row = c.execute("SELECT id, title, url, page_text FROM bookmarks LIMIT 1").fetchone()
        c.execute("INSERT INTO bookmarks_fts(bookmarks_fts, rowid, title, url, page_text) "
                  "VALUES('delete', ?, ?, ?, ?)", tuple(row))
        c.commit()
        r = self.sk.check()
        self.assertTrue(r.fts_bad)
        self.assertTrue(r.repairable)
        done = self.sk.repair(r)
        self.assertIn("The search index was rebuilt.", done)
        self.assertTrue(self.sk.check().ok)
        self.assertIsNotNone(self.sk.last_safety("before-repair"))

    def test_missing_damaged_and_unused_files(self):
        a = Path(self.ctx.storage.get_archive(self.ids[0])["path"])
        b = Path(self.ctx.storage.get_archive(self.ids[1])["path"])
        self.sk.set_aside(a)                                   # missing, but recoverable
        with gzip.open(b, "wb") as f:                          # damaged
            f.write(b"something else entirely")
        stray = self.ctx.archive.dir / "deadbeef.html.gz"      # nothing uses it
        stray.write_bytes(gzip.compress(b"x"))
        r = self.sk.check(deep=True)
        self.assertEqual(r.missing_files, [self.ids[0]])
        self.assertEqual(r.damaged_files, [self.ids[1]])
        self.assertEqual([p.name for p in r.orphan_files], ["deadbeef.html.gz"])
        self.assertIn("can be brought back", r.text())
        self.sk.repair(r)
        self.assertTrue(a.exists())                            # brought back
        self.assertFalse(stray.exists())
        self.assertTrue((self.sk.removed / "deadbeef.html.gz").exists())   # aside, not deleted

    def test_clearing_removed_files(self):
        self.ctx.removal.remove_many([self.ids[2]])
        self.assertEqual(self.sk.empty_removed(30), 0)          # too recent
        self.assertEqual(self.sk.empty_removed(None), 1)


try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait(self, cond, secs=20):
        t = time.time()
        while not cond() and time.time() - t < secs:
            self.app.processEvents(); time.sleep(0.02)

    def test_your_archive_window(self):
        from chronos.gui.archive_dialog import ArchiveDialog
        tmp, ctx = _ctx()
        try:
            ids = _fill(ctx)
            ctx.takeaways.add(ids[0], "remember this")
            d = ArchiveDialog(ctx)
            o = d.overview_data
            self.assertEqual((o["items"], o["offline"], o["quotes"], o["takeaways"]), (5, 5, 5, 1))
            self.assertEqual([r[0] for r in d.ch_tags.rows], ["brahui"])
            self.assertEqual(d.usage_data["saved_count"], 5)
            d._backup()
            self.assertIn("Yours", d.backups.item(0).text())
            d._check(False)
            self._wait(lambda: "healthy" in d.health.toPlainText())
            self.assertIn("Everything checked is healthy.", d.health.toPlainText())
            ctx.storage.delete_bookmark(ids[4]); ctx.storage.conn.commit()
            seen = []
            d.restored.connect(lambda: seen.append(1))
            d._do_restore(str(ctx.safekeeping.list()[0].path))
            self.assertEqual(ctx.storage.count(), 5)
            self.assertEqual(seen, [1])
        finally:
            ctx.close()

    def test_undo_after_removing(self):
        from chronos.gui.main_window import MainWindow
        tmp, ctx = _ctx()
        try:
            ids = _fill(ctx)
            w = MainWindow(ctx)
            ctx.removal.remove_many(ids[:2])
            w._offer_undo("Removed 2 items.", "before-remove")
            self.assertIsNotNone(w._undo_btn)
            w._undo_btn.click()
            self.assertEqual(ctx.storage.count(), 5)
            self.assertIsNone(w._undo_btn)
        finally:
            ctx.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
