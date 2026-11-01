// Save to Chronos — background service worker (MV3).
// On toolbar click or context menu, extract the specific post/page under the
// selection and hand it to the local Chronos native host. No servers involved.

const HOST = "com.chronos.capture";

// Runs in the page. Mirrors the bookmarklet: best-effort permalink for the post
// nearest the selection, plus the selection and title.
function extract() {
  const sel = window.getSelection ? window.getSelection().toString() : "";
  let url = location.href, sp = "";
  try {
    let n = window.getSelection().anchorNode;
    let e = n && n.nodeType === 3 ? n.parentElement : n;
    while (e) {
      const a = e.querySelector &&
        e.querySelector("a[href*='/status/'],a[href*='/comments/']");
      if (a) { url = a.href; sp = location.href; break; }
      e = e.parentElement;
    }
  } catch (x) {}

  // best-ref metadata: Open Graph / Twitter card / <meta>, then JSON-LD
  const M = (q) => { const el = document.querySelector(q);
                     return el ? el.getAttribute("content") : ""; };
  let author = M("meta[name='author']") || M("meta[property='article:author']");
  let site = M("meta[property='og:site_name']");
  let desc = M("meta[property='og:description']") ||
             M("meta[name='twitter:description']") || M("meta[name='description']");
  let published = M("meta[property='article:published_time']") || M("meta[name='date']");
  const title = M("meta[property='og:title']") ||
                M("meta[name='twitter:title']") || document.title;
  try {
    document.querySelectorAll("script[type='application/ld+json']").forEach((s) => {
      const d = JSON.parse(s.textContent);
      const arr = Array.isArray(d) ? d : (d["@graph"] || [d]);
      arr.forEach((nd) => {
        if (!nd || typeof nd !== "object") return;
        if (!author && nd.author)
          author = typeof nd.author === "object" ? (nd.author.name || "") : nd.author;
        if (!published && nd.datePublished) published = nd.datePublished;
        if (!site && nd.publisher && nd.publisher.name) site = nd.publisher.name;
      });
    });
  } catch (e) {}

  return {
    type: "capture",
    url: url, title: title, selection: sel, source_page: sp,
    author: author, site_name: site, description: desc, published: published,
    captured_at: Math.floor(Date.now() / 1000)
  };
}

async function capture(tab) {
  if (!tab || !tab.id) return;
  let cap;
  try {
    const [res] = await chrome.scripting.executeScript(
      { target: { tabId: tab.id }, func: extract });
    cap = res.result;
  } catch (e) {
    cap = { type: "capture", url: tab.url, title: tab.title,
            captured_at: Math.floor(Date.now() / 1000) };
  }
  chrome.runtime.sendNativeMessage(HOST, cap, (resp) => {
    const ok = !chrome.runtime.lastError && resp && resp.ok;
    chrome.action.setBadgeText({ text: ok ? "\u2713" : "!" });
    chrome.action.setBadgeBackgroundColor(
      { color: ok ? "#3E7A5E" : "#B04A3A" });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2500);
  });
}

chrome.action.onClicked.addListener(capture);

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "save-to-chronos",
    title: "Save to Chronos",
    contexts: ["page", "selection", "link"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => capture(tab));
