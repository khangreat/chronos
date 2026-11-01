"""v0.31 "Selection & AI": context packs, the OpenAI-compatible client against a
real local HTTP server, the policy gates (local vs other computers), multi-select
and bulk actions, and the Ask AI window.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chronos.ai import client  # noqa: E402
from chronos.ai.pack import build_messages, build_pack  # noqa: E402
from chronos.core.context import ApplicationContext  # noqa: E402
from chronos.core.models import Bookmark  # noqa: E402
from chronos.net.policy import NetworkDisabled, NetworkPolicy  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:
    _HAS_QT = False


class FakeAI:
    """An OpenAI-compatible server on 127.0.0.1 that records requests."""
    def __init__(self, models=("tiny-model",), answer="**Answer** about [1] and [2]."):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)

            def do_GET(self):
                outer.requests.append(("GET", self.path, dict(self.headers), None))
                if self.path.endswith("/models"):
                    self._send(200, {"data": [{"id": m} for m in models]})
                else:
                    self._send(404, {"error": {"message": "no route"}})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(("POST", self.path, dict(self.headers), body))
                if body.get("model") == "missing":
                    self._send(404, {"error": {"message": "model 'missing' not found"}})
                    return
                self._send(200, {"choices": [{"message": {"role": "assistant",
                                                          "content": answer}}]})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()


def seed(ctx):
    ids = []
    for i, (t, text) in enumerate((
            ("Brahui retroflex consonants", "Brahui keeps retroflex consonants. " * 200),
            ("Balochi contact", "Loanwords from Balochi."),
            ("My own post", "A post with no web page."))):
        url = f"https://ex.org/{i}" if i < 2 else "fb-post://abc"
        bid, _ = ctx.storage.upsert_bookmark(Bookmark(
            url=url, title=t, date_added=1700000000 + i, browser="F", kind="article"))
        ctx.storage.conn.execute("UPDATE bookmarks SET page_text=? WHERE id=?", (text, bid))
        ids.append(bid)
    ctx.storage.conn.commit()
    ctx.snippets.capture(ids[0], "retroflex consonants")
    ctx.takeaways.add(ids[0], "Retroflex series marks the Dravidian link")
    return ids


class PackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_ai_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "h")
        self.ids = seed(self.ctx)

    def tearDown(self):
        self.ctx.close()

    def test_numbered_with_your_words_before_text(self):
        p = build_pack(self.ctx, self.ids)
        md = p.markdown
        self.assertIn("## [1] Brahui retroflex consonants", md)
        self.assertIn("## [3] My own post", md)
        self.assertLess(md.index("Your quotes:"), md.index("Text:"))
        self.assertIn("> retroflex consonants", md)
        self.assertIn("- Retroflex series marks the Dravidian link", md)
        self.assertIn("- Link: https://ex.org/0", md)
        self.assertNotIn("fb-post://", md)            # no fake link for export items

    def test_budget_shares_text(self):
        p = build_pack(self.ctx, self.ids, budget=3000)
        self.assertTrue(p.truncated)
        self.assertIn("[…]", p.markdown)
        self.assertIn("Loanwords from Balochi.", p.markdown)   # short item untouched
        self.assertLess(len(p.markdown), 6000)

    def test_question_needed_for_own_question(self):
        p = build_pack(self.ctx, self.ids[:1])
        with self.assertRaises(ValueError):
            build_messages("question", p, "  ")
        msgs = build_messages("summarise", p, "focus on phonology")
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("focus on phonology", msgs[1]["content"])
        self.assertIn("## [1]", msgs[1]["content"])


class StyleGuardTest(unittest.TestCase):
    def test_reader_text_has_no_box(self):
        # v0.31 regression: a QTextEdit rule boxed the reader (QTextBrowser)
        from chronos.gui.theme.tokens import DUSK, build_qss
        qss = build_qss(DUSK)
        self.assertNotRegex(qss, r"QTextEdit\s*[{,]")

    def test_checkboxes_visible(self):
        from chronos.gui.theme.tokens import THEMES, build_qss
        for t in THEMES.values():
            qss = build_qss(t)
            self.assertIn("QCheckBox::indicator {", qss)
            self.assertIn(f"border: 1px solid {t['text_muted']}", qss)


class PolicyTest(unittest.TestCase):
    def test_local_needs_only_ai_switch(self):
        from chronos.core.config import Settings
        s = Settings()
        self.assertFalse(NetworkPolicy(s).is_allowed("ai_local"))
        s.allow_ai = True
        self.assertTrue(NetworkPolicy(s).is_allowed("ai_local"))     # no master switch
        self.assertFalse(NetworkPolicy(s).is_allowed("ai_remote"))

    def test_remote_needs_three_switches(self):
        from chronos.core.config import Settings
        for net, ai, remote, ok in ((1, 1, 0, False), (0, 1, 1, False),
                                    (1, 0, 1, False), (1, 1, 1, True)):
            s = Settings(network_enabled=bool(net), allow_ai=bool(ai),
                         allow_ai_remote=bool(remote))
            self.assertEqual(NetworkPolicy(s).is_allowed("ai_remote"), ok)

    def test_endpoint_classification(self):
        self.assertTrue(client.is_local("http://localhost:11434/v1"))
        self.assertTrue(client.is_local("http://127.0.0.1:1234/v1"))
        self.assertFalse(client.is_local("https://api.example.com/v1"))
        self.assertFalse(client.is_local("http://localhost.evil.com/v1"))


class ClientTest(unittest.TestCase):
    def setUp(self):
        from chronos.core.config import Settings
        self.ai = FakeAI()
        self.s = Settings(allow_ai=True, ai_endpoint=self.ai.url)

    def tearDown(self):
        self.ai.close()

    def test_chat_round_trip_and_model_autopick(self):
        out = client.chat(self.s, NetworkPolicy(self.s),
                          [{"role": "user", "content": "hi"}])
        self.assertEqual(out, "**Answer** about [1] and [2].")
        methods = [(m, p) for m, p, _, _ in self.ai.requests]
        self.assertEqual(methods, [("GET", "/v1/models"), ("POST", "/v1/chat/completions")])
        self.assertEqual(self.ai.requests[1][3]["model"], "tiny-model")

    def test_key_sent_as_bearer(self):
        s = replace(self.s, ai_model="m", ai_api_key="sk-test")
        client.chat(s, NetworkPolicy(s), [{"role": "user", "content": "x"}])
        self.assertEqual(self.ai.requests[-1][2].get("Authorization"), "Bearer sk-test")

    def test_ai_off_sends_nothing(self):
        s = replace(self.s, allow_ai=False)
        with self.assertRaises(NetworkDisabled):
            client.chat(s, NetworkPolicy(s), [{"role": "user", "content": "x"}])
        self.assertEqual(self.ai.requests, [])

    def test_remote_blocked_without_switches(self):
        s = replace(self.s, ai_endpoint="https://api.example.invalid/v1", ai_model="m")
        with self.assertRaises(NetworkDisabled) as e:
            client.chat(s, NetworkPolicy(s), [{"role": "user", "content": "x"}])
        self.assertIn("other computer", str(e.exception))

    def test_errors_are_plain(self):
        s = replace(self.s, ai_model="missing")
        with self.assertRaises(client.AIError) as e:
            client.chat(s, NetworkPolicy(s), [{"role": "user", "content": "x"}])
        self.assertIn("not found", str(e.exception).lower())
        port = self.ai.httpd.server_address[1]
        self.ai.close()
        s = replace(self.s, ai_endpoint=f"http://127.0.0.1:{port}/v1", ai_model="m")
        with self.assertRaises(client.AIError) as e:
            client.chat(s, NetworkPolicy(s), [{"role": "user", "content": "x"}])
        self.assertIn("No AI is answering", str(e.exception))
        self.ai = FakeAI()          # for tearDown

    def test_local_calls_bypass_system_proxy(self):
        old = {k: os.environ.get(k) for k in ("HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy")}
        os.environ["HTTP_PROXY"] = os.environ["http_proxy"] = "http://127.0.0.1:9"
        os.environ.pop("NO_PROXY", None); os.environ.pop("no_proxy", None)
        try:
            s = replace(self.s, ai_model="m")
            self.assertTrue(client.chat(s, NetworkPolicy(s), [{"role": "user", "content": "x"}]))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


@unittest.skipUnless(_HAS_QT, "PySide6 not installed")
class GuiSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chronos_sel_"))
        self.ctx = ApplicationContext.for_dir(self.tmp / "h")
        self.ids = seed(self.ctx)
        self.ai = FakeAI()

    def tearDown(self):
        self.ai.close()
        self.ctx.close()

    def _win(self):
        from chronos.gui.main_window import MainWindow
        w = MainWindow(self.ctx); w.resize(1280, 800); w.show()
        self.app.processEvents()
        w._show_period(2023, 11)
        return w

    def _select(self, w, n):
        from PySide6.QtCore import QItemSelectionModel
        m, sm = w.stream.model, w.stream.view.selectionModel()
        rows = [r for r in range(m.rowCount()) if m.bookmark_at(r)][:n]
        for r in rows:
            sm.select(m.index(r, 0), QItemSelectionModel.Select)
        self.app.processEvents()
        return [m.bookmark_at(r).id for r in rows]

    def test_multi_select_and_bar(self):
        w = self._win()
        chosen = self._select(w, 2)
        self.assertEqual(w.stream.selected_ids(), chosen)
        self.assertTrue(w.stream.selbar.isVisible())
        self.assertIn("2 selected", w.stream.sel_label.text())

    def test_copy_for_ai(self):
        from PySide6.QtGui import QGuiApplication
        w = self._win(); self._select(w, 2)
        w._selection_action("copy_ai")
        clip = QGuiApplication.clipboard().text()
        self.assertIn("## [1]", clip); self.assertIn("## [2]", clip)

    def test_bulk_favourite_and_tag(self):
        from unittest import mock
        w = self._win(); chosen = self._select(w, 2)
        w._selection_action("favorite")
        self.assertTrue(all(self.ctx.storage.get(i).is_favorite for i in chosen))
        with mock.patch("chronos.gui.main_window.QInputDialog.getText",
                        return_value=("Phonology", True)):
            w._selection_action("tag")
        self.assertTrue(all("phonology" in self.ctx.storage.get(i).tags for i in chosen))

    def test_export_selected_only(self):
        bms = [self.ctx.storage.get(i) for i in self.ids[:2]]
        out = json.loads(self.ctx.export.export("json", bms))
        self.assertEqual(len(out), 2)

    def test_ask_ai_dialog_and_keep(self):
        from chronos.gui.ai_dialog import AskAIDialog
        self.ctx.config._settings = replace(self.ctx.config.settings, allow_ai=True,
                                            ai_endpoint=self.ai.url, ai_model="m")
        self.ctx.network.settings = self.ctx.config._settings
        d = AskAIDialog(self.ctx, self.ids[:2], sync=True)
        d.ask()
        self.assertIn("Answer", d.answer.toPlainText())
        sent = self.ai.requests[-1][3]["messages"][1]["content"]
        self.assertIn("Brahui retroflex consonants", sent)
        self.assertIn("Retroflex series marks", sent)          # your takeaway went along
        self.assertEqual(d.keep_as_takeaway(), 2)
        kept = self.ctx.takeaways.for_bookmark(self.ids[1])
        self.assertTrue(kept and kept[-1].text.startswith("[AI · Summarise]"))

    def test_answer_references_open_items(self):
        from PySide6.QtCore import QUrl
        from chronos.gui.ai_dialog import AskAIDialog, link_references
        self.assertEqual(link_references("see [2] not [7]", 3),
                         "see [\\[2\\]](chronos-item:2) not [7]")
        d = AskAIDialog(self.ctx, self.ids[:2], sync=True)
        d._done("Compare [1] with [2].")
        hits = []
        d.open_item.connect(hits.append)
        d._on_link(QUrl("chronos-item:2"))
        self.assertEqual(hits, [d.pack.ids[1]])

    def test_ask_ai_off_explains(self):
        from chronos.gui.ai_dialog import AskAIDialog
        d = AskAIDialog(self.ctx, self.ids[:1], sync=True)
        self.assertFalse(d.ask_btn.isEnabled())
        self.assertIn("Copy for AI", d.status.text())
        self.assertEqual(self.ai.requests, [])

    def test_ctrl_a_in_search_selects_text_not_list(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        w = self._win()
        w.search.setText("brahui"); w.search.setFocus(); self.app.processEvents()
        QTest.keyClick(w.search, Qt.Key_A, Qt.ControlModifier)
        self.assertEqual(w.search.selectedText(), "brahui")
        self.assertEqual(w.stream.selected_count(), 0)

    def test_settings_dialog_keeps_ai_fields(self):
        from chronos.gui.settings_dialog import SettingsDialog
        st = replace(self.ctx.config.settings, allow_ai=True, ai_model="llama3.2",
                     ai_endpoint="http://localhost:1234/v1", text_size="large")
        d = SettingsDialog(st)
        out = d.result_settings()
        self.assertEqual((out.allow_ai, out.ai_model, out.ai_endpoint, out.text_size),
                         (True, "llama3.2", "http://localhost:1234/v1", "large"))
        self.assertEqual(d.ai_preset.currentText(), "LM Studio on this computer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
