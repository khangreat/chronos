"""Multi-script / long-page extraction stress, baked into the suite.

Asserts what the builtin extractor genuinely does: recovers article text across
scripts (RTL + CJK), strips semantic boilerplate (nav/header/footer/aside), and
survives very long pages. Generic ad <div>s are a known builtin limitation
(that's what the optional trafilatura extractor is for) and are NOT asserted away.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chronos.web.extract import extract_content  # noqa: E402


def _page(script_body: str, title: str, site: str) -> str:
    return (f"<html><head><title>{title}</title>"
            f"<meta property='og:site_name' content='{site}'></head><body>"
            "<nav>Home About Sections Login SUBSCRIBE</nav>"
            "<header>Top banner navigation</header>"
            "<aside>Related links sidebar promo</aside>"
            f"<article>{script_body}</article>"
            "<footer>Copyright terms privacy cookies</footer>"
            "<script>var ads = loadAds();</script></body></html>")


BRAHUI = _page("<h1>سرخی</h1><p>ای براہوئی متن انا، خبر نا اصل حصہ.</p>"
               "<p>دومی پیراگراف انا ٹیسٹ واسطہ.</p>", "براہوئی خبر", "تلار")
ARABIC = _page("<h1>عنوان</h1><p>هذا هو النص العربي الأساسي للمقالة.</p>",
               "مقالة", "الجزيرة")
JAPANESE = _page("<h1>見出し</h1><p>これは記事の本文です。重要な内容。</p>",
                 "ニュース記事", "日本ニュース")
LONG = _page("".join(f"<p>Paragraph number {i} with meaningful body content "
                     f"about the subject at hand.</p>" for i in range(600)),
             "Very long article", "Longform")


class MultiScriptTest(unittest.TestCase):
    def _check_strips_boilerplate(self, page):
        t = page.text.lower()
        self.assertNotIn("subscribe", t)          # nav
        self.assertNotIn("top banner", t)         # header
        self.assertNotIn("related links", t)      # aside
        self.assertNotIn("copyright terms", t)    # footer
        self.assertNotIn("loadads", t)            # script

    def test_brahui_rtl(self):
        p = extract_content(BRAHUI, "https://talar.example/a")
        self.assertEqual(p.site_name, "تلار")
        self.assertIn("براہوئی", p.text)          # article body recovered
        self._check_strips_boilerplate(p)

    def test_arabic_rtl(self):
        p = extract_content(ARABIC, "https://ar.example/a")
        self.assertIn("النص العربي", p.text)
        self._check_strips_boilerplate(p)

    def test_japanese_cjk(self):
        p = extract_content(JAPANESE, "https://jp.example/a")
        self.assertIn("記事の本文", p.text)
        self.assertEqual(p.title, "ニュース記事")
        self._check_strips_boilerplate(p)

    def test_long_page(self):
        p = extract_content(LONG, "https://long.example/a")
        self.assertIn("Paragraph number 599", p.text)   # reached the end
        self.assertGreater(len(p.text), 20_000)         # substantial recovery
        self._check_strips_boilerplate(p)

    def test_no_crash_on_malformed(self):
        # unclosed tags, stray entities, mixed scripts
        junk = "<html><body><article><p>ok &amp; بلا <b>bold text</p></article>"
        p = extract_content(junk, "https://x/y")
        self.assertIn("ok", p.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
