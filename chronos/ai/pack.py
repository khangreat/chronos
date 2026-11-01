"""Context packs — selected archive items, ready for any AI.

A pack is plain Markdown: each item numbered [1], [2]… with its title, link,
what it is and when, how it reached your archive, your tags, quotes and
takeaways, then its text. Your own words (quotes you chose, takeaways you wrote)
come before the page text because they say what mattered to you.

Text is shared out across the items within a size budget, so ten long articles
don't crowd out a short post. The same pack is used for Copy for AI, Save for
AI, and Ask AI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ..services.describe import byline_for, provenance_sentences

DEFAULT_BUDGET = 24_000       # characters of page text across all items

TASKS: Dict[str, str] = {
    "summarise": "Summarise these items. Give the main points of each, then what "
                 "they say together.",
    "compare": "Compare these items: where they agree, where they differ, and what "
               "each adds that the others don't.",
    "claims": "List the key claims made in these items, each with the item number "
              "it comes from. Note which claims are supported by evidence in the "
              "text and which are only asserted.",
    "connections": "What connects these items? Point out shared themes, people, "
                   "places, sources or arguments, and anything that contradicts.",
    "translate": "Translate the text of these items into clear English, keeping "
                 "the item numbers. Keep names and quoted terms as they are, with "
                 "a transliteration where useful.",
    "question": "",
}

TASK_LABELS: Dict[str, str] = {
    "summarise": "Summarise", "compare": "Compare", "claims": "Key claims",
    "connections": "Find connections", "translate": "Translate to English",
    "question": "Ask your own question",
}

SYSTEM = ("You help the user think with items from their personal archive. The "
          "items are numbered [1], [2] and so on. Refer to them by number. Base your "
          "answer on what the items say; if they don't contain the answer, say so "
          "plainly. “Your quotes” and “Your takeaways” were chosen or "
          "written by the user.")


@dataclass
class Pack:
    markdown: str
    ids: List[int]
    truncated: bool


def _is_web(url: str) -> bool:
    return (url or "").startswith(("http://", "https://"))


def build_pack(ctx, ids: List[int], budget: int = DEFAULT_BUDGET) -> Pack:
    items = [b for b in (ctx.storage.get(i) for i in ids) if b is not None]
    if not items:
        return Pack("", [], False)
    share = max(400, budget // len(items))
    truncated = False
    parts = [f"# {len(items)} item{'s' if len(items) != 1 else ''} from my archive\n"]
    for n, b in enumerate(items, 1):
        lines = [f"## [{n}] {b.title or b.url}"]
        if _is_web(b.url):
            lines.append(f"- Link: {b.url}")
        lines.append(f"- {byline_for(b)}")
        try:
            trail = provenance_sentences(ctx.provenance.for_bookmark(b.id))
        except Exception:
            trail = []
        if trail:
            lines.append("- In my archive: " + "; ".join(trail))
        if b.tags:
            lines.append("- Tags: " + ", ".join(b.tags))
        quotes = ctx.snippets.for_bookmark(b.id)
        if quotes:
            lines.append("\nYour quotes:")
            lines += [f"> {q.quote.strip()}" for q in quotes]
        takeaways = ctx.takeaways.for_bookmark(b.id)
        if takeaways:
            lines.append("\nYour takeaways:")
            lines += [f"- {t.text.strip()}" for t in takeaways]
        text = (b.page_text or b.excerpt or "").strip()
        if text:
            if len(text) > share:
                cut = text.rfind(" ", 0, share)
                text = text[:cut if cut > share // 2 else share].rstrip() + " […]"
                truncated = True
            lines.append("\nText:\n" + text)
        parts.append("\n".join(lines))
    return Pack("\n\n".join(parts) + "\n", [b.id for b in items], truncated)


def build_messages(task: str, pack: Pack, question: str = "") -> List[dict]:
    ask = question.strip() if task == "question" else TASKS.get(task, "")
    if task != "question" and question.strip():
        ask += "\n\nAlso: " + question.strip()
    if not ask:
        raise ValueError("Write a question to ask about these items.")
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"{ask}\n\n---\n\n{pack.markdown}"}]
