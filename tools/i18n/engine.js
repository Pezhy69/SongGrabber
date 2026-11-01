/* SongGrabber – English translation of the German interface.
   Generated from tools/i18n (see README there). German stays the source language:
   every German text in index.html / app.js is looked up here and replaced when English is active. */
"use strict";
const I18N = (() => {
  const EN = /*DICT*/{};
  const PATS = /*PATS*/[].map(([re, to]) => [new RegExp(re, "gu"), to]);
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE", "KBD", "INPUT"]);
  const ATTRS = ["title", "placeholder", "aria-label"];
  const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // Längere Bruchstücke zuerst, damit „Mikrofon an – …“ vor „Mikrofon“ greift
  const FR = Object.keys(EN).filter(k => k.length >= 8 && /\s/.test(k.trim())).sort((a, b) => b.length - a.length);
  const reFr = FR.length ? new RegExp(FR.map(reEsc).join("|"), "g") : null;
  const EDGE = /^([\s\d.,:;·()[\]+\-–—%/×✓★⏭⏮▶🔴🎤🎙…!?"„“”»«]*)([\s\S]*?)([\s\d.,:;·()[\]+\-–—%/×✓…!?"„“”»«]*)$/u;
  let lang = "de", sysLang = "", helpDe = null;

  function tr(s) {
    if (lang !== "en" || !s) return s;
    const t = s.trim();
    if (!t) return s;
    let r = EN[t];
    if (r === undefined) { const m = EDGE.exec(t); if (m && m[2] && EN[m[2]] !== undefined) r = m[1] + EN[m[2]] + m[3]; }
    if (r === undefined) {
      let x = t;
      for (const [re, to] of PATS) x = x.replace(re, to);
      if (reFr) x = x.replace(reFr, k => EN[k]);
      if (x !== t) r = x;
    }
    if (r === undefined) return s;
    return s === t ? r : s.replace(t, () => r);
  }

  // ---- DOM: Originaltext merken, damit „Deutsch“ alles zurückholen kann
  const TXT = new WeakMap(), ATT = new WeakMap();
  function skip(el) {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      if (SKIP_TAGS.has(e.tagName) || e.namespaceURI === "http://www.w3.org/2000/svg" || e.hasAttribute("data-noi18n")) return true;
    }
    return false;
  }
  function doText(n) {
    const v = n.nodeValue, rec = TXT.get(n);
    if (rec && v === rec[1]) { if (lang !== "en") { n.nodeValue = rec[0]; TXT.delete(n); } return; }
    if (lang !== "en" || !/[A-Za-zÄÖÜäöüß]/.test(v) || skip(n.parentElement)) { TXT.delete(n); return; }
    const out = tr(v);
    if (out !== v) { TXT.set(n, [v, out]); n.nodeValue = out; } else TXT.delete(n);
  }
  function doAttr(el, a) {
    const v = el.getAttribute(a);
    let m = ATT.get(el); const rec = m && m[a];
    if (v == null) { if (rec) delete m[a]; return; }
    if (rec && v === rec[1]) { if (lang !== "en") { el.setAttribute(a, rec[0]); delete m[a]; } return; }
    if (lang !== "en" || el.hasAttribute("data-noi18n") || skip(el.parentElement)) { if (rec) delete m[a]; return; }
    const out = tr(v);
    if (out !== v) { if (!m) ATT.set(el, m = {}); m[a] = [v, out]; el.setAttribute(a, out); } else if (rec) delete m[a];
  }
  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) return doText(root);
    if (root.nodeType !== 1 && root.nodeType !== 11) return;
    if (root.nodeType === 1) { if (root.tagName === "SCRIPT" || root.tagName === "STYLE") return; ATTRS.forEach(a => root.hasAttribute(a) && doAttr(root, a)); }
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      if (n.nodeType === 3) doText(n);
      else ATTRS.forEach(a => n.hasAttribute(a) && doAttr(n, a));
    }
  }
  const mo = new MutationObserver(list => {
    if (lang !== "en") return;
    for (const m of list) {
      if (m.type === "childList") m.addedNodes.forEach(walk);
      else if (m.type === "characterData") doText(m.target);
      else if (m.type === "attributes") doAttr(m.target, m.attributeName);
    }
  });

  // ---- Hilfe: ganze Artikel tauschen (eigene englische Fassung im <template id="helpEn">)
  function swapHelp() {
    const body = document.getElementById("helpBody"), tpl = document.getElementById("helpEn");
    if (!body || !tpl) return;
    const arts = [...body.querySelectorAll("article")].filter(a => a.id !== "h-new");
    if (!helpDe) { helpDe = {}; arts.forEach(a => { helpDe[a.id] = a.innerHTML; a.setAttribute("data-noi18n", ""); }); }
    arts.forEach(a => {
      const en = tpl.content.getElementById(a.id);
      a.innerHTML = lang === "en" && en ? en.innerHTML : helpDe[a.id];
    });
    document.querySelectorAll("#helpToc a").forEach(x => {
      const a = document.getElementById(x.dataset.id), h = a && a.querySelector("h2");
      if (h && a.id !== "h-new") x.textContent = h.textContent;
    });
  }

  function resolve(pref) { return pref === "de" || pref === "en" ? pref : (sysLang || ((navigator.language || "de").toLowerCase().startsWith("de") ? "de" : "en")); }
  function set(pref, sys) {
    if (sys) sysLang = sys;
    const next = resolve(pref || "auto");
    try { localStorage.setItem("sg_lang", next); } catch (e) { /* egal */ }
    if (next === lang && document.documentElement.lang === lang) return;
    lang = next;
    document.documentElement.lang = lang;
    if (document.body) { walk(document.body); swapHelp(); }
    window.dispatchEvent(new CustomEvent("langchange", { detail: lang }));
  }
  function start() {
    let first = "";
    try { first = localStorage.getItem("sg_lang") || ""; } catch (e) { /* egal */ }
    lang = "de";
    mo.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    set(first || "auto");
  }
  // native Rückfragen (confirm/alert) ebenfalls übersetzen
  const _confirm = window.confirm.bind(window), _alert = window.alert.bind(window);
  window.confirm = m => _confirm(tr(String(m)));
  window.alert = m => _alert(tr(String(m)));
  return { tr, set, start, get lang() { return lang; }, EN };
})();
const T = s => I18N.tr(s);
