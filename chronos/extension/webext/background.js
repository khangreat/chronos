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

// --- Reddit: your saved, upvoted, posts and comments, read while you're logged
// in. Runs in the reddit.com tab you're on (same site, your own session — no
// API key, no server), a page of 100 at a time, about one page a second.
// Reddit lists at most ~1000 of each. "Fill in" completes the bare links that
// Reddit's data download gives (titles, text, authors).
const REDDIT = ["https://www.reddit.com/*", "https://old.reddit.com/*"];

async function readReddit(mode, wanted) {
  const base = location.origin;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const get = async (path) => {
    const r = await fetch(base + path, { credentials: "include",
                                         headers: { Accept: "application/json" } });
    if (r.status === 429) { await sleep(10000); return get(path); }
    if (!r.ok) throw new Error(`Reddit answered ${r.status} for ${path}`);
    return r.json();
  };
  const send = (role, data) => chrome.runtime.sendMessage(
    { type: "chronos_reddit", role: role, data: data });
  let me;
  try { me = await get("/api/me.json"); } catch (e) { me = null; }
  const name = me && (me.name || (me.data && me.data.name));
  if (!name) return { ok: false, error: "Log in to Reddit in this browser first." };
  let read = 0, fresh = 0;
  if (mode === "fill") {
    for (let i = 0; i < wanted.length; i += 100) {
      const data = await get("/api/info.json?raw_json=1&id=" + wanted.slice(i, i + 100).join(","));
      const r = await send("fill", data);
      if (r && r.ok) { read += r.read || 0; fresh += r.new || 0; }
      chrome.runtime.sendMessage({ type: "chronos_progress", n: read });
      await sleep(1100);
    }
    return { ok: true, read: read, new: fresh };
  }
  for (const role of ["saved", "upvoted", "submitted", "comments"]) {
    let after = "";
    for (let page = 0; page < 12; page++) {
      let data;
      try {
        data = await get(`/user/${encodeURIComponent(name)}/${role}.json?limit=100&raw_json=1` +
                         (after ? `&after=${after}` : ""));
      } catch (e) { break; }            // e.g. upvoted hidden: go on with the rest
      const kids = (data && data.data && data.data.children) || [];
      if (!kids.length) break;
      const r = await send(role, data);
      if (r && r.ok) { read += r.read || 0; fresh += r.new || 0; }
      chrome.runtime.sendMessage({ type: "chronos_progress", n: read });
      after = data.data.after;
      if (!after) break;
      await sleep(1100);
    }
  }
  return { ok: true, read: read, new: fresh, name: name };
}

function badge(text, ok) {
  chrome.action.setBadgeText({ text: text });
  chrome.action.setBadgeBackgroundColor({ color: ok ? "#3E7A5E" : "#B04A3A" });
}

function native(msg) {
  return new Promise((resolve) => chrome.runtime.sendNativeMessage(HOST, msg, (resp) => {
    resolve(chrome.runtime.lastError ? { ok: false, error: chrome.runtime.lastError.message }
                                     : resp);
  }));
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === "chronos_reddit") {
    native({ type: "reddit_listing", role: msg.role, data: msg.data }).then(reply);
    return true;                        // answer asynchronously
  }
  if (msg && msg.type === "chronos_progress") {
    badge(String(msg.n > 999 ? Math.floor(msg.n / 1000) + "k" : msg.n), true);
  }
  return false;
});

async function redditRun(tab, mode) {
  if (!tab || !tab.id) return;
  let wanted = [];
  if (mode === "fill") {
    const w = await native({ type: "reddit_wanted" });
    wanted = (w && w.ids) || [];
    if (!wanted.length) { badge("0", true); setTimeout(() => badge("", true), 4000); return; }
  }
  badge("\u2026", true);
  let res;
  try {
    const [r] = await chrome.scripting.executeScript(
      { target: { tabId: tab.id }, func: readReddit, args: [mode, wanted] });
    res = r.result;
  } catch (e) { res = { ok: false, error: String(e) }; }
  if (res && res.ok) {
    badge("\u2713" + (res.read || 0), true);
    chrome.action.setTitle({ title: `Chronos: ${res.read || 0} Reddit items read, ${res.new || 0} new` });
  } else {
    badge("!", false);
    chrome.action.setTitle({ title: "Chronos: " + ((res && res.error) || "Reddit couldn't be read") });
  }
  setTimeout(() => badge("", true), 15000);
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "save-to-chronos",
    title: "Save to Chronos",
    contexts: ["page", "selection", "link"]
  });
  chrome.contextMenus.create({
    id: "reddit-all",
    title: "Chronos: bring in my Reddit saved, upvoted, posts and comments",
    contexts: ["page"], documentUrlPatterns: REDDIT
  });
  chrome.contextMenus.create({
    id: "reddit-fill",
    title: "Chronos: fill in titles and text for my Reddit data download",
    contexts: ["page"], documentUrlPatterns: REDDIT
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "reddit-all") return redditRun(tab, "all");
  if (info.menuItemId === "reddit-fill") return redditRun(tab, "fill");
  return capture(tab);
});
