/* SongGrabber – Oberfläche */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = s => { if (!isFinite(s)) return ""; s = Math.max(0, Math.round(s || 0)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0"); };
const fmtClock = s => { s = Math.floor(s || 0); return [s / 3600, s % 3600 / 60, s % 60].map(v => String(Math.floor(v)).padStart(2, "0")).join(":"); };

const S = { presets: [], settings: {}, link: null, cd: null, cdCover: null, files: [], rec: { mode: "vinyl", state: "idle" }, jobs: [], seenDone: new Set(), first: true };

/* ---------------------------------------------------------------- API */
let booted = false;
async function call(name, ...args) {
  const api = window.pywebview && window.pywebview.api;
  if (api && api[name]) return await api[name](...args);
  if (Mock[name]) return await Mock[name](...args);
  throw new Error("Funktion nicht verfügbar: " + name);
}
async function safe(btn, fn) {
  if (btn) btn.classList.add("busy");
  try { return await fn(); }
  catch (e) { toast(String(e && e.message || e).replace(/^Error:\s*/, ""), "err"); }
  finally { if (btn) btn.classList.remove("busy"); }
}
function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.transition = ".3s"; t.style.opacity = 0; setTimeout(() => t.remove(), 300); }, kind === "err" ? 6500 : 3800);
}

/* ---------------------------------------------------------------- Navigation */
function go(page) {
  $$(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.page === page));
  $$(".page").forEach(p => p.classList.toggle("active", p.id === "page-" + page));
  if (page === "cd" && !$("#cdDrive").options.length) loadDrives();
  if (page === "rec") { if (!$("#recDevice").options.length) loadDevices(); else monitorLoop(); }
  if (page === "settings") refreshTools();
  if (page === "library") loadLibrary();
  if (page === "abos") loadAbos();
  document.body.classList.toggle("pp-active", page === "player");
  if (page === "player") { Viz.start(); SysMode.resume(); if (SysMode.on()) SysMode.lyrics(true); else if (!$("#ppLyBody").hidden) { LY.path = ""; loadLyrics(Player.lyricsTrack()); } }
  if (page === "radio") loadRadio();
  if (page === "screen") Scr.enter();
}
$$(".nav-item").forEach(b => b.onclick = () => go(b.dataset.page));

/* ---------------------------------------------------------------- Ausgabe-Leiste */
function presetFmt(id) { return (S.presets.find(p => p.id === id) || {}).fmt || "MP3"; }
function fillPresets(fmt, keep) {
  const sel = $("#presetSel");
  sel.innerHTML = S.presets.filter(p => p.fmt === fmt).map(p => `<option value="${p.id}">${fmt} · ${esc(p.label)}</option>`).join("");
  if (keep && [...sel.options].some(o => o.value === keep)) sel.value = keep;
  $$("#fmtSeg button").forEach(b => b.classList.toggle("active", b.dataset.fmt === fmt));
}
$$("#fmtSeg button").forEach(b => b.onclick = () => { fillPresets(b.dataset.fmt); save({ preset: $("#presetSel").value }); });
$("#presetSel").onchange = e => save({ preset: e.target.value });
$("#normSel").onchange = e => save({ normalize: e.target.value });
$("#btnOutPick").onclick = () => pickFolder("output_dir");
$("#btnOutOpen").onclick = () => call("open_path", S.settings.output_dir);
$("#btnOpenOut").onclick = () => call("open_path", S.settings.output_dir);

async function save(patch) {
  S.settings = await call("save_settings", patch);
  renderSettings();
}
async function pickFolder(key) {
  const p = await call("choose_folder");
  if (p) await save({ [key]: p });
}

/* ---------------------------------------------------------------- Einstellungen */
function renderSettings() {
  const s = S.settings;
  $("#outPath").textContent = s.output_dir || "–";
  $("#normSel").value = s.normalize || "off";
  $("#setOut").value = s.output_dir || "";
  $("#setWatch").value = s.watch_dir || "";
  $("#setTools").value = s.tools_dir || "";
  $("#setLayout").value = Object.entries(LAYOUTS).find(([, v]) => v[0] === s.name_single && v[1] === s.name_album)?.[0] || "custom";
  $$("[data-key]").forEach(el => {
    if (el.type === "checkbox") el.checked = !!s[el.dataset.key];
    else if (document.activeElement !== el) el.value = s[el.dataset.key] ?? "";
  });
  namePreview();
}
$$("[data-key]").forEach(el => {
  el.addEventListener(el.type === "checkbox" ? "change" : "input", () => {
    clearTimeout(el._t);
    el._t = setTimeout(() => save({ [el.dataset.key]: el.type === "checkbox" ? el.checked : el.value }), el.type === "checkbox" ? 0 : 400);
    if (el.type !== "checkbox") namePreview();
  });
});
$$("[data-pick]").forEach(b => b.onclick = () => pickFolder({ setOut: "output_dir", setWatch: "watch_dir", setTools: "tools_dir" }[b.dataset.pick]));
$("#btnToolsReset").onclick = async () => { await save({ tools_dir: "" }); refreshTools(); };
const LAYOUTS = {
  artist_album: ["{albumartist}/{album}/{track:02} - {title}", "{albumartist}/{album}/{track:02} - {title}"],
  artist: ["{artist}/{artist} - {title}", "{albumartist}/{album}/{track:02} - {title}"],
  flat: ["{artist} - {title}", "{albumartist} - {album}/{track:02} - {title}"],
  genre: ["{genre}/{albumartist}/{album}/{track:02} - {title}", "{genre}/{albumartist}/{album}/{track:02} - {title}"],
};
$("#setLayout").onchange = async e => { if (e.target.value !== "custom") { S.settings = await call("set_layout", e.target.value); renderSettings(); toast("Ordnerstruktur gespeichert – gilt für neue Titel", "ok"); } };
$("#btnReorg").onclick = e => safe(e.currentTarget, async () => {
  const plan = await call("lib_reorganize", false);
  if (!plan.count) return toast("Alles ist bereits richtig einsortiert.", "ok");
  const ex = plan.preview.slice(0, 3).map(p => `• ${p.from}\n   → ${p.to}`).join("\n");
  if (!confirm(`${plan.count} Datei(en) werden verschoben, z. B.:\n\n${ex}\n\nPlaylists werden automatisch angepasst. Fortfahren?`)) return;
  const r = await call("lib_reorganize", true);
  toast(`${r.count} Datei(en) neu einsortiert` + (r.errors.length ? ` · ${r.errors.length} Fehler` : ""), r.errors.length ? "err" : "ok");
});
function namePreview() {
  const ex = { artist: "Adele", title: "Rolling in the Deep", album: "21", albumartist: "Adele", track: 1, date: "2011", genre: "Pop" };
  const fmt = (t, e) => t.replace(/\{(\w+)(?::0?(\d+))?\}/g, (_, k, w) => k === "track" ? String(e.track).padStart(+w || 1, "0") : (e[k] ?? "Unbekannt"));
  const ext = (S.presets.find(p => p.id === S.settings.preset) || { ext: "mp3" }).ext;
  const single = { ...ex, title: "Hello", album: "Singles", track: 0 };
  const sing = fmt($("#setNameSingle").value || "", single).replace(/(^|\/)0+\s*[-.–]\s*/, "$1");
  $("#namePreview").innerHTML = `<b>Mit Album:</b> ${esc(fmt($("#setNameAlbum").value || "", ex))}.${ext}<br><b>Ohne Album:</b> ${esc(sing)}.${ext}`;
}
$("#btnDiag").onclick = e => safe(e.currentTarget, async () => { const t = await call("diagnose"); copyText(t); toast("Fehlerbericht kopiert – jetzt einfach einfügen und verschicken", "ok"); });
$("#btnLog").onclick = () => call("log_open");
$("#btnLicenses").onclick = () => call("open_licenses");
window.addEventListener("error", e => { try { call("log_js", `${e.message} @ ${(e.filename || "").split("/").pop()}:${e.lineno}`); } catch (x) { } });
window.addEventListener("unhandledrejection", e => { try { call("log_js", "Promise: " + (e.reason && e.reason.message || e.reason)); } catch (x) { } });
$("#btnYtUpdate").onclick = e => safe(e.currentTarget, async () => { const r = await call("ytdlp_update"); toast(r, "ok"); refreshTools(); });
async function refreshTools() {
  const i = await call("init");
  const t = i.tools;
  $("#tFf").className = t.ffmpeg && t.ffprobe ? "ok" : "";
  $("#tYt").className = t.ytdlp ? "ok" : "";
  $("#tFfV").textContent = t.ffmpeg ? (t.ffmpeg_version || "gefunden") : "fehlt – ffmpeg.exe in den Ordner bin legen";
  $("#tYtV").textContent = t.ytdlp ? (t.ytdlp_version || "gefunden") : "fehlt – yt-dlp.exe in den Ordner bin legen";
  const st = $("#toolsState");
  const ok = t.ffmpeg && t.ffprobe;
  st.className = "tools-state " + (ok ? "ok" : "bad");
  st.querySelector("span").textContent = ok ? "LAME-Encoder bereit" : "ffmpeg fehlt";
  call("output_check").then(o => { if (o && !o.ok) toast(o.error, "err"); }).catch(() => { });
  setTimeout(() => checkUpdate(false), 5000);
  return i;
}

/* ---------------------------------------------------------------- Links */
$("#btnPaste").onclick = async () => { const t = await call("get_clipboard"); if (t) { $("#urlInput").value = t; analyze(); } else toast("Zwischenablage ist leer."); };
$("#urlInput").addEventListener("keydown", e => { if (e.key === "Enter") analyze(); });
$("#urlInput").addEventListener("paste", () => setTimeout(() => { if (/^https?:\/\//i.test($("#urlInput").value.trim())) analyze(); }, 30));
$("#btnAnalyze").onclick = analyze;

async function analyze() {
  const url = $("#urlInput").value.trim();
  if (!url) return toast("Bitte zuerst einen Link einfügen.");
  await safe($("#btnAnalyze"), async () => {
    $("#linkEmpty").hidden = true;
    const r = $("#linkResult");
    r.hidden = false; r.style.opacity = .55;
    $("#resThumb").classList.add("skeleton");
    const info = await call("link_analyze", url);
    S.link = info; renderLink(info);
  });
  $("#linkResult").style.opacity = 1;
  $("#resThumb").classList.remove("skeleton");
  if (!S.link) { $("#linkResult").hidden = true; $("#linkEmpty").hidden = false; }
}
function renderLink(info) {
  const pl = info.type === "playlist", live = info.is_live || info.type === "stream";
  $("#resThumb").style.backgroundImage = info.thumb ? `url("${info.thumb}")` : "";
  $("#resThumb").innerHTML = info.duration ? `<span class="dur">${fmtTime(info.duration)}</span>` : "";
  $("#resTitle").textContent = info.title;
  $("#resSub").textContent = [info.uploader, info.extractor, pl ? info.count + " Titel" : ""].filter(Boolean).join(" · ") || info.url;
  $("#resBadges").innerHTML = (pl ? `<span class="tag acc">Playlist</span>` : "") + (live ? `<span class="tag live">● Live</span>` : "") + (!pl && !live ? `<span class="tag ok">Bereit</span>` : "");
  $("#resArtist").value = info.artist || (pl ? info.uploader || "" : "");
  $("#resTrack").value = info.track || "";
  $("#resAlbum").value = pl ? info.title : (info.album || "");
  $("#resGenre").value = info.genre || "";
  $("#resYear").value = info.date || "";
  $("#resNo").value = info.track_no || "";
  $("#resTrackWrap").hidden = $("#resYearWrap").hidden = $("#resNoWrap").hidden = pl;
  $("#resAlbum").placeholder = $("#resGenre").placeholder = pl ? "wird je Titel automatisch gesucht" : "nicht gefunden – optional";
  const mf = $("#resMeta");
  mf.hidden = !info.meta_source;
  if (info.meta_source) {
    mf.innerHTML = (info.cover_url ? `<img src="${esc(info.cover_url.replace("1000x1000", "200x200"))}" alt="">` : "") +
      `<div><b>✓ Musikdaten gefunden</b> über ${esc(info.meta_source)}<br>${esc([info.album, info.date, info.genre].filter(Boolean).join(" · "))}</div>`;
    if (info.cover_url && S.settings.prefer_album_cover !== false) $("#resThumb").style.backgroundImage = `url("${info.cover_url.replace("1000x1000", "600x600")}")`;
  }
  $("#plWrap").hidden = !pl;
  showLive(info);
  showChapters(info);
  $("#streamOpts").hidden = $("#btnStreamStart").hidden = !live;
  $("#btnDownload").hidden = info.type === "stream" || info.is_live;
  $("#streamNameIn").value = live ? (info.uploader || info.title || "") : "";
  if (pl) {
    $("#plList").innerHTML = info.entries.map((e, i) => `<label class="pl-row"><span class="check"><input type="checkbox" data-i="${i}" checked><span></span></span><span class="n">${String(i + 1).padStart(2, "0")}</span><span class="t" title="${esc(e.title)}">${esc(e.title)}</span><span class="d">${e.duration ? fmtTime(e.duration) : ""}</span></label>`).join("");
    $("#plAll").checked = true; plCount();
    $$("#plList input").forEach(c => c.onchange = plCount);
  }
}
function plCount() {
  const n = $$("#plList input:checked").length;
  $("#plCount").textContent = `${n} von ${S.link.entries.length} ausgewählt`;
  $("#btnDownload").textContent = n ? `${n} Titel herunterladen & umwandeln` : "Nichts ausgewählt";
  $("#btnDownload").disabled = !n;
}
$("#plAll").onchange = e => { $$("#plList input").forEach(c => c.checked = e.target.checked); plCount(); };
$("#btnDownload").onclick = e => safe(e.currentTarget, async () => {
  const L = S.link; if (!L) return;
  const opts = { artist: $("#resArtist").value.trim(), album: $("#resAlbum").value.trim(), genre: $("#resGenre").value.trim(), as_album: $("#plAsAlbum").checked, playlist_title: L.title };
  let items;
  if (L.type === "playlist") {
    items = $$("#plList input:checked").map(c => L.entries[+c.dataset.i]);
    if (!opts.as_album) opts.album = opts.album === L.title ? "" : opts.album;
    if (opts.artist === (L.uploader || "")) opts.artist = "";
  } else {
    items = [{ url: L.url, title: L.title, uploader: L.uploader, artist: opts.artist, title_override: $("#resTrack").value.trim() }];
    opts.single = { date: $("#resYear").value.trim(), track: $("#resNo").value.trim(), disc: L.disc || "", album_artist: L.album_artist || "", cover_url: L.cover_url || "", meta_source: L.meta_source || "" };
    if (!$("#chapBox").hidden && $("#chapOn").checked) {
      opts.single.chapters = $$("#chapList .chap-row").map((r, i) => ({ ...L.chapters[i], title: r.querySelector("input").value.trim() || L.chapters[i].title }));
      opts.single.track = "";
      items[0].title = `${opts.artist || L.artist} – ${opts.album || L.chapter_album} (${opts.single.chapters.length} Titel)`;
    }
  }
  const ids = await call("link_download", items, opts);
  toast(`${ids.length} ${ids.length === 1 ? "Auftrag" : "Aufträge"} in der Warteschlange`, "ok");
  $("#urlInput").value = ""; $("#urlInput").focus();
});
$("#btnStreamStart").onclick = e => safe(e.currentTarget, async () => {
  await call("stream_start", S.link.url, $("#streamNameIn").value.trim(), +$("#streamMin").value || 0);
  toast("Mitschnitt läuft", "ok");
});
$("#btnStreamStop").onclick = () => call("stream_stop");

/* ---------------------------------------------------------------- Audio-CD */
async function loadDrives() {
  await safe($("#btnCdDrives"), async () => {
    const d = await call("cd_drives");
    $("#cdDrive").innerHTML = d.length ? d.map(x => `<option value="${esc(x.letter)}">${x.letter.startsWith("/") ? `${esc(x.label || "CD/DVD-Laufwerk")} (${esc(x.letter)})` : `Laufwerk ${x.letter}:${x.label ? " · " + esc(x.label) : ""}`}</option>`).join("") : `<option value="">Kein CD/DVD-Laufwerk gefunden</option>`;
  });
}
$("#btnCdDrives").onclick = loadDrives;
$("#btnCdEject").onclick = e => safe(e.currentTarget, () => call("cd_eject", $("#cdDrive").value));
$("#btnCdImage").onclick = e => safe(e.currentTarget, async () => { const p = await call("cd_open_image"); if (p) await openCdImage(p); });
async function openCdImage(p) {
  const sel = $("#cdDrive"); [...sel.options].filter(o => o.value.toLowerCase().endsWith(".cue")).forEach(o => o.remove());
  sel.insertAdjacentHTML("afterbegin", `<option value="${esc(p)}">Abbild: ${esc(p.split(/[\\/]/).pop())}</option>`); sel.value = p;
  await readCd(p);
}
$("#btnCdTest").onclick = e => safe(e.currentTarget, async () => {
  toast("Test-CD wird erzeugt …");
  const p = await call("cd_make_test");
  const sel = $("#cdDrive"); [...sel.options].filter(o => o.value.toLowerCase().endsWith(".cue")).forEach(o => o.remove());
  sel.insertAdjacentHTML("afterbegin", `<option value="${esc(p)}">Abbild: Test-CD</option>`); sel.value = p;
  await readCd(p);
});
$("#btnCdRead").onclick = e => safe(e.currentTarget, async () => {
  const L = $("#cdDrive").value; if (!L) return toast("Kein Laufwerk gefunden – du kannst ein CD-Abbild öffnen.", "err");
  await readCd(L);
});
$("#cdDrive").onchange = () => { $("#btnCdEject").disabled = $("#cdDrive").value.toLowerCase().endsWith(".cue"); };
async function readCd(L) {
  $("#btnCdEject").disabled = L.toLowerCase().endsWith(".cue");
  const d = await call("cd_read", L);
  S.cd = d; S.cdCover = null; renderCd(0);
  if (d.releases.length) toast(`Gefunden: ${d.releases[0].artist} – ${d.releases[0].album}`, "ok");
  else if (d.cdtext && (d.cdtext.album || d.cdtext.artist)) toast("Titel aus dem CD-Text übernommen", "ok");
  else toast(d.lookup_error || "Diese CD ist bei MusicBrainz nicht bekannt – bitte Titel eintragen.");
}
function renderCd(relIdx) {
  const d = S.cd, rel = d.releases[relIdx] || null;
  $("#cdEmpty").hidden = true; $("#cdView").hidden = false;
  const ct = d.cdtext || {}, ctt = ct.tracks || {};
  $("#cdArtist").value = rel ? rel.artist : (ct.artist || ""); $("#cdAlbum").value = rel ? rel.album : (ct.album || "");
  $("#cdYear").value = rel ? (rel.date || "").slice(0, 4) : (ct.date || ""); if (!rel) $("#cdGenre").value = ct.genre || "";
  $("#cdReleaseWrap").hidden = d.releases.length < 2;
  $("#cdRelease").innerHTML = d.releases.map((r, i) => `<option value="${i}">${esc(r.album)} · ${esc(r.date || "?")} ${esc(r.country || "")} ${r.label ? "· " + esc(r.label) : ""}</option>`).join("");
  $("#cdRelease").value = relIdx;
  const cov = S.cdCover || (rel && rel.cover_url) || "";
  $("#cdCover").style.backgroundImage = cov ? `url("${cov}")` : "";
  $("#cdCover").classList.toggle("empty-cover", !cov);
  if (rel && rel.cover_url && !S.cdCover) {
    const img = new Image();
    img.onerror = () => { if (rel.rg_cover) { $("#cdCover").style.backgroundImage = `url("${rel.rg_cover}")`; rel.cover_url = rel.rg_cover; } else { rel.cover_url = ""; $("#cdCover").style.backgroundImage = ""; $("#cdCover").classList.add("empty-cover"); } };
    img.src = rel.cover_url;
  }
  const total = d.tracks.reduce((a, t) => a + t.seconds, 0);
  $("#cdBadges").innerHTML = (d.image ? `<span class="tag acc">CD-Abbild</span>` : "") + (rel ? `<span class="tag ok">MusicBrainz ✓</span>` : (ct.album || ct.artist) ? `<span class="tag ok">CD-Text</span>` : `<span class="tag warn">Manuell</span>`) + `<span class="tag">${d.tracks.length} Titel</span><span class="tag">${fmtTime(total)}</span>` + (rel && rel.disc ? `<span class="tag acc">Disc ${rel.disc}</span>` : "") + `<span class="tag" title="Disc-ID">${esc(d.discid)}</span>`;
  $("#cdTracks").innerHTML = d.tracks.map((t, i) => {
    const c = ctt[t.n] || {}, rt = (rel && rel.tracks[i]) || (c.title ? { title: c.title, artist: c.artist && c.artist !== ct.artist ? c.artist : "" } : null);
    return `<div class="trow cd-cols" data-i="${i}"><label class="check"><input type="checkbox" checked><span></span></label><span class="n">${String(t.n).padStart(2, "0")}</span><input class="tt" value="${esc(rt ? rt.title : "Titel " + String(t.n).padStart(2, "0"))}"><input class="ta" value="${esc(rt ? rt.artist : "")}" placeholder="wie Album"><span class="d">${fmtTime(t.seconds)}</span></div>`;
  }).join("");
  $$("#cdTracks input[type=checkbox]").forEach(c => c.onchange = cdSummary);
  $("#cdAll").checked = true; cdSummary();
}
$("#cdRelease").onchange = e => renderCd(+e.target.value);
$("#cdAll").onchange = e => { $$("#cdTracks input[type=checkbox]").forEach(c => c.checked = e.target.checked); cdSummary(); };
function cdSummary() {
  const rows = $$("#cdTracks .trow");
  let n = 0, sec = 0;
  rows.forEach(r => { const on = r.querySelector("input[type=checkbox]").checked; r.classList.toggle("off", !on); if (on) { n++; sec += S.cd.tracks[+r.dataset.i].seconds; } });
  const fmt = presetFmt(S.settings.preset);
  const mb = fmt === "MP3" ? sec * 0.031 : fmt === "FLAC" ? sec * 0.105 : sec * 0.176;
  $("#cdSummary").textContent = `${n} von ${rows.length} Titeln · ${fmtTime(sec)} · ca. ${Math.round(mb)} MB als ${fmt}`;
  $("#btnCdRip").disabled = !n;
}
$("#btnCdCopyArtist").onclick = () => $$("#cdTracks .ta").forEach(i => i.value = $("#cdArtist").value);
$("#cdCover").onclick = async () => { if (!S.cd) return; const p = await call("choose_image"); if (p) { S.cdCover = p; $("#cdCover").style.backgroundImage = `url("file:///${p.replace(/\\/g, "/")}")`; $("#cdCover").classList.remove("empty-cover"); } };
$("#btnCdRip").onclick = e => safe(e.currentTarget, async () => {
  const d = S.cd, rel = d.releases[+$("#cdRelease").value || 0];
  const album = { artist: $("#cdArtist").value.trim(), album: $("#cdAlbum").value.trim(), date: $("#cdYear").value.trim(), genre: $("#cdGenre").value.trim(), cover_url: S.cdCover ? "" : (rel ? rel.cover_url : ""), cover_file: S.cdCover || "", disc: rel ? rel.disc : "", track_total: d.tracks.length };
  const tracks = $$("#cdTracks .trow").filter(r => r.querySelector("input[type=checkbox]").checked).map(r => {
    const t = d.tracks[+r.dataset.i];
    return { n: t.n, start: t.start, end: t.end, title: r.querySelector(".tt").value.trim(), artist: r.querySelector(".ta").value.trim() };
  });
  await call("cd_rip", d.letter, album, tracks);
  toast(`${tracks.length} Titel werden gerippt`, "ok"); go("queue");
});

/* ---------------------------------------------------------------- Aufnahme */
const MODES = {
  vinyl: { wait: true, split: true, stop: true, vinyl: true, sys: false, fmt: "48000/24", thr: "-45" },
  tape: { wait: true, split: true, stop: true, vinyl: false, sys: false, fmt: "48000/24", thr: "-40" },
  system: { wait: false, split: false, stop: false, vinyl: false, sys: true, fmt: "48000/24", thr: "-50" },
  mic: { wait: false, split: false, stop: false, vinyl: false, sys: false, fmt: "48000/24", thr: "-45" },
};
$$("#recModes .mode").forEach(b => b.onclick = () => setMode(b.dataset.mode));
function setMode(m) {
  S.rec.mode = m; const c = MODES[m];
  $$("#recModes .mode").forEach(b => b.classList.toggle("active", b.dataset.mode === m));
  $("#recWait").checked = c.wait; $("#recSplit").checked = c.split; $("#recAutoStop").checked = c.stop; $("#recVinyl").checked = c.vinyl;
  $("#recFmt").value = c.fmt; $("#recThr").value = c.thr;
  const sel = $("#recDevice"), opts = [...sel.options], ins = opts.filter(o => o.dataset.loop !== "1");
  let want;
  if (c.sys) want = opts.find(o => o.dataset.loop === "1" && o.dataset.def === "1") || opts.find(o => o.dataset.loop === "1");
  else if (m === "mic") want = ins.find(o => o.dataset.def === "1" && !/line|stereo ?mix|wave|was du hörst/i.test(o.textContent)) || ins.find(o => /mikro|mic|headset|webcam/i.test(o.textContent)) || ins.find(o => o.dataset.def === "1") || ins[0];
  else want = ins.find(o => /line|eingang|input|phono|usb audio codec/i.test(o.textContent) && !/mikro|mic/i.test(o.textContent)) || ins.find(o => o.dataset.def === "1") || ins[0];
  if (want) sel.value = want.value;
  renderInputs();
}
$("#recDevice").addEventListener("change", renderInputs);
async function loadDevices() {
  await safe($("#btnRecDevices"), async () => {
    const d = await call("rec_devices");
    const loop = d.filter(x => x.loopback), ins = d.filter(x => !x.loopback);
    const opt = x => `<option value="${esc(x.id)}" data-loop="${x.loopback ? 1 : 0}" data-def="${x.default ? 1 : 0}">${esc(x.name)}${x.default ? " (Standard)" : ""}</option>`;
    $("#recDevice").innerHTML = (ins.length ? `<optgroup label="Eingänge – Line-In, Plattenspieler, Mikrofon">${ins.map(opt).join("")}</optgroup>` : "") + (loop.length ? `<optgroup label="Systemsound (was der PC abspielt)">${loop.map(opt).join("")}</optgroup>` : "");
    S.rec.devices = d;
    setMode(S.rec.mode);
    monitorLoop();
  });
}
$("#btnRecDevices").onclick = loadDevices;
const gain = $("#recGain");
gain.oninput = () => {
  const v = +gain.value; $("#recGainV").textContent = (v > 0 ? "+" : "") + v.toFixed(1).replace(".", ",") + " dB";
  gain.style.setProperty("--p", ((v - gain.min) / (gain.max - gain.min) * 100) + "%");
  if (S.rec.state !== "idle") call("rec_gain", v);
};
gain.oninput();
$("#btnRec").onclick = e => {
  if (S.rec.state !== "idle") return stopRec();
  safe(null, async () => {
    const [sr, bits] = $("#recFmt").value.split("/").map(Number);
    if (!$("#recDevice").value) return toast("Keine Aufnahmequelle gefunden.", "err");
    await call("rec_start", {
      device: $("#recDevice").value, samplerate: sr, bitdepth: bits, gain_db: +gain.value,
      wait_signal: $("#recWait").checked, threshold_db: +$("#recThr").value,
      stop_silence: $("#recAutoStop").checked ? +$("#recStopSec").value : 0,
      auto_split: $("#recSplit").checked, split_pause: +$("#recSplitPause").value, split_db: +$("#recThr").value,
      vinyl_clean: $("#recVinyl").checked,
    });
    pollRec();
  });
};
function recMeta() { return { artist: $("#recArtist").value.trim(), album: $("#recAlbum").value.trim(), title: $("#recAlbum").value.trim(), year: $("#recYear").value.trim(), genre: $("#recGenre").value.trim() }; }
function stopRec() { call("rec_stop", recMeta()).then(() => toast("Aufnahme wird gespeichert …", "ok")); }
$("#btnRecStop").onclick = stopRec;
$("#btnRecPause").onclick = () => call("rec_pause");
$("#btnRecDiscard").onclick = () => { if (confirm("Aufnahme wirklich verwerfen?")) call("rec_discard"); };

let recTimer = null;
function pollRec() {
  clearTimeout(recTimer);
  call("rec_status").then(st => {
    drawRec(st);
    if (st.error) toast("Aufnahme: " + st.error, "err");
    if (st.state !== "idle") recTimer = setTimeout(pollRec, 70);
    else if (S.rec.state !== "idle") { S.rec.state = "idle"; drawRec(st); monitorLoop(); }
  }).catch(() => { recTimer = setTimeout(pollRec, 400); });
}
const STATE_TXT = { idle: "Bereit", armed: "Wartet auf Signal …", recording: "Aufnahme", paused: "Pause", finishing: "Speichern …" };
function drawRec(st) {
  S.rec.state = st.state;
  const active = st.state !== "idle" && st.state !== "finishing";
  $("#recState").textContent = STATE_TXT[st.state] || st.state;
  $("#recLed").className = "led " + st.state;
  $("#recTimer").textContent = fmtClock(st.elapsed);
  $("#btnRec").classList.toggle("on", active);
  $("#btnRec").title = active ? "Stopp & speichern" : "Aufnahme starten";
  $("#btnRecStop").disabled = $("#btnRecPause").disabled = !active;
  $("#btnRecDiscard").hidden = !active;
  $("#navRecDot").classList.toggle("on", active);
  $("#recClip").hidden = !st.clips;
  if (active && st.zero > 2.5) showMicWarn("Es kommt kein Ton an – nur digitale Stille", S.rec.privacy === "deny" ? "Windows blockiert den Mikrofonzugriff für Desktop-Programme. Einstellung öffnen, Zugriff erlauben, Aufnahme neu starten." : "Falscher Eingang, Mikrofon stummgeschaltet oder von Windows blockiert. Rechts unter „Eingänge“ prüfen, welcher beim Sprechen ausschlägt.");
  else if (active && !S.rec.privacyShown) $("#micWarn").hidden = true;
  drawMeter($("#meterL"), st.peak[0], st.rms[0], 0); drawMeter($("#meterR"), st.peak[1], st.rms[1], 1);
  $("#meterLv").textContent = st.peak[0] <= -89 ? "-∞" : st.peak[0].toFixed(1);
  $("#meterRv").textContent = st.peak[1] <= -89 ? "-∞" : st.peak[1].toFixed(1);
  drawWave(st.wave || []);
}
const hold = [{ v: -90, t: 0 }, { v: -90, t: 0 }];
function dbPos(db) { // -60..0 dB → 0..1, unten gestaucht wie ein echtes VU
  const pts = [[-60, 0], [-40, .17], [-24, .38], [-12, .6], [-6, .75], [-3, .86], [0, 1]];
  if (db <= -60) return 0; if (db >= 0) return 1;
  for (let i = 1; i < pts.length; i++) if (db <= pts[i][0]) { const [a, pa] = pts[i - 1], [b, pb] = pts[i]; return pa + (db - a) / (b - a) * (pb - pa); }
  return 1;
}
function fitCanvas(c) { const r = c.getBoundingClientRect(), d = window.devicePixelRatio || 1; if (c.width !== Math.round(r.width * d)) { c.width = Math.round(r.width * d); c.height = Math.round(r.height * d); } return d; }
function drawMeter(c, peak, rms, i) {
  const d = fitCanvas(c), x = c.getContext("2d"), W = c.width, H = c.height;
  x.clearRect(0, 0, W, H);
  const segs = 64, gap = 2 * d, sw = (W - gap * (segs - 1)) / segs, p = dbPos(peak), r = dbPos(rms), now = performance.now();
  if (peak > hold[i].v || now - hold[i].t > 1400) { hold[i] = { v: peak, t: now }; }
  const hp = dbPos(hold[i].v);
  for (let s = 0; s < segs; s++) {
    const f = (s + .5) / segs, col = f > .86 ? "#FF3B4E" : f > .75 ? "#FFB547" : "#3DDC97";
    x.fillStyle = col; x.globalAlpha = f <= p ? (f <= r ? 1 : .55) : .09;
    x.fillRect(s * (sw + gap), 0, sw, H);
  }
  x.globalAlpha = 1;
  if (hp > 0) { x.fillStyle = "#fff"; x.fillRect(Math.min(W - 2 * d, hp * W - d), 0, 2 * d, H); }
}
function drawWave(w) {
  const c = $("#recWave"), d = fitCanvas(c), x = c.getContext("2d"), W = c.width, H = c.height, mid = H / 2;
  x.clearRect(0, 0, W, H);
  x.strokeStyle = "rgba(255,255,255,.06)"; x.lineWidth = d; x.beginPath(); x.moveTo(0, mid); x.lineTo(W, mid); x.stroke();
  if (!w.length) return;
  const n = Math.max(w.length, 300), bw = W / n;
  const g = x.createLinearGradient(0, 0, 0, H); g.addColorStop(0, "#FFB547"); g.addColorStop(.5, "#FF7A30"); g.addColorStop(1, "#FFB547");
  x.fillStyle = g;
  const off = n - w.length;
  w.forEach((v, i) => { const h = Math.max(1 * d, Math.min(1, v) * (H * .46)); x.globalAlpha = .35 + .65 * (i / w.length); x.fillRect((off + i) * bw, mid - h, Math.max(1, bw - d), h * 2); });
  x.globalAlpha = 1;
}

/* ---------------------------------------------------------------- Eingänge live */
let monT = null;
function showMicWarn(t, sub) { $("#micWarnT").textContent = t; $("#micWarnS").textContent = sub; $("#micWarn").hidden = false; }
$("#btnMicPriv").onclick = () => call("rec_privacy_settings");
function renderInputs() {
  const box = $("#recInputs"), d = S.rec.devices || [], cur = $("#recDevice").value;
  if (!d.length) { box.innerHTML = `<div class="muted" style="font-size:12.5px">Keine Eingänge gefunden.</div>`; return; }
  const ins = d.filter(x => !x.loopback), loops = d.filter(x => x.loopback).sort((a, b) => b.default - a.default);
  box.innerHTML = [...ins, ...loops].map(x => `<button class="inp ${x.loopback ? "loop" : ""} ${x.id === cur ? "sel" : ""}" data-id="${esc(x.id)}"><i class="dot"></i><span class="nm" title="${esc(x.name)}">${x.loopback ? "🔊 " : ""}${esc(x.loopback ? "Systemsound – " + x.name : x.name)}${x.default ? "<small>Standard</small>" : ""}</span><div class="lv"><div class="bar"><i></i><b></b></div><span class="st">…</span></div></button>`).join("");
  $$("#recInputs .inp").forEach(b => b.onclick = () => {
    const isLoop = b.classList.contains("loop");
    if (isLoop && S.rec.mode !== "system") setMode("system");
    else if (!isLoop && S.rec.mode === "system") { S.rec.mode = "mic"; $$("#recModes .mode").forEach(x => x.classList.toggle("active", x.dataset.mode === "mic")); }
    $("#recDevice").value = b.dataset.id; renderInputs();
  });
}
async function monitorLoop() {
  clearTimeout(monT);
  if (!$("#page-rec").classList.contains("active") || !S.rec.devices) return;
  if (S.rec.state === "idle") {
    try {
      const r = await call("rec_monitor");
      S.rec.privacy = r.privacy;
      if (r.privacy === "deny") { S.rec.privacyShown = true; showMicWarn("Windows blockiert den Mikrofonzugriff", "Unter Datenschutz ist „Desktop-Apps Zugriff auf das Mikrofon erlauben“ ausgeschaltet – deshalb kommt kein Ton an. Nach dem Einschalten SongGrabber neu starten."); }
      else if (!$("#micWarn").hidden) { S.rec.privacyShown = false; $("#micWarn").hidden = true; }
      const cur = $("#recDevice").value;
      $$("#recInputs .inp").forEach(b => {
        const isLoop = b.classList.contains("loop");
        const lv = r.levels[b.dataset.id], barBox = b.querySelector(".bar"), bar = barBox.querySelector("i"), hold = barBox.querySelector("b"), st = b.querySelector(".st");
        barBox.style.setProperty("--w", barBox.offsetWidth + "px");
        if (!lv) { st.textContent = "…"; st.className = "st"; return; }
        bar.style.width = (dbPos(lv.peak ?? -90) * 100) + "%"; hold.style.left = `calc(${dbPos(lv.hold ?? -90) * 100}% - 1px)`;
        let txt = "still", cls = "st";
        if (lv.state === "error") { txt = "nicht verfügbar"; cls = "st bad"; b.title = lv.error; }
        else if (isLoop && (lv.zero > 0.5 || lv.peak <= -60)) { txt = "spielt nichts"; cls = "st"; b.title = "Über dieses Ausgabegerät läuft gerade kein Ton"; }
        else if (lv.zero > 1.5) { txt = "stumm"; cls = "st bad"; b.title = "Liefert nur digitale Stille – stummgeschaltet, nicht angeschlossen oder von Windows blockiert"; }
        else if (lv.peak > -30) { txt = isLoop ? "Ton läuft ✓" : "Signal ✓"; cls = "st ok"; }
        else if (lv.peak > -60) { txt = "leise"; cls = "st warn"; }
        st.textContent = txt; st.className = cls;
        b.classList.toggle("hot", lv.peak > -30);
        if (b.dataset.id === cur) {
          drawMeter($("#meterL"), lv.peak, lv.rms, 0); drawMeter($("#meterR"), lv.peak, lv.rms, 1);
          $("#meterLv").textContent = $("#meterRv").textContent = lv.peak <= -89 ? "-∞" : lv.peak.toFixed(1);
        }
      });
    } catch (e) { }
  }
  monT = setTimeout(monitorLoop, 90);
}

/* ---------------------------------------------------------------- Bildschirm aufnehmen */
const Scr = (() => {
  let data = null, kind = "screen", src = null, devs = null, st = { state: "idle" }, view = "setup";
  let prevT = null, prevBusy = false, lvlT = null, pollT = null, discardArm = 0, barOn = false, crop = null;
  const active = () => $("#page-screen").classList.contains("active");
  const sep = () => (S.settings.output_dir || "").includes("\\") ? "\\" : "/";
  const db2w = v => Math.max(0, Math.min(100, ((v ?? -90) + 60) / 60 * 100));
  const opts = () => ({ source: src && src.id, sys_audio: $("#scrSys").checked, mic: $("#scrMic").checked, mic_device: $("#scrMicDev").value,
    fps: +$("#scrFps").value, quality: $("#scrQ").value, cursor: $("#scrCursor").checked, mp3: $("#scrMp3").checked, small: $("#scrSmall").checked, kind, crop });

  function applyOpts() {
    const o = S.settings.screen_opts || {};
    if (o.kind) kind = o.kind;
    if (o.sys_audio !== undefined) $("#scrSys").checked = !!o.sys_audio;
    if (o.mic !== undefined) $("#scrMic").checked = !!o.mic;
    if (o.fps) $("#scrFps").value = String(o.fps);
    if (o.quality) $("#scrQ").value = o.quality;
    if (o.cursor !== undefined) $("#scrCursor").checked = !!o.cursor;
    if (o.mp3 !== undefined) $("#scrMp3").checked = !!o.mp3;
    if (o.small !== undefined) $("#scrSmall").checked = !!o.small;
    if (o.crop) crop = o.crop;
  }
  async function remember() {
    const o = opts(); o.last = o.source; delete o.source;
    S.settings = await call("save_settings", { screen_opts: o });
  }

  async function enter() {
    $("#scrHint").hidden = !!S.settings.screen_hint_ok;
    try { st = await call("screen_status"); } catch { st = { state: "idle" }; }
    if (["recording", "paused"].includes(st.state)) { show("live"); renderLive(); startPoll(); return; }
    if (st.state === "finishing") { show("done"); renderDone(); startPoll(); return; }
    if (view === "done") { renderDone(); return; }
    show("setup");
    if (!data) { applyOpts(); await loadSources(); } else { renderList(); preview(true); }
    if (!devs) await loadDevs();
    loops();
  }
  function show(v) {
    view = v;
    $("#scrSetup").hidden = v !== "setup" || (data && !data.supported);
    $("#scrLive").hidden = v !== "live";
    $("#scrDone").hidden = v !== "done";
    if (v !== "setup") { clearTimeout(prevT); clearTimeout(lvlT); }
  }

  async function loadSources() {
    $("#scrList").innerHTML = `<div class="muted">Suche Bildschirme und Fenster …</div>`;
    data = await call("screen_sources");
    $("#scrOff").hidden = data.supported;
    $("#scrOffWhy").textContent = data.reason || "";
    if (!data.supported) { $("#scrSetup").hidden = true; return; }
    $("#scrSetup").hidden = view !== "setup";
    const last = (S.settings.screen_opts || {}).last;
    const all = [...data.screens, ...data.windows];
    src = all.find(x => x.id === (src && src.id)) || all.find(x => x.id === last) || null;
    if (!src) crop = null;
    if (src && kind !== "area") kind = src.id.startsWith("win:") ? "win" : "screen";
    pickDefault();
    renderList(); preview(true);
  }
  const itemsFor = k => k === "screen" ? data.screens : k === "win" ? data.windows : [...data.screens, ...data.windows.filter(w => !w.minimized)];
  function pickDefault() {
    const items = itemsFor(kind);
    if (src && items.some(x => x.id === src.id)) return;
    src = kind !== "win" ? (items.find(x => x.primary) || items[0] || null)
      : (items.find(x => !x.minimized && /zoom|teams|webex|meet|skype|discord|slack|jitsi/i.test(x.app + " " + x.title)) || items.find(x => !x.minimized) || items[0] || null);
  }
  function renderList() {
    $$("#scrKind button").forEach(b => b.classList.toggle("active", b.dataset.k === kind));
    $("#scrKindTip").textContent = kind === "screen"
      ? "Alles, was auf diesem Bildschirm zu sehen ist – auch Hinweise und andere Fenster."
      : kind === "win" ? "Nur dieses eine Fenster. Es darf verschoben werden, aber nicht minimiert sein."
      : "Wähle, worin der Bereich liegt – dann ziehst du ein Rechteck darum, z. B. nur um das Video in Zoom, Teams oder YouTube.";
    const items = itemsFor(kind);
    const box = $("#scrList");
    if (!items.length) { box.innerHTML = `<div class="muted" style="font-size:12.5px">${kind === "screen" ? "Kein Bildschirm gefunden." : "Keine offenen Fenster gefunden – starte zuerst Zoom, Teams oder das Programm, das du aufnehmen willst, und klicke dann auf „Neu suchen“."}</div>`; summary(); return; }
    const isScr = x => !x.id.startsWith("win:");
    box.innerHTML = items.map((x, i) => (kind === "area" && (i === 0 || isScr(items[i - 1]) !== isScr(x)) ? `<div class="scr-sec">${isScr(x) ? "Auf dem Bildschirm" : "In einem Fenster"}</div>` : "") + (isScr(x)
      ? `<button class="scr-src ${src && src.id === x.id ? "sel" : ""}" data-id="${esc(x.id)}"><span class="si">${esc(x.id.split(":")[1] * 1 + 1)}</span><span><b>${esc(x.name)}</b><small>${x.primary ? "Hauptbildschirm" : "weiterer Bildschirm"}</small></span><em>${esc(x.size)}</em></button>`
      : `<button class="scr-src ${src && src.id === x.id ? "sel" : ""} ${x.minimized ? "min" : ""}" data-id="${esc(x.id)}" title="${esc(x.title)}"><span class="si">${esc((x.app || "?").slice(0, 1).toUpperCase())}</span><span><b>${esc(x.title)}</b><small>${esc(x.app)}${x.minimized ? " · minimiert" : ""}</small></span><em>${x.w && x.h ? x.w + " × " + x.h : ""}</em></button>`)).join("");
    $$("#scrList .scr-src").forEach(b => b.onclick = () => {
      const nw = items.find(x => x.id === b.dataset.id);
      if (!src || nw.id !== src.id) crop = null;
      src = nw;
      $$("#scrList .scr-src").forEach(y => y.classList.toggle("sel", y === b));
      summary(); preview(true); remember();
      if (kind === "area") openCrop();
    });
    summary();
  }

  async function loadDevs() {
    try { devs = S.rec.devices || await call("rec_devices"); } catch { devs = []; }
    const mics = devs.filter(d => !d.loopback);
    const want = (S.settings.screen_opts || {}).mic_device;
    $("#scrMicDev").innerHTML = mics.length
      ? mics.map(d => `<option value="${esc(d.id)}">${esc(d.name)}${d.default ? " (Standard)" : ""}</option>`).join("")
      : `<option value="">Kein Mikrofon gefunden</option>`;
    const def = mics.find(d => d.id === want) || mics.find(d => d.default) || mics[0];
    if (def) $("#scrMicDev").value = def.id;
    audioRows();
  }
  function audioRows() {
    $("#scrSysRow").classList.toggle("on", $("#scrSys").checked);
    $("#scrMicRow").classList.toggle("on", $("#scrMic").checked);
    $("#scrMicDevRow").hidden = !$("#scrMic").checked;
    summary();
  }

  function summary() {
    if (!data) return;
    const o = opts(), mic = devs && devs.find(d => d.id === o.mic_device);
    const line = (on, icon, txt) => `<div class="${on ? "on" : "off"}"><svg><use href="#${icon}"/></svg><span>${txt}</span></div>`;
    const what = !src ? `<div class="warn"><svg><use href="#i-help"/></svg>Bitte oben auswählen, was aufgenommen werden soll.</div>`
      : line(true, src.id.startsWith("win:") ? "i-window" : "i-screen", src.id.startsWith("win:") ? `Fenster „${esc(src.title)}“` : `${esc(src.name)} (${esc(src.size)})`);
    let cl = "";
    if (src && crop) {
      const W = src.w && Math.round(src.w * crop.w), H = src.h && Math.round(src.h * crop.h);
      cl = line(true, "i-crop", "Nur dieser Bereich" + (W && H ? ` <span class="muted">· ca. ${W} × ${H}</span>` : ""));
    } else if (src && kind === "area") cl = `<div class="warn"><svg><use href="#i-crop"/></svg>Bitte noch den Bereich zeichnen.</div>`;
    let h = `<span class="t">So wird aufgenommen</span>${what}${cl}`
      + line(o.sys_audio, "i-vol", o.sys_audio ? "Ton vom PC" : "Ton vom PC – nein")
      + line(o.mic, "i-mic", o.mic ? "Dein Mikrofon" + (mic ? ` <span class="muted">· ${esc(mic.name)}</span>` : "") : "Dein Mikrofon – nein");
    if (!o.sys_audio && !o.mic) h += `<div class="warn"><svg><use href="#i-mute"/></svg>Ohne Ton – es wird nur das Bild aufgenommen.</div>`;
    else if (o.sys_audio && !o.mic) h += `<div class="warn"><svg><use href="#i-mic"/></svg>Man hört nur die anderen, nicht dich.</div>`;
    if (src && src.minimized) h += `<div class="warn"><svg><use href="#i-window"/></svg>Dieses Fenster ist minimiert – bitte vorher öffnen.</div>`;
    $("#scrSum").innerHTML = h;
    $("#scrGo").disabled = !src || (kind === "area" && !crop);
    cropUi();
    const d = S.settings.output_dir || "";
    $("#scrWhere").textContent = d ? `Wird als MP4-Video gespeichert in: ${d}${d.endsWith(sep()) ? "" : sep()}Bildschirmaufnahmen` : "";
  }

  async function preview(now) {
    clearTimeout(prevT);
    if (!active() || view !== "setup" || !src) return;
    if (!prevBusy && !document.hidden) {
      prevBusy = true;
      try {
        const id = src.id, u = await call("screen_preview", id);
        if (u && src && src.id === id) {
          const b = $("#scrShot"), im = new Image();
          im.onload = () => { const r = im.naturalWidth / im.naturalHeight || 1.6; b.style.setProperty("--ar", `${im.naturalWidth} / ${im.naturalHeight}`); b.style.setProperty("--arn", r.toFixed(3)); };
          im.src = u; b.style.backgroundImage = `url("${u}")`; b.classList.add("has");
        }
      } catch { } finally { prevBusy = false; }
    }
    prevT = setTimeout(preview, now ? 2500 : 3000);
  }
  async function levels() {
    clearTimeout(lvlT);
    if (!active() || view !== "setup") return;
    try {
      const r = await call("rec_monitor"), L = r.levels || {};
      const loop = (devs || []).find(d => d.loopback && d.default) || (devs || []).find(d => d.loopback);
      const set = (el, id) => { const lv = id && L[id]; el.parentNode.style.setProperty("--w", el.parentNode.offsetWidth + "px"); el.style.width = (lv ? db2w(lv.peak) : 0) + "%"; };
      set($("#scrSysLv"), loop && loop.id); set($("#scrMicLv"), $("#scrMicDev").value);
    } catch { }
    lvlT = setTimeout(levels, 140);
  }
  function loops() { preview(true); levels(); }

  /* --- Bereich zeichnen */
  function cropUi() {
    const bx = $("#scrCropBox");
    bx.hidden = !crop;
    if (crop) Object.assign(bx.style, { left: crop.x * 100 + "%", top: crop.y * 100 + "%", width: crop.w * 100 + "%", height: crop.h * 100 + "%" });
    $("#scrCropBtn span").textContent = crop ? "Bereich ändern" : "Nur einen Bereich aufnehmen";
    $("#scrCropBtn").disabled = !src;
    $("#scrCropOff").hidden = !crop;
  }
  async function openCrop() {
    if (!src) return;
    const s0 = src;
    let r = crop ? { ...crop } : null, drag = null;
    const box = dialog({ title: "Bereich zeichnen", icon: "i-crop", wide: true,
      body: `<p class="muted crop-tip">Ziehe mit der Maus ein Rechteck um das, was aufgenommen werden soll – z. B. nur das Video. An den Ecken ziehen ändert die Größe, in der Mitte ziehen verschiebt.</p>
        <div class="crop-stage"><img alt=""><div class="loading">Bild wird geladen …</div><div class="crop-rect" hidden><i data-h="nw"></i><i data-h="ne"></i><i data-h="sw"></i><i data-h="se"></i><b></b></div></div>`,
      buttons: [
        { label: "Ganzes Bild", fn: () => { crop = null; closeDialog(); if (kind === "area") { kind = s0.id.startsWith("win:") ? "win" : "screen"; renderList(); } summary(); remember(); } },
        { label: "Abbrechen" },
        { label: "Übernehmen", cls: "primary", id: "cropOk", fn: () => { if (!r || r.w < .02 || r.h < .02) return toast("Bitte zuerst ein Rechteck ziehen."); crop = r; closeDialog(); summary(); remember(); } },
      ] });
    box.classList.add("crop-modal");
    const stage = box.querySelector(".crop-stage"), img = stage.querySelector("img"), rect = stage.querySelector(".crop-rect"), lab = rect.querySelector("b");
    const clamp = v => Math.max(0, Math.min(1, v));
    const draw = () => {
      rect.hidden = !r;
      if (!r) return;
      Object.assign(rect.style, { left: r.x * 100 + "%", top: r.y * 100 + "%", width: r.w * 100 + "%", height: r.h * 100 + "%" });
      lab.textContent = s0.w && s0.h ? `${Math.round(s0.w * r.w)} × ${Math.round(s0.h * r.h)}` : `${Math.round(r.w * 100)} % × ${Math.round(r.h * 100)} %`;
    };
    const pt = e => { const b = img.getBoundingClientRect(); return { x: clamp((e.clientX - b.left) / b.width), y: clamp((e.clientY - b.top) / b.height) }; };
    stage.addEventListener("pointerdown", e => {
      if (!img.naturalWidth) return;
      e.preventDefault(); stage.setPointerCapture(e.pointerId);
      const p = pt(e), h = e.target.dataset && e.target.dataset.h;
      if (h && r) drag = { mode: h, r0: { ...r } };
      else if (r && e.target.closest(".crop-rect")) drag = { mode: "move", p0: p, r0: { ...r } };
      else { drag = { mode: "new", p0: p }; r = { x: p.x, y: p.y, w: 0, h: 0 }; }
    });
    stage.addEventListener("pointermove", e => {
      if (!drag) return;
      const p = pt(e), o = drag.r0;
      if (drag.mode === "new") r = { x: Math.min(p.x, drag.p0.x), y: Math.min(p.y, drag.p0.y), w: Math.abs(p.x - drag.p0.x), h: Math.abs(p.y - drag.p0.y) };
      else if (drag.mode === "move") r = { ...o, x: clamp(Math.min(1 - o.w, o.x + p.x - drag.p0.x)), y: clamp(Math.min(1 - o.h, o.y + p.y - drag.p0.y)) };
      else {
        let x1 = o.x, y1 = o.y, x2 = o.x + o.w, y2 = o.y + o.h;
        if (drag.mode.includes("w")) x1 = p.x; else x2 = p.x;
        if (drag.mode.includes("n")) y1 = p.y; else y2 = p.y;
        r = { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1) };
      }
      draw();
    });
    stage.addEventListener("pointerup", () => { drag = null; if (r && (r.w < .01 || r.h < .01)) r = null; draw(); });
    try {
      const u = await call("screen_preview", s0.id, 1280);
      img.onload = () => { stage.querySelector(".loading").remove(); draw(); };
      img.src = u;
    } catch (e) { stage.querySelector(".loading").textContent = "Kein Bild: " + String(e.message || e); }
  }
  $("#scrCropBtn").onclick = openCrop;
  $("#scrCropOff").onclick = () => { crop = null; if (kind === "area") { kind = src && src.id.startsWith("win:") ? "win" : "screen"; renderList(); } summary(); remember(); };

  /* --- Aufnahme */
  async function start() {
    if (!src) return;
    await safe($("#scrGo"), async () => {
      remember();
      st = await call("screen_start", opts());
      discardArm = 0; show("live"); renderLive(); startPoll();
      if ($("#scrSmall").checked) bar(true);
      else toast("Aufnahme läuft – du kannst SongGrabber jetzt minimieren.", "ok");
    });
  }
  function startPoll() { clearTimeout(pollT); tick(); }
  async function tick() {
    try { st = await call("screen_status"); } catch { }
    const on = ["recording", "paused"].includes(st.state);
    $("#navScrDot").classList.toggle("on", on || st.state === "finishing");
    if (on && view !== "live") show("live");
    if (on) { renderLive(); renderBar(); }
    else {
      if (barOn) { bar(false); go("screen"); }
      if (st.state === "finishing" || st.state === "done" || st.state === "error") { if (view !== "done") show("done"); renderDone(); }
    }
    if (on || st.state === "finishing") pollT = setTimeout(tick, on ? 400 : 300);
    else if (st.state === "done") toastDone();
  }
  let doneShown = null;
  function toastDone() {
    const p = st.result && st.result.mp4;
    if (!p || doneShown === p) return;
    doneShown = p;
    if (!active()) toast("Bildschirmaufnahme gespeichert: " + p.split(/[\\/]/).pop(), "ok");
  }
  function renderLive() {
    if (!active()) return;
    const paused = st.state === "paused", o = opts(), lv = st.levels || {};
    $("#scrLed").className = "led " + (paused ? "paused" : "on");
    $("#scrLiveState").textContent = paused ? "Pausiert – gerade wird nichts aufgenommen" : "Aufnahme läuft";
    $("#scrLiveSrc").textContent = st.source ? "· " + st.source : "";
    $("#scrTimer").textContent = fmtClock(st.elapsed);
    $("#scrSize").textContent = st.size ? mb(st.size) + " bisher" : "";
    $("#scrPause").innerHTML = `<svg><use href="#${paused ? "i-play" : "i-pause"}"/></svg>`;
    $("#scrPause").title = paused ? "Weiter aufnehmen" : "Pause";
    const meter = (box, key, on) => {
      const el = $(box), bar = el.querySelector(".bar i"), em = el.querySelector("em"), v = lv[key], err = lv[key + "_error"];
      el.classList.toggle("off", !on); el.classList.toggle("bad", !!err);
      bar.parentNode.style.setProperty("--w", bar.parentNode.offsetWidth + "px");
      bar.style.width = (on && !paused ? db2w(v) : 0) + "%";
      em.textContent = !on ? "nicht dabei" : err ? "Fehler" : paused ? "Pause" : v === undefined || v < -58 ? "still" : Math.round(v) + " dB";
      em.title = err || "";
    };
    const sysOn = st.sys_on ?? o.sys_audio, micOn = st.mic_on ?? o.mic, micWait = micOn && !paused && st.mic_ready === false;
    meter("#scrMSys", "sys", sysOn);
    meter("#scrMMic", "mic", micOn);
    if (micWait) $("#scrMMic em").textContent = "geht an …";
    if (!micOn) $("#scrMMic em").textContent = "";
    const t = $("#scrMicTog");
    t.className = "mic-tog " + (micWait ? "wait" : micOn ? "on" : "off");
    t.innerHTML = micOn ? `<svg><use href="#i-mic"/></svg>Mikro an` : `<svg><use href="#i-micoff"/></svg>Mikro aus`;
    t.title = micOn ? "Mikrofon ausschalten – ab jetzt hört man dich nicht mehr" : "Mikrofon einschalten – ab jetzt hört man dich im Video";
    $("#scrVErr").hidden = !st.video_error;
    $("#scrVErrT").textContent = st.video_error ? st.video_error + " – bitte stoppen und neu starten." : "";
  }
  /* --- kleine Leiste während der Aufnahme */
  async function bar(v) {
    if (v === barOn) return;
    barOn = v;
    if (v && Mini.on()) await Mini.set(false);
    document.body.classList.toggle("is-scrbar", v);
    if (v) renderBar();
    try {
      const r = await call("screen_bar", v);
      if (v) $("#sbNote").textContent = r && r.hidden ? "Diese Leiste ist im Video nicht zu sehen"
        : (st.source && kind === "win" ? "Aufgenommen wird nur: " + st.source : "Hinweis: Diese Leiste ist im Video zu sehen");
    } catch { }
  }
  function renderBar() {
    if (!barOn) return;
    const paused = st.state === "paused", lv = st.levels || {}, o = opts();
    $("#scrBar").classList.toggle("paused", paused);
    $("#scrBar").classList.toggle("vbad", !!st.video_error);
    const micOn = st.mic_on ?? o.mic, micWait = micOn && !paused && st.mic_ready === false, mb_ = $("#sbMic");
    mb_.className = "sb-btn sb-mic " + (micWait ? "wait" : micOn ? "on" : "off");
    mb_.innerHTML = `<svg><use href="#${micOn ? "i-mic" : "i-micoff"}"/></svg>`;
    mb_.title = micOn ? "Mikrofon ist AN – klicken zum Ausschalten" : "Mikrofon ist AUS – klicken zum Einschalten";
    $("#sbTime").textContent = fmtClock(st.elapsed);
    $("#sbState").textContent = st.video_error ? "Bild wird nicht aufgenommen!" : paused ? "Pausiert – nichts wird aufgenommen"
      : ((st.mic_on ?? o.mic) ? "Mikro an" : "Mikro aus") + (st.source ? " · " + st.source : "");
    $("#sbPause").innerHTML = `<svg><use href="#${paused ? "i-play" : "i-pause"}"/></svg>`;
    $("#sbPause").title = paused ? "Weiter aufnehmen" : "Pause";
    [["#sbSys", "sys", st.sys_on ?? o.sys_audio], ["#sbMicLv", "mic", st.mic_on ?? o.mic]].forEach(([id, k, on]) => {
      const el = $(id); el.classList.toggle("off", !on); el.style.height = Math.max(2, (paused ? 0 : db2w(lv[k])) * .26) + "px";
      el.title = on ? (k === "sys" ? "Ton vom PC" : "Mikrofon") : (k === "sys" ? "Ton vom PC: aus" : "Mikrofon: aus");
    });
  }

  function renderDone() {
    const fin = st.state === "finishing", ok = st.state === "done" && st.result, err = st.state === "error";
    $("#scrFin").hidden = !fin; $("#scrRes").hidden = !ok; $("#scrErr").hidden = !err;
    if (fin) $("#scrFinBar").style.width = Math.max(3, (st.progress || 0) * 100) + "%";
    if (ok) {
      const r = st.result;
      $("#scrResT").textContent = "Aufnahme gespeichert";
      $("#scrResS").textContent = [fmtTime(r.duration) + " min", mb(r.size || 0), r.has_audio ? "mit Ton" : "ohne Ton", r.mp3 ? "plus MP3" : ""].filter(Boolean).join(" · ");
      $("#scrResP").textContent = r.mp4;
    }
    if (err) $("#scrErrT").textContent = st.error || "Unbekannter Fehler.";
  }
  async function back() { await call("screen_discard").catch(() => { }); st = { state: "idle" }; show("setup"); enter(); }

  /* --- Bedienung */
  $$("#scrKind button").forEach(b => b.onclick = () => { if (kind === b.dataset.k) return; kind = b.dataset.k; src = null; pickDefault(); renderList(); preview(true); remember(); });
  $("#scrRefresh").onclick = () => safe($("#scrRefresh"), loadSources);
  ["#scrSys", "#scrMic"].forEach(s => $(s).onchange = () => { audioRows(); remember(); });
  $("#scrMicDev").onchange = () => { summary(); remember(); };
  ["#scrQ", "#scrFps", "#scrCursor", "#scrMp3"].forEach(s => $(s).onchange = remember);
  $("#scrGo").onclick = start;
  $("#scrHintOk").onclick = () => { $("#scrHint").hidden = true; save({ screen_hint_ok: true }); };
  $("#scrPause").onclick = () => safe($("#scrPause"), async () => { st = await call(st.state === "paused" ? "screen_resume" : "screen_pause"); renderLive(); renderBar(); });
  $("#sbPause").onclick = () => $("#scrPause").click();
  async function micToggle() {
    const v = !(st.mic_on ?? opts().mic);
    try { st = await call("screen_mic", v); renderLive(); renderBar(); toast(v ? "Mikrofon an – ab jetzt hört man dich im Video." : "Mikrofon aus – ab jetzt hört man dich nicht mehr."); } catch (e) { toast(String(e.message || e), "err"); }
  }
  $("#scrMicTog").onclick = micToggle;
  $("#sbMic").onclick = micToggle;
  $("#sbStop").onclick = () => $("#scrStop").click();
  $("#scrToBar").onclick = () => bar(true);
  $("#sbBig").onclick = () => { bar(false); go("screen"); };
  $("#scrBar").addEventListener("dblclick", e => { if (!e.target.closest("button")) $("#sbBig").click(); });
  $("#scrStop").onclick = () => safe($("#scrStop"), async () => { st = await call("screen_stop"); if (barOn) { await bar(false); go("screen"); } show("done"); renderDone(); startPoll(); });
  $("#scrDiscard").onclick = async () => {
    const b = $("#scrDiscard");
    if (Date.now() - discardArm > 3500) { discardArm = Date.now(); b.textContent = "Wirklich verwerfen? Nochmal klicken"; setTimeout(() => { if (Date.now() - discardArm >= 3400) b.textContent = "Verwerfen"; }, 3500); return; }
    discardArm = 0; b.textContent = "Verwerfen"; clearTimeout(pollT);
    await call("screen_discard"); if (barOn) bar(false); $("#navScrDot").classList.remove("on"); toast("Aufnahme verworfen."); st = { state: "idle" }; show("setup"); enter();
  };
  $("#scrPlay").onclick = () => st.result && playVideo(st.result.mp4);
  $("#scrShow").onclick = () => st.result && call("open_path", st.result.mp4);
  $("#scrNew").onclick = back; $("#scrErrNew").onclick = back;
  document.addEventListener("visibilitychange", () => { if (!document.hidden && active() && view === "setup") preview(true); });

  async function closeAsk() {
    if (barOn) await bar(false);
    go("screen");
    dialog({ title: "Bildschirmaufnahme läuft noch", icon: "i-screen",
      body: `<p>Soll die Aufnahme vor dem Schließen gespeichert werden?</p>`,
      buttons: [
        { label: "Speichern & schließen", cls: "primary", fn: () => { closeDialog(); call("screen_close", true); } },
        { label: "Verwerfen & schließen", fn: () => { closeDialog(); call("screen_close", false); } },
        { label: "Weiter aufnehmen" },
      ] });
  }
  return { enter, closeAsk, tick };
})();

/* ---------------------------------------------------------------- Video ansehen (schlicht, ohne Lichtshow) */
async function playVideo(path) {
  let src = "";
  try { src = await call("video_url", path); } catch { }
  if (!src) { call("open_file", path); return; }
  const a = $("#audio");
  if (a && !a.paused) Player.toggle();                       // Musik anhalten, solange das Video läuft
  const name = path.split(/[\\/]/).pop();
  const box = dialog({ title: name.replace(/\.mp4$/i, ""), icon: "i-play", wide: true,
    body: `<video class="vid" src="${esc(src)}" controls autoplay playsinline></video>`,
    buttons: [
      { label: "Mit anderem Programm öffnen", fn: () => { box.querySelector("video").pause(); call("open_file", path); } },
      { label: "Im Ordner zeigen", fn: () => call("open_path", path) },
      { label: "Schließen", cls: "primary" },
    ],
    onClose: () => { const v = box.querySelector("video"); if (v) { v.pause(); v.removeAttribute("src"); v.load(); } } });
  box.classList.add("vid-modal");
  const v = box.querySelector("video"), head = box.querySelector(".m-head");
  let winFs = false;
  const tools = document.createElement("div");
  tools.className = "vid-tools";
  tools.innerHTML = `<button class="ghost sm" data-v="big" title="Fenster groß / klein (Doppelklick aufs Bild)"><svg><use href="#i-expand"/></svg><span>Größer</span></button><button class="ghost sm" data-v="fs" title="Vollbild (Esc beendet)"><svg><use href="#i-full"/></svg><span>Vollbild</span></button>`;
  head.insertBefore(tools, head.querySelector("[data-close]"));
  const setBig = on => { box.classList.toggle("big", on); box.style.width = box.style.height = ""; tools.querySelector("[data-v=big] span").textContent = on ? "Kleiner" : "Größer"; };
  const fs = async on => {
    if (on === winFs) return;
    const r = await call("toggle_fullscreen").catch(() => null);
    winFs = r === null ? on : !!r; box.classList.toggle("fs", winFs); if (winFs) setBig(true);
    tools.querySelector("[data-v=fs] span").textContent = winFs ? "Vollbild aus" : "Vollbild";
  };
  tools.querySelector("[data-v=big]").onclick = () => setBig(!box.classList.contains("big"));
  tools.querySelector("[data-v=fs]").onclick = () => fs(!winFs);
  const esc_ = e => { if (e.key === "Escape" && winFs) { e.stopPropagation(); fs(false); } };
  document.addEventListener("keydown", esc_, true);
  const prevClose = dlgClose;
  dlgClose = () => { document.removeEventListener("keydown", esc_, true); if (winFs) fs(false); prevClose && prevClose(); };
  v.addEventListener("error", () => { toast("Dieses Video lässt sich hier nicht abspielen – es wird mit einem anderen Programm geöffnet.", "err"); closeDialog(); call("open_file", path); });
  v.addEventListener("dblclick", e => { e.preventDefault(); if (winFs) fs(false); else setBig(!box.classList.contains("big")); });
}
window.Scr = Scr;

/* ---------------------------------------------------------------- Dateien & DVD */
$("#btnFilesAdd").onclick = e => safe(e.currentTarget, async () => addFiles(await call("choose_files")));
$("#btnFolderAdd").onclick = e => safe(e.currentTarget, async () => { const f = await call("choose_folder"); if (f) await addFiles([f]); });
$("#btnDvd").onclick = e => safe(e.currentTarget, async () => { const t = await call("dvd_open"); if (t.length) { S.files.push(...t); renderFiles(); toast(`${t.length} DVD-Titel gefunden`, "ok"); } });
$("#filesEmpty").onclick = () => $("#btnFilesAdd").click();
async function addFiles(paths) {
  if (!paths || !paths.length) return;
  const items = await call("files_probe", paths);
  const bad = items.filter(i => !i.ok);
  S.files.push(...items.filter(i => i.ok && !S.files.some(f => f.path === i.path)));
  if (bad.length) toast(`${bad.length} Datei(en) ohne Tonspur übersprungen`, "err");
  renderFiles();
}
function renderFiles() {
  const has = S.files.length > 0;
  $("#filesEmpty").hidden = has; $("#filesView").hidden = !has;
  $("#filesList").innerHTML = S.files.map((f, i) => {
    const streams = f.streams || [];
    const ss = streams.length > 1 ? `<select data-k="stream">${streams.map((s, j) => `<option value="${j}">${j + 1}: ${esc(s.codec)} ${s.channels || ""}ch ${esc(s.lang)}</option>`).join("")}</select>` : `<span class="muted" style="font-size:12px">${esc(f.codec || "")} ${f.rate ? (f.rate / 1000).toFixed(1).replace(".0", "") + " kHz" : ""}</span>`;
    return `<div class="trow file-cols" data-i="${i}"><div class="fname"><b title="${esc(f.path)}">${esc(f.name)}</b><small>${f.video ? "Video → Audio" : "Audio"}${f.size ? " · " + Math.round(f.size / 1048576) + " MB" : ""}</small></div><input data-k="artist" value="${esc(f.artist)}" placeholder="Interpret"><input data-k="title" value="${esc(f.title)}">${ss}<span class="d">${fmtTime(f.duration)}</span><button class="x" title="Entfernen"><svg><use href="#i-x"/></svg></button></div>`;
  }).join("");
  $$("#filesList .trow").forEach(r => {
    const f = S.files[+r.dataset.i];
    $$("[data-k]", r).forEach(el => el.onchange = el.oninput = () => f[el.dataset.k] = el.value);
    r.querySelector(".x").onclick = () => { S.files.splice(+r.dataset.i, 1); renderFiles(); };
    const st = r.querySelector("select"); if (st) st.value = f.stream || 0;
  });
  const sec = S.files.reduce((a, f) => a + (f.duration || 0), 0);
  $("#filesSummary").textContent = `${S.files.length} Dateien · ${fmtTime(sec)}`;
}
$("#btnFilesClear").onclick = () => { S.files = []; renderFiles(); };
$("#btnFilesConvert").onclick = e => safe(e.currentTarget, async () => {
  const ids = await call("files_convert", S.files);
  toast(`${ids.length} Dateien werden umgewandelt`, "ok"); S.files = []; renderFiles(); go("queue");
});

/* ---------------------------------------------------------------- Warteschlange */
const KIND_ICO = { link: "i-link", cd: "i-disc", rec: "i-mic", file: "i-file", stream: "i-radio", watch: "i-plug" };
function renderJobs(jobs) {
  const running = jobs.filter(j => j.status === "läuft" || j.status === "wartet");
  const b = $("#queueBadge"); b.hidden = !running.length; b.textContent = running.length;
  $("#queueEmpty").hidden = jobs.length > 0;
  const cur = jobs.find(j => j.status === "läuft");
  $("#miniNow").hidden = !cur;
  if (cur) { $("#miniTitle").textContent = cur.title; $("#miniBar").style.width = (cur.progress * 100) + "%"; }
  const box = $("#jobs");
  const ids = new Set(jobs.map(j => String(j.id)));
  $$(".job", box).forEach(el => { if (!ids.has(el.dataset.id)) el.remove(); });
  jobs.forEach((j, idx) => {
    let el = box.querySelector(`.job[data-id="${j.id}"]`);
    if (!el) {
      el = document.createElement("div"); el.dataset.id = j.id;
      el.innerHTML = `<div class="job-ico"><svg><use href="#${KIND_ICO[j.kind] || "i-file"}"/></svg></div><div style="min-width:0"><div class="job-title"></div><div class="job-sub"></div><div class="job-line"><div class="bar"><i></i></div><span></span><b></b></div></div><div class="job-actions"></div>`;
      box.insertBefore(el, box.children[idx] || null);
    }
    el.className = "job " + j.status;
    el.querySelector(".job-title").textContent = j.title;
    el.querySelector(".job-sub").textContent = j.subtitle || "";
    el.querySelector(".bar i").style.width = (j.progress * 100).toFixed(1) + "%";
    el.querySelector(".job-line span").textContent = j.status === "fehler" ? j.error : (j.status === "fertig" && j.count > 1 ? `${j.stage} · ${j.count} Dateien` : j.stage);
    el.querySelector(".job-line span").title = j.error || j.stage;
    el.querySelector(".job-line b").textContent = j.status === "fehler" ? "!" : Math.round(j.progress * 100) + "%";
    const act = el.querySelector(".job-actions"), key = j.status + j.count;
    if (act.dataset.key !== key) {
      act.dataset.key = key;
      const audio = j.outputs.filter(o => /\.(mp3|flac|wav|m4a|ogg|opus)$/i.test(o));
      act.innerHTML = (j.status === "läuft" || j.status === "wartet") ? `<button class="ghost sm" data-a="cancel">Abbrechen</button>` :
        (audio.length ? `<button class="primary sm" data-a="play"><svg><use href="#i-play"/></svg>Abspielen</button>` : "") +
        (j.outputs.length ? `<button class="ghost sm" data-a="open"><svg><use href="#i-folder"/></svg>Anzeigen</button>` : "");
      const c = act.querySelector("[data-a=cancel]"); if (c) c.onclick = () => call("job_cancel", j.id);
      const o = act.querySelector("[data-a=open]"); if (o) o.onclick = () => call("open_path", j.outputs[j.outputs.length - 1]);
      const pb = act.querySelector("[data-a=play]"); if (pb) pb.onclick = () => Player.playPaths(audio);
      el.oncontextmenu = ev => { ev.preventDefault(); ctxMenu(ev, [
        audio.length && { icon: "i-play", label: "Abspielen", fn: () => Player.playPaths(audio) },
        audio.length && { icon: "i-list", label: "An Wiedergabeliste anhängen", fn: () => Player.addPaths(audio) },
        audio.length && { icon: "i-tag", label: "Tags bearbeiten …", fn: () => openTagEditor(audio) },
        audio.length === 1 && { icon: "i-cut", label: "Anfang/Ende kürzen …", fn: () => openTrim(audio[0]) },
        j.outputs.length && { icon: "i-folder", label: "Im Ordner anzeigen", fn: () => call("open_path", j.outputs[j.outputs.length - 1]) },
        (j.status === "läuft" || j.status === "wartet") && { icon: "i-x", label: "Abbrechen", fn: () => call("job_cancel", j.id) },
      ]); };
    }
    if (!S.first && (j.status === "fertig" || j.status === "fehler") && !S.seenDone.has(j.id)) {
      toast(j.status === "fertig" ? `Fertig: ${j.title}` : `Fehler: ${j.title} – ${j.error}`, j.status === "fertig" ? "ok" : "err");
    }
    if (j.status === "fertig" || j.status === "fehler") S.seenDone.add(j.id);
  });
  S.first = false;
}
$("#btnQueueClear").onclick = async () => { await call("jobs_clear"); poll(true); };

function renderStream(st) {
  $("#streamLive").hidden = !st.running;
  if (st.running) { $("#streamName").textContent = "● " + st.name; $("#streamInfo").textContent = `${fmtClock(st.elapsed)} · ${(st.size / 1048576).toFixed(1)} MB`; }
}
let pollT = null, pollN = 0;
async function poll(once) {
  clearTimeout(pollT);
  try {
    const r = await call("jobs_list");
    if (++pollN % 8 === 1) call("lib_status").then(st => { $("#libCount").textContent = st.count || ""; });
    renderJobs(r.jobs); renderStream(r.stream);
    if (r.inbox) {
      const items = await call("pop_inbox"), plays = items.filter(i => i.kind === "play" || i.kind === "play_add"), other = items.length - plays.length;
      plays.forEach((p, n) => { if (p.kind === "play" && n === 0) Player.playPaths(p.paths); else Player.addPaths(p.paths); });
      if (plays.length) go("player");
      if (other) toast(`${other} Übergabe(n) vom anderen Programm angenommen`, "ok");
    }
  } catch (e) { }
  if (!once) pollT = setTimeout(poll, 600);
}

/* ---------------------------------------------------------------- Live-Erkennung */
let liveToken = 0;
function showLive(info) {
  const box = $("#liveBox"), my = ++liveToken;
  box.hidden = !(info.type === "single" && info.live && !info.is_live);
  if (box.hidden) return;
  $("#liveWhy").textContent = info.live + (info.can_search ? " – ich suche die Originalversion …" : "");
  $("#liveCands").innerHTML = info.can_search ? `<div class="live-wait"><i class="spinner"></i>Suche Studioaufnahme und offizielles Video …</div>` : "";
  if (!info.can_search) return;
  call("link_find_original", info.artist || "", info.track || info.title, info.url, info.duration || 0).then(r => {
    if (my !== liveToken) return;
    const c = r.candidates || [];
    $("#liveWhy").textContent = info.live + (c.length ? " – möchtest du lieber das Original?" : " – kein Original gefunden, die Live-Version wird verwendet.");
    $("#liveCands").innerHTML = c.map((x, i) => `<div class="cand ${i === 0 ? "best" : ""}"><div class="ct" style="background-image:url('${esc(x.thumb)}')">${x.duration ? `<span>${fmtTime(x.duration)}</span>` : ""}</div><div class="cm"><span class="tag ${i === 0 ? "ok" : ""}">${i === 0 ? "Empfohlen · " : ""}${esc(x.kind)}</span><b title="${esc(x.title)}">${esc(x.title)}</b><small>${esc(x.uploader)}</small><button class="primary sm" data-u="${esc(x.url)}">Original nehmen</button></div></div>`).join("");
    $$("#liveCands [data-u]").forEach(b => b.onclick = () => { $("#urlInput").value = b.dataset.u; analyze(); });
  }).catch(() => { if (my === liveToken) $("#liveCands").innerHTML = `<div class="live-wait">Suche nicht möglich – die Live-Version wird verwendet.</div>`; });
}
$("#btnKeepLive").onclick = () => {
  liveToken++;
  $("#liveBox").hidden = true;
  const t = $("#resTrack");
  if (!/\blive\b|unplugged|konzert|concert/i.test(t.value)) t.value = t.value + " (Live)";
  if ($("#resAlbum").value && !/live|konzert|concert|unplugged/i.test($("#resAlbum").value)) { $("#resAlbum").value = ""; $("#resNo").value = ""; }
  if (S.link) { S.link.track_no = ""; S.link.cover_url = ""; S.link.meta_source = ""; }
  toast("Live-Version wird verwendet – als „(Live)“ gekennzeichnet", "ok");
};

/* ---------------------------------------------------------------- Neu in dieser Version (bei jeder Version ergänzen!) */
const CHANGES = [
  ["1.11.0", ["<b>Bildschirm aufnehmen</b>: Zoom, Teams, Webinar oder Live-Coaching als MP4-Video – ganzer Bildschirm oder nur ein Fenster, mit Vorschau", "Neue Lichtshows: <b>Nordlicht</b>, <b>Disco-Kugel</b>, <b>Laser</b> und <b>Feuerwerk</b> (statt Tesla)", "Player: <b>rechte Leiste hochrollen</b> wie ein Rollo (Q) und <b>Bedienung einklappen</b> zu kleinen Knöpfen (H) – Drüberfahren zeigt alles, nach 1 Minute Ruhe passiert es von selbst", "<b>Bereich zeichnen</b>: nur einen Ausschnitt aufnehmen – z. B. nur das Video in YouTube, Zoom oder Teams", "Klar sichtbar, welcher Ton mit drauf ist: <b>Ton vom PC</b> und/oder <b>dein Mikrofon</b> – mit Pegelanzeige", "<b>Mikrofon während der Aufnahme an/aus</b> – z. B. nur kurz einschalten, um etwas zu sagen", "<b>Kleine Aufnahme-Leiste</b> oben rechts mit Uhr, Pause und Stopp – unter Windows im Video unsichtbar", "Fertiges Video direkt in SongGrabber ansehen – saubere Dateinamen ohne Emojis", "Pause, Verwerfen, auf Wunsch zusätzlich als MP3 – und beim Schließen geht keine laufende Aufnahme verloren"]],
  ["1.10.0", ["<b>SongGrabber für Linux</b>: Ubuntu, Mint, Debian, Fedora, Arch, openSUSE – mit <code>install.sh</code>, Startmenü-Eintrag, Papierkorb, Audio-CDs, Systemsound und „Alles am PC“ über MPRIS", "Update-Hinweis verlinkt automatisch die passende Datei für Windows bzw. Linux"]],
  ["1.9.1", ["<b>Mini-Player</b> friert nicht mehr ein – Fenster wird zuverlässig klein, bleibt im Vordergrund und kommt genau so zurück", "Knöpfe oben im Player bleiben bei jeder Fenstergröße sichtbar"]],
  ["1.9.0", ["<b>Überblenden</b>: sanfte Übergänge zwischen Titeln (2–12 s) – Alben am Stück bleiben nahtlos", "<b>Lautstärke angleichen</b>: leise und laute Titel klingen gleich laut", "<b>Mini-Player</b>: mit einem Klick als kleine Leiste unten rechts, immer im Vordergrund – mit Songtext-Zeile und Lichtshow", "<b>Bibliothek aufräumen</b>: doppelte Titel, fehlende Cover/Angaben, leere Ordner", "<b>Update-Hinweis</b>: SongGrabber sagt Bescheid, wenn es eine neue Version gibt"]],
  ["1.8.2", ["Netzlaufwerk/NAS als Musik-Ordner: Setup bietet die Netzwerkadresse an, klare Meldung wenn das NAS aus ist", "<b>Setup fragt nach dem Musik-Ordner</b> – z. B. D:\\Musik für dein Archiv, Standard mit einem Klick", "<b>Neue Lichtshow „Tesla“</b>: Tesla-Spule mit Blitzen im Takt", "<b>Welle</b> neu: vier Wellen für Bass, Mitten und Höhen, automatisch ausgesteuert – kein Zittern mehr", "<b>Grundton</b>-Regler: alle Farben auf einmal ändern, alles bleibt abgestimmt", "<b>Eigene Farben</b> für die Lichtshow: Knopf „Farben“ neben den Farbpunkten – mit Vorlagen und „Zufällig“", "Radio-Songtext: Reiter „Songtext“ sucht jetzt immer nach dem gesendeten Lied, nicht nach dem Sender", "<b>Radio: Titel wechseln jetzt zuverlässig</b> – bisher blieb oft der erste Titel stehen", "<b>Radio-Songtexte viel öfter gefunden</b>: versteht jetzt „»Titel« von Interpret“, „Titel - Interpret“, „Interpret mit »Titel«“ u. a. und sucht notfalls im Freitext", "Livesender in der Leiste unten: sauberer LIVE-Hinweis mit laufendem Titel statt Zeitleiste", "<b>Drag &amp; Drop überall, wo es Sinn macht</b>: Dateien, Ordner, DVD-Ordner, .cue-Abbilder, Playlists, Links, Cover-Bilder und Ordner für die Einstellungen einfach hereinziehen", "<b>Cover &amp; Titel klein oben links</b> wie ein Senderlogo – Klick darauf (oder Taste I) zeigt sie wieder groß in der Mitte", "<b>Songtext bei „Alles am PC“</b>: zu Spotify, YouTube im Browser &amp; Co. erscheint der passende Text – mitlaufend, wenn die App ihre Position meldet", "<b>Radio-Songtext läuft mit</b> ab dem Liedwechsel", "Zeile anklicken, die gerade gesungen wird, oder −0,5 s / +0,5 s – so passt der Text immer"]],
  ["1.8.1", ["<b>Lichter aus</b>-Knopf im Player (Taste B): nur Musik hören mit ruhigem Bild – ideal auf dem zweiten Bildschirm, spart Leistung", "„CD-Abbild öffnen“ und „Dateien hinzufügen“ öffnen wieder das Auswahlfenster"]],
  ["1.8.0", ["<b>Radio &amp; Podcasts</b>: über 30.000 Internetradios mit Favoriten, gesendetem Titel, Cover, Songtext und Mitschnitt; Podcasts suchen, abonnieren, fortsetzen, herunterladen", "<b>YouTube &amp; Co. abspielen ohne Download</b> – auch direkt im Player suchen", "<b>Alles am PC</b>: Lichtshow, Titel, Cover und Steuerung für Spotify, YouTube im Browser &amp; Co."]],
  ["1.7.0", ["<b>Neuer Player</b> mit eigener Seite: Lichtshow (Synthwave, Spektrum, Kreis, Welle), Farbwelten auch vom Cover, 10-Band-Equalizer, Zufall &amp; Wiederholen, sortierbare Warteschlange, Tempo, Schlaf-Timer, Vollbild", "Windows-Medientasten und Wiedergabe-Anzeige", "Als Musik-Player in Windows nutzbar („Öffnen mit“, Doppelklick auf MP3/FLAC/Playlists)", "Player merkt sich Warteschlange, Position und Einstellungen", "<b>Hilfe komplett überarbeitet</b>: jeder Bereich, jede Einstellung, Tastenkürzel, Fortgeschrittene"]],
  ["1.6.1", ["Hilfe erklärt jetzt auch Löschen und die Ausgabegeräte beim Systemsound", "Nach jedem Update zeigt SongGrabber einmal, was neu ist (auch jederzeit unter Hilfe → „Neu in Version …“)"]],
  ["1.6.0", ["<b>Ohne CD-Laufwerk testen:</b> „Test-CD erzeugen“ und „CD-Abbild öffnen“ (CUE/BIN/WAV/FLAC, mit CD-Text)", "<b>Fehlerbericht:</b> Einstellungen → Werkzeuge → „Fehlerbericht kopieren“ – zum Weiterschicken bei Problemen", "Hilfe zeigt nach jedem Update, was neu ist"]],
  ["1.5.4", ["Aufnahme vom Systemsound bricht nicht mehr mit einem Fehler ab"]],
  ["1.5.3", ["Systemsound: alle Ausgabegeräte mit Live-Pegel – man sieht, über welches gerade Ton läuft"]],
  ["1.5.2", ["Titel in der Bibliothek löschen (Papierkorb) – Knopf, Entf-Taste oder Rechtsklick"]],
  ["1.5.1", ["Live-Pegel für alle Eingänge – der aktive Eingang leuchtet grün", "Mikrofon-Modus wählt das Windows-Standardmikrofon", "Hinweis, wenn Windows den Mikrofonzugriff blockiert"]],
  ["1.5.0", ["Neuer Name: <b>SongGrabber</b> (früher AudioGrabber) – Einstellungen werden übernommen"]],
  ["1.4.0", ["Full-Album-Videos in einzelne Titel teilen", "Musikerkennung per Fingerabdruck", "Tag-Editor, Songtexte, Übertragen auf USB/Handy, Abos, Anfang/Ende kürzen"]],
  ["1.3.0", ["Live-Auftritte erkennen und Original vorschlagen", "Hilfe (F1) und Begrüßung"]],
];
function renderChanges(all) {
  const list = all ? CHANGES : CHANGES.slice(0, 1);
  $("#newVer").textContent = CHANGES[0][0];
  $("#newList").innerHTML = list.map(([v, items], i) => (all && i ? `<h3>Version ${v}</h3>` : "") + `<ul>${items.map(x => `<li>${x}</li>`).join("")}</ul>`).join("");
  $("#btnAllChanges").parentElement.hidden = all;
}
$("#btnAllChanges").onclick = () => renderChanges(true);
renderChanges(false);
function showWhatsNew(from) {
  const newer = CHANGES.filter(([v]) => verCmp(v, from) > 0);
  if (!newer.length) return;
  const box = dialog({ title: `SongGrabber wurde aktualisiert – Version ${CHANGES[0][0]}`, icon: "i-wand",
    body: newer.map(([v, items]) => `<h4 class="muted" style="margin:6px 0 8px;font-size:12px;letter-spacing:1px">VERSION ${v}</h4><ul style="margin:0 0 10px;padding-left:20px">${items.map(x => `<li>${x}</li>`).join("")}</ul>`).join(""),
    buttons: [{ label: "Hilfe öffnen", fn: () => { closeDialog(); openHelp("h-new"); } }, { label: "Alles klar", cls: "primary" }] });
  box.classList.add("whatsnew");
}
function verCmp(a, b) { const x = String(a).split(".").map(Number), y = String(b || "0").split(".").map(Number); for (let i = 0; i < 3; i++) { if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) - (y[i] || 0); } return 0; }

/* ---------------------------------------------------------------- Hilfe */
const HELP_FOR = { screen: "h-screen", radio: "h-radio", player: "h-player", abos: "h-abos", links: "h-links", cd: "h-cd", rec: "h-rec", files: "h-files", library: "h-library", queue: "h-queue", settings: "h-settings", help: "h-start" };
(() => {
  const arts = $$("#helpBody article");
  $("#helpToc").innerHTML = arts.map(a => `<a href="#${a.id}" data-id="${a.id}">${esc(a.querySelector("h2").textContent)}</a>`).join("");
  $$("#helpToc a").forEach(a => a.onclick = e => { e.preventDefault(); openHelp(a.dataset.id); });
  // „?“-Knopf in jeder Seitenüberschrift
  $$(".page").forEach(p => {
    const id = HELP_FOR[p.id.replace("page-", "")], h = p.querySelector(".page-head h1");
    if (!id || p.id === "page-help" || !h) return;
    const b = document.createElement("button"); b.className = "help-btn"; b.title = "Hilfe zu dieser Seite (F1)"; b.textContent = "?";
    b.onclick = () => openHelp(id); h.appendChild(b);
  });
})();
function openHelp(id) {
  go("help");
  const el = document.getElementById(id || "h-start");
  $$("#helpToc a").forEach(a => a.classList.toggle("on", a.dataset.id === el.id));
  requestAnimationFrame(() => { el.scrollIntoView({ behavior: "smooth", block: "start" }); el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); });
}
document.addEventListener("keydown", e => {
  if (e.key !== "F1") return;
  e.preventDefault();
  const cur = ($(".page.active") || {}).id || "page-links";
  openHelp(HELP_FOR[cur.replace("page-", "")] || "h-start");
});
$("#btnWelcome").onclick = () => { $("#welcome").hidden = false; };
$("#wGo").onclick = () => { $("#welcome").hidden = true; save({ welcome_done: true }); $("#urlInput").focus(); };
$("#wHelp").onclick = () => { $("#welcome").hidden = true; save({ welcome_done: true }); openHelp("h-start"); };

/* ---------------------------------------------------------------- Kontextmenü */
function ctxMenu(ev, items) {
  const m = $("#ctx");
  items = items.filter(Boolean);
  if (!items.length) return;
  m.innerHTML = items.map((it, i) => it === "-" ? "<hr>" : `<button data-i="${i}" ${it.disabled ? "disabled" : ""}><svg><use href="#${it.icon || "i-check"}"/></svg>${esc(it.label)}${it.kbd ? `<kbd>${it.kbd}</kbd>` : ""}</button>`).join("");
  $$("button", m).forEach(b => b.onclick = () => { hideCtx(); items[+b.dataset.i].fn(); });
  m.hidden = false;
  const w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = Math.min(ev.clientX, innerWidth - w - 8) + "px";
  m.style.top = Math.min(ev.clientY, innerHeight - h - 8) + "px";
}
function hideCtx() { $("#ctx").hidden = true; }
document.addEventListener("click", e => { if (!e.target.closest("#ctx")) hideCtx(); if (!e.target.closest("#pQueue,#pQueueBtn")) $("#pQueue").hidden = true; });
document.addEventListener("keydown", e => { if (e.key === "Escape") { hideCtx(); $("#modal").hidden = true; closeDialog(); } });
window.addEventListener("blur", hideCtx);

async function pasteInto(input, andAnalyze) {
  const t = await call("get_clipboard");
  if (!t) return toast("Zwischenablage ist leer.");
  const a = input.selectionStart ?? input.value.length, b = input.selectionEnd ?? input.value.length;
  input.value = andAnalyze ? t : input.value.slice(0, a) + t + input.value.slice(b);
  input.focus();
  if (andAnalyze) analyze();
}
function copyText(text) {
  if (!text) return;
  call("set_clipboard", text).catch(() => navigator.clipboard && navigator.clipboard.writeText(text));
}
// Rechtsklick im Link-Feld
$(".url-field").addEventListener("contextmenu", e => {
  e.preventDefault();
  const inp = $("#urlInput"), sel = inp.value.substring(inp.selectionStart, inp.selectionEnd), has = !!inp.value.trim();
  ctxMenu(e, [
    { icon: "i-wand", label: "Einfügen & analysieren", fn: () => pasteInto(inp, true) },
    { icon: "i-paste", label: "Einfügen", kbd: "Strg+V", fn: () => pasteInto(inp, false) },
    "-",
    { icon: "i-cut", label: "Ausschneiden", kbd: "Strg+X", disabled: !sel, fn: () => { copyText(sel); inp.setRangeText("", inp.selectionStart, inp.selectionEnd, "end"); } },
    { icon: "i-copy", label: "Kopieren", kbd: "Strg+C", disabled: !(sel || has), fn: () => copyText(sel || inp.value) },
    { icon: "i-check", label: "Alles markieren", kbd: "Strg+A", disabled: !has, fn: () => { inp.focus(); inp.select(); } },
    "-",
    { icon: "i-link", label: "Im Browser öffnen", disabled: !/^https?:/i.test(inp.value.trim()), fn: () => call("open_url", inp.value.trim()) },
    { icon: "i-x", label: "Feld leeren", disabled: !has, fn: () => { inp.value = ""; inp.focus(); } },
  ]);
});
// Rechtsklick in allen anderen Textfeldern: Standard-Bearbeiten
document.addEventListener("contextmenu", e => {
  const inp = e.target.closest("input:not([type=checkbox]):not([type=range]), textarea");
  if (!inp || inp.id === "urlInput" || e.defaultPrevented) return;
  e.preventDefault();
  const sel = inp.value.substring(inp.selectionStart, inp.selectionEnd);
  ctxMenu(e, [
    { icon: "i-paste", label: "Einfügen", fn: async () => { await pasteInto(inp, false); inp.dispatchEvent(new Event("input")); } },
    { icon: "i-copy", label: "Kopieren", disabled: !sel, fn: () => copyText(sel) },
    { icon: "i-check", label: "Alles markieren", fn: () => { inp.focus(); inp.select(); } },
  ]);
});

/* ---------------------------------------------------------------- Drag & Drop (Dateien, Ordner, Links) */
const Drop = (() => {
  const ov = document.createElement("div"); ov.id = "dropOv"; ov.hidden = true;
  ov.innerHTML = `<div class="drop-card"><svg><use href="#i-plus"/></svg><b id="dropTxt"></b><small id="dropSub"></small></div>`;
  document.body.appendChild(ov);
  let zone = null, target = null, hideT = 0;
  const page = () => (($(".page.active") || {}).id || "").replace("page-", "");
  const ZONE_TXT = { "image:cd": ["Bild als CD-Cover übernehmen", ""], "image:te": ["Bild als Cover übernehmen", ""],
    "folder:output_dir": ["Als Zielordner übernehmen", "Ordner hier loslassen"], "folder:watch_dir": ["Als Übergabe-Ordner übernehmen", "Ordner hier loslassen"], "folder:tools_dir": ["Als Werkzeug-Ordner übernehmen", "Ordner mit ffmpeg.exe / yt-dlp.exe"] };
  const PAGE_TXT = {
    files: ["Loslassen zum Umwandeln", "Audio- und Videodateien, ganze Ordner oder einen DVD-Ordner (VIDEO_TS)"],
    player: ["Loslassen zum Abspielen", "Musik, Ordner oder Playlists – oder einen YouTube-Link"],
    library: ["In die Bibliothek übernehmen", "Dateien werden ins eingestellte Format umgewandelt und einsortiert"],
    cd: ["CD-Abbild einlesen", ".cue-Datei hier loslassen"],
    links: ["Link loslassen", "Aus der Browser-Adresszeile, oder eine .url-/.txt-Datei mit Links"],
    abos: ["Kanal oder Playlist abonnieren", "Link hier loslassen"],
  };
  function hint(e) {
    const files = [...(e.dataTransfer.types || [])].includes("Files");
    const z = e.target.closest && e.target.closest("[data-drop]");
    if (target !== z) { if (target) target.classList.remove("drop-hot"); target = z; if (z) z.classList.add("drop-hot"); }
    zone = z ? z.dataset.drop : null;
    const t = zone ? ZONE_TXT[zone] : PAGE_TXT[page()] || (files ? ["Loslassen zum Umwandeln", "Audio/Video kommt nach „Dateien & DVD“, Playlists in den Player"] : ["Link loslassen", "wird unter „Links & Streams“ geöffnet"]);
    $("#dropTxt").textContent = t[0]; $("#dropSub").textContent = t[1];
    ov.hidden = false; ov.classList.toggle("zone", !!zone);
  }
  function hide() { ov.hidden = true; if (target) target.classList.remove("drop-hot"); target = null; }
  document.addEventListener("dragover", e => {
    if (e.dataTransfer.types && [...e.dataTransfer.types].includes("text/x-sg-internal")) return;   // Sortieren in der Warteschlange
    e.preventDefault(); clearTimeout(hideT); hint(e); hideT = setTimeout(hide, 400);
  });
  document.addEventListener("drop", e => {
    if ([...(e.dataTransfer.types || [])].includes("text/x-sg-internal")) return;
    e.preventDefault(); clearTimeout(hideT); hide();
    const dropZone = zone, pg = page();
    if (e.dataTransfer.files && e.dataTransfer.files.length) {
      Drop.pending = { zone: dropZone, page: pg };
      if (!window.pywebview) handle([...e.dataTransfer.files].map(f => f.name), dropZone, pg);   // Demo im Browser
      return;                                                      // echte Pfade kommen gleich von Python (sgDrop)
    }
    const txt = e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain") || "";
    const urls = [...new Set(txt.split(/\s+/).filter(x => /^https?:\/\//i.test(x)))];
    if (urls.length) links(urls, pg); else toast("Bitte Dateien, Ordner oder einen Link hierher ziehen.");
  });
  window.sgDrop = paths => { const p = Drop.pending || { zone: null, page: page() }; Drop.pending = null; handle(paths, p.zone, p.page); };

  async function links(urls, pg) {
    if (pg === "abos") { $("#aboUrl").value = urls[0]; $("#aboUrl").focus(); return toast("Link eingefügt – mit „Abonnieren“ bestätigen."); }
    if (pg === "player") { await Player.playEntries(urls.map(u => ({ kind: "stream", url: u, title: u }))); return toast(urls.length > 1 ? `${urls.length} Links werden abgespielt` : "Wird abgespielt – ohne Download", "ok"); }
    if (urls.length > 1) {
      return dialog({ title: `${urls.length} Links gefunden`, icon: "i-link", body: `<p>Alle als Audio herunterladen?</p><div class="muted" style="max-height:180px;overflow:auto;font-size:12px">${urls.map(esc).join("<br>")}</div>`,
        buttons: [{ label: "Nur den ersten öffnen", fn: () => { closeDialog(); go("links"); $("#urlInput").value = urls[0]; analyze(); } }, { label: "Alle herunterladen", cls: "primary", fn: async () => { closeDialog(); await call("link_download", urls.map(u => ({ url: u, title: u }))); toast(`${urls.length} Downloads gestartet`, "ok"); } }] });
    }
    go("links"); $("#urlInput").value = urls[0]; analyze();
  }
  async function handle(paths, z, pg) {
    if (!paths || !paths.length) return;
    const d = await call("drop_sort", paths);
    const n = k => d[k].length;
    // 1) gezielte Ablagefelder
    if (z && z.startsWith("image:")) {
      if (!n("images")) return toast("Bitte ein Bild (JPG/PNG) ablegen.");
      const p = d.images[0];
      if (z === "image:te" && window.__teCover) return window.__teCover(p);
      if (z === "image:cd") { if (!S.cd) return toast("Erst eine CD lesen."); S.cdCover = p; $("#cdCover").style.backgroundImage = `url("file:///${p.replace(/\\/g, "/")}")`; $("#cdCover").classList.remove("empty-cover"); return toast("Cover übernommen", "ok"); }
    }
    if (z && z.startsWith("folder:")) {
      const f = d.folders[0] || d.dvd[0]; if (!f) return toast("Bitte einen Ordner ablegen.");
      await save({ [z.slice(7)]: f }); return toast("Ordner übernommen", "ok");
    }
    // 2) je nach Bereich
    if (n("links") && !n("media") && !n("folders") && !n("cue")) return links(d.links, pg);
    if (pg === "cd" || (n("cue") && !n("media") && !n("folders"))) {
      if (n("cue")) { go("cd"); return openCdImage(d.cue[0]); }
      if (pg === "cd") toast("Für CDs bitte eine .cue-Datei ablegen – Audiodateien wandle ich unter „Dateien & DVD“ um.");
    }
    if (pg === "player" || (n("playlists") && !n("media") && !n("folders") && !n("dvd"))) {
      const ps = await call("files_expand_audio", [...d.audio, ...d.folders, ...d.playlists]);
      if (ps.length) { const had = !!Player.current(); if (!had) await Player.playPaths(ps); else await Player.addPaths(ps); return toast(`${ps.length} Titel ${had ? "zur Warteschlange hinzugefügt" : "werden abgespielt"}`, "ok"); }
      if (pg === "player") return toast("Keine abspielbaren Musikdateien gefunden.");
    }
    if (n("dvd")) {
      go("files");
      for (const f of d.dvd) { try { const t = await call("dvd_from", f); S.files.push(...t); toast(`${t.length} DVD-Titel gefunden`, "ok"); } catch (e) { toast(e.message || String(e), "err"); } }
      renderFiles();
    }
    if (n("media") || n("folders")) {
      if (pg !== "files") toast(pg === "library" ? "Wird umgewandelt und landet danach in der Bibliothek – unten auf „Umwandeln“ klicken." : "Unter „Dateien & DVD“ hinzugefügt.");
      go("files"); await addFiles([...d.media, ...d.folders]); return;
    }
    if (n("images")) return toast("Bilder kannst du auf ein Cover ziehen (CD oder Tags bearbeiten).");
    if (!n("dvd")) toast("Diese Datei kann SongGrabber nicht verwenden.");
  }
  return { handle };
})();

/* ---------------------------------------------------------------- Zwischenablage-Erkennung */
let lastClip = "";
async function checkClipboard() {
  if (!S.settings.clipboard_watch) return;
  try {
    const t = (await call("get_clipboard") || "").trim();
    if (!/^https?:\/\/\S+$/i.test(t) || t === lastClip || t === $("#urlInput").value.trim()) return;
    lastClip = t;
    $("#clipUrl").textContent = t; $("#clipBanner").hidden = false;
  } catch (e) { }
}
window.addEventListener("focus", () => setTimeout(checkClipboard, 150));
$("#clipYes").onclick = () => { $("#urlInput").value = lastClip; $("#clipBanner").hidden = true; go("links"); analyze(); };
$("#clipNo").onclick = () => { $("#clipBanner").hidden = true; };

/* ---------------------------------------------------------------- Player */
const THEMES = {
  synth: { name: "Synthwave", c: ["#FF2EA6", "#7B2FF7", "#00E5FF"], sun: ["#FFD319", "#FF2975", "#8C1EFF"], sky: ["#0B0420", "#1A0B3B", "#3B0F5C"] },
  sunset: { name: "Sonnenuntergang", c: ["#FF7A30", "#FF2E63", "#FFB547"], sun: ["#FFE29A", "#FF8A3D", "#FF2E63"], sky: ["#0D0610", "#2A0E1F", "#4E1630"] },
  ocean: { name: "Ozean", c: ["#00F5D4", "#3A86FF", "#9B5DE5"], sun: ["#C8FFF4", "#00BBF9", "#3A0CA3"], sky: ["#020A16", "#06213A", "#0B3B5C"] },
  neon: { name: "Neon", c: ["#39FF14", "#00E5FF", "#FF00E6"], sun: ["#EFFF7A", "#39FF14", "#00A8FF"], sky: ["#020806", "#052014", "#0A3324"] },
  cover: { name: "Farben vom Cover", c: ["#FF2EA6", "#7B2FF7", "#00E5FF"], sun: ["#FFD319", "#FF2975", "#8C1EFF"], sky: ["#0B0420", "#1A0B3B", "#3B0F5C"] },
};
const hexRgb = h => { const n = parseInt(h.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; };
const rgba = (h, a) => { const [r, g, b] = hexRgb(h); return `rgba(${r},${g},${b},${a})`; };

let PodProg = {};
function describe(t) {
  if (t.kind === "stream") return { kind: "stream", url: t.url, title: t.title, artist: t.artist, album: t.album, duration: t.duration, thumb: t.thumb };
  if (t.kind === "radio") return { kind: "radio", uuid: t.uuid, name: t.station, url: t.url, favicon: t.favicon, tags: t.tags };
  if (t.kind === "podcast") return { kind: "podcast", url: t.url, guid: t.guid, title: t.title, show: t.show, image: t.image, duration: t.duration, feed: t.feed };
  return { kind: "file", path: t.path };
}
const Player = (() => {
  const a = $("#audio");
  const st = { queue: [], idx: -1, order: [], shuffle: false, repeat: "off", seeking: false, muted: false, lastVol: .8, restoring: false };
  const cur = () => st.queue[st.idx];

  /* --- Anzeige --- */
  function ui() {
    const t = cur();
    $("#player").hidden = !t;
    $("#ppEmpty").hidden = !!t; $("#ppNow").hidden = !t;
    $("#navEq").classList.toggle("on", !!t && !a.paused);
    $("#pQn").textContent = st.queue.length > 1 ? st.queue.length : "";
    $("#ppQn").textContent = st.queue.length || "";
    [$("#pShuffle"), $("#ppShuffle")].forEach(b => b.classList.toggle("on", st.shuffle));
    const rp = $("#ppRepeat"); rp.classList.toggle("on", st.repeat !== "off");
    rp.querySelector("use").setAttribute("href", st.repeat === "one" ? "#i-repeat1" : "#i-repeat");
    rp.title = "Wiederholen: " + { off: "aus", all: "alle", one: "diesen Titel" }[st.repeat] + " (R)";
    renderQueue(); markRows();
    if (!t) return;
    const lv = t.kind === "radio" ? (st.liveMeta || {}) : null;
    const title = lv && lv.title ? lv.title : t.title, artist = lv ? (lv.artist || (lv.title ? t.station : (t.artist || "Live-Radio"))) : t.artist;
    const album = lv ? t.station : t.album;
    $("#pTitle").textContent = $("#ppTitle").textContent = title || "–";
    $("#pArtist").textContent = [artist, album].filter(Boolean).join(" · ") || "–";
    $("#ppArtist").textContent = artist || "–";
    $("#ppAlbum").textContent = lv ? "📻 " + t.station : [album, t.year].filter(Boolean).join(" · ") + (t.kind === "stream" ? (album ? " · " : "") + "online" : "");
    const live = t.kind === "radio";
    $("#ppLive").hidden = !live; $("#ppSeek").parentElement.hidden = live;
    $("#ppLiveTxt").textContent = live ? (lv && lv.text ? lv.text : t.station) : "";
    $("#pSeek").disabled = live; $("#ppSpeed").disabled = live; $("#ppRepeat").disabled = live;
    $(".p-seek").classList.toggle("live", live);
    if (live) { $("#pCur").innerHTML = `<i class="pulse"></i>LIVE<em>${esc(lv && lv.text ? lv.text : t.station || "")}</em>`; $("#pDur").textContent = ""; } else if ($("#pCur").querySelector(".pulse")) $("#pCur").textContent = fmtTime(a.currentTime);
    setArt(lv && lv.art ? Object.assign({}, t, { art: lv.art, path: t.path + "|" + lv.art }) : t);
    document.title = `${t.title}${t.artist ? " – " + t.artist : ""} · SongGrabber`;
    mediaSession(t);
    window.dispatchEvent(new CustomEvent("ag-track", { detail: lyricsTrack() }));
  }
  function lyricsTrack() {    // für den Songtext: beim Radio das gerade gesendete Lied, nicht der Sender
    const t = cur(); if (!t) return null;
    if (t.kind !== "radio") return t;
    const lv = st.liveMeta;
    return lv && lv.text ? Object.assign({}, t, { title: lv.title || lv.text, artist: lv.artist || "", album: "", raw: lv.text, path: t.path + "|" + lv.text })
      : Object.assign({}, t, { title: "", artist: "", path: t.path + "|" });
  }
  const BADGE = { stream: "ONLINE", radio: "RADIO", podcast: "PODCAST" };
  let artFor = null;
  function setArt(t) {
    if (artFor === t.path) return; artFor = t.path;
    const els = [$("#pArt"), $("#ppCoverImg")];
    els.forEach(e => { e.classList.add("none"); e.style.backgroundImage = ""; });
    Viz.setCover(null);
    if (!t.art) return;
    const img = new Image(); img.crossOrigin = "anonymous";
    img.onload = () => { if (artFor !== t.path) return; els.forEach(e => { e.style.backgroundImage = `url("${t.art}")`; e.classList.remove("none"); }); Viz.setCover(img); };
    img.src = t.art;
  }
  const playIcon = () => {
    const h = a.paused ? "#i-play" : "#i-pause";
    $("#pPlay use").setAttribute("href", h); $("#ppPlay use").setAttribute("href", h);
    $("#navEq").classList.toggle("on", !!cur() && !a.paused);
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = a.paused ? "paused" : "playing";
  };
  function renderQueue() {
    const tot = st.queue.reduce((s, t) => s + (t.duration || 0), 0);
    $("#ppQInfo").textContent = st.queue.length ? `${st.queue.length} Titel · ${fmtTime(tot)}` : "leer";
    $("#pQueue").innerHTML = st.queue.map((t, i) => `<div class="pq ${i === st.idx ? "cur" : ""}" data-i="${i}"><span>${i === st.idx ? "▶" : i + 1}</span><span class="t">${esc(t.artist && t.kind !== "radio" ? t.artist + " – " : "")}${esc(t.title)}${BADGE[t.kind] ? `<i class="src-badge">${BADGE[t.kind]}</i>` : ""}</span><button class="x" data-rm="${i}" title="Entfernen"><svg><use href="#i-x"/></svg></button></div>`).join("") || `<div class="pq">Leer</div>`;
    $("#ppQueue").innerHTML = st.queue.map((t, i) => `<div class="qrow ${i === st.idx ? "cur" : ""}" draggable="true" data-i="${i}"><span class="qn">${i === st.idx ? (a.paused ? "❚❚" : "▶") : i + 1}</span><span class="qa" style="${t.art ? `background-image:url('${t.art}')` : ""}"></span><span class="qt"><b>${esc(t.title || "–")}${BADGE[t.kind] ? `<i class="src-badge">${BADGE[t.kind]}</i>` : ""}</b><small>${esc(t.artist || "")}</small></span><span class="qd">${t.live ? "LIVE" : t.duration ? fmtTime(t.duration) : ""}<button class="x" data-rm="${i}" title="Entfernen"><svg><use href="#i-x"/></svg></button></span></div>`).join("")
      || `<div class="empty-ly">Die Warteschlange ist leer.<br>Über „Hinzufügen“ oder per Rechtsklick in der Bibliothek füllen.</div>`;
    const bind = (sel, row) => {
      $$(sel + " [data-i]").forEach(r => { r[row === "q" ? "ondblclick" : "onclick"] = e => { if (e.target.closest("[data-rm]")) return; play(+r.dataset.i); }; });
      $$(sel + " [data-rm]").forEach(b => b.onclick = e => { e.stopPropagation(); remove(+b.dataset.rm); });
    };
    bind("#pQueue", "p"); bind("#ppQueue", "q");
    // Ziehen zum Sortieren
    let from = -1;
    $$("#ppQueue .qrow").forEach(r => {
      r.ondragstart = e => { from = +r.dataset.i; r.classList.add("drag"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/x-sg-internal", "1"); };
      r.ondragend = () => r.classList.remove("drag");
      r.ondragover = e => { e.preventDefault(); $$("#ppQueue .over").forEach(x => x.classList.remove("over")); r.classList.add("over"); };
      r.ondrop = e => { e.preventDefault(); move(from, +r.dataset.i); };
      r.oncontextmenu = e => {
        e.preventDefault(); const i = +r.dataset.i, t = st.queue[i];
        ctxMenu(e, [
          { icon: "i-play", label: "Abspielen", fn: () => play(i) },
          { icon: "i-next", label: "Als Nächstes abspielen", disabled: i === st.idx, fn: () => move(i, st.idx + (i > st.idx ? 1 : 0)) },
          "-",
          t.kind === "file" && { icon: "i-tag", label: "Tags bearbeiten …", fn: () => openTagEditor([t.path]) },
          t.kind === "file" && { icon: "i-folder", label: "Im Ordner anzeigen", fn: () => call("open_path", t.path) },
          t.kind === "stream" && { icon: "i-down", label: "Herunterladen (als MP3 …)", fn: () => { call("link_download", [{ url: t.url, title: t.title, artist: t.artist }], {}); toast("Download gestartet – siehe Warteschlange", "ok"); } },
          t.kind === "stream" && { icon: "i-link", label: "Im Browser öffnen", fn: () => call("open_url", t.url) },
          t.kind === "radio" && { icon: "i-mic", label: "Sender mitschneiden", fn: () => recordRadio(t) },
          t.kind === "podcast" && { icon: "i-down", label: "Folge herunterladen", fn: () => { call("podcast_download", { title: t.show, author: t.show, image: t.image }, { title: t.title, url: t.url, date: 0, image: t.image }); toast("Download gestartet", "ok"); } },
          { icon: "i-x", label: "Aus der Warteschlange entfernen", fn: () => remove(i) },
        ]);
      };
    });
    const c = $("#ppQueue .qrow.cur");
    if (c && !st.userScrolled) c.scrollIntoView({ block: "nearest" });
  }
  function markRows() { const p = cur() && cur().path; $$("#libList .lrow").forEach(r => r.classList.toggle("playing", r.dataset.path === p)); }

  /* --- Steuerung --- */
  function makeOrder(keepCurrent = true) {
    const n = st.queue.length, rest = [...Array(n).keys()].filter(i => !(keepCurrent && i === st.idx));
    for (let i = rest.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [rest[i], rest[j]] = [rest[j], rest[i]]; }
    st.order = keepCurrent && st.idx >= 0 ? [st.idx, ...rest] : rest;
  }
  function play(i, { autoplay = true, at: at0 = 0 } = {}) {
    let at = at0;
    if (!st.queue.length) return;
    if (cur() && cur().kind === "podcast") savePodcast();
    st.idx = (i + st.queue.length) % st.queue.length;
    st.liveMeta = null;
    if (xf && !xf.handing) stopXfade();
    a.src = cur().src; a.playbackRate = cur().live ? 1 : (+$("#ppSpeed").value || 1);
    if (cur().kind === "radio") call("radio_played", { uuid: cur().uuid, name: cur().station, url: cur().url, favicon: cur().favicon, tags: cur().tags }).catch(() => { });
    if (cur().kind === "podcast" && !at) { const pr = PodProg[cur().guid]; if (pr && pr.pos > 15 && !pr.done) { at = pr.pos; toast(`Fortgesetzt bei ${fmtTime(pr.pos)}`); } }
    if (at) a.addEventListener("loadedmetadata", () => { a.currentTime = at; }, { once: true });
    loadNorm(cur());
    if (autoplay) { Viz.start(); a.play().catch(() => { }); }
    st.userScrolled = false; ui(); persist();
  }
  function nextIndex(dir) {
    const n = st.queue.length; if (!n) return -1;
    if (st.shuffle) {
      if (st.order.length !== n) makeOrder();
      let p = st.order.indexOf(st.idx) + dir;
      if (p >= n) { if (st.repeat === "all") { makeOrder(false); p = 0; } else return -1; }
      if (p < 0) p = 0;
      return st.order[p];
    }
    const j = st.idx + dir;
    if (j >= n) return st.repeat === "all" ? 0 : -1;
    return Math.max(0, j);
  }
  function next(auto = false) {
    if (auto && st.repeat === "one") { a.currentTime = 0; a.play(); return; }
    if (auto && Sleep.endOfTrack()) return;
    const j = nextIndex(1);
    if (j < 0) { a.pause(); a.currentTime = 0; playIcon(); return; }
    play(j);
  }
  function prev() { if (a.currentTime > 3) { a.currentTime = 0; return; } const j = nextIndex(-1); if (j >= 0) play(j); }
  function toggle() { if (!cur()) return; if (a.paused) { Viz.start(); a.play(); } else a.pause(); }
  function remove(i) {
    st.queue.splice(i, 1);
    if (i < st.idx) st.idx--;
    else if (i === st.idx) { if (st.queue.length) { play(Math.min(st.idx, st.queue.length - 1), { autoplay: !a.paused }); return; } close(); return; }
    st.order = []; ui(); persist();
  }
  function move(from, to) {        // „from“ vor die Zeile „to“ setzen
    if (from < 0 || from === to || from >= st.queue.length) return;
    const curT = cur(), [t] = st.queue.splice(from, 1);
    st.queue.splice(from < to ? to - 1 : to, 0, t);
    st.idx = st.queue.indexOf(curT); st.order = []; ui(); persist();
  }
  function close() { stopXfade(); a.pause(); a.removeAttribute("src"); a.load(); st.queue = []; st.idx = -1; st.order = []; artFor = null; document.title = "SongGrabber"; ui(); persist(); }
  function setShuffle(v) { st.shuffle = v; if (v) makeOrder(); ui(); persist(); toast(v ? "Zufällige Reihenfolge an" : "Zufällige Reihenfolge aus"); }
  function cycleRepeat() { st.repeat = { off: "all", all: "one", one: "off" }[st.repeat]; ui(); persist(); toast("Wiederholen: " + { off: "aus", all: "alle Titel", one: "diesen Titel" }[st.repeat]); }

  /* --- Ereignisse --- */
  a.addEventListener("play", () => { playIcon(); renderQueue(); });
  a.addEventListener("pause", () => { playIcon(); renderQueue(); persist(); savePodcast(); });
  function savePodcast() { const t = cur(); if (t && t.kind === "podcast" && a.currentTime > 5) { PodProg[t.guid] = { pos: a.currentTime, dur: a.duration, done: a.duration && a.currentTime >= a.duration - 30 }; call("podcast_progress_set", t.guid, a.currentTime, a.duration || 0).catch(() => { }); } }
  // Radio: gesendeten Titel abfragen
  setInterval(async () => {
    const t = cur(); if (!t || t.kind !== "radio" || a.paused) return;
    try {
      const m = await call("radio_now", t.rid);
      if (m && m.text) RC.note(m);
      if (m && m.text && (!st.liveMeta || st.liveMeta.text !== m.text)) { st.liveMeta = m; ui(); }
    } catch (e) { }
  }, 4000);
  a.addEventListener("ended", () => next(true));
  a.addEventListener("timeupdate", () => {
    if (st.seeking || !a.duration || !isFinite(a.duration) || (cur() && cur().kind === "radio")) return;
    const p = a.currentTime / a.duration;
    [["#pSeek", "#pCur"], ["#ppSeek", "#ppCur"]].forEach(([s, c]) => { $(s).value = p * 1000; $(s).style.setProperty("--p", p * 100 + "%"); $(c).textContent = fmtTime(a.currentTime); });
    if ("mediaSession" in navigator && navigator.mediaSession.setPositionState) try { navigator.mediaSession.setPositionState({ duration: a.duration, position: a.currentTime, playbackRate: a.playbackRate }); } catch (e) { }
    if (Math.floor(a.currentTime) % 10 === 0) persist();
    if (cur() && cur().kind === "podcast" && Math.floor(a.currentTime) % 15 === 0) savePodcast();
  });
  a.addEventListener("loadedmetadata", () => { if (cur() && cur().kind === "radio") return; $("#pDur").textContent = $("#ppDur").textContent = fmtTime(a.duration); });
  a.addEventListener("error", () => { if (cur() && a.getAttribute("src")) toast("Datei kann nicht abgespielt werden: " + cur().title, "err"); });
  [["#pSeek", "#pCur"], ["#ppSeek", "#ppCur"]].forEach(([s, c]) => {
    $(s).addEventListener("input", e => { st.seeking = true; $(c).textContent = fmtTime(e.target.value / 1000 * (a.duration || 0)); e.target.style.setProperty("--p", e.target.value / 10 + "%"); });
    $(s).addEventListener("change", e => { if (a.duration) a.currentTime = e.target.value / 1000 * a.duration; st.seeking = false; });
  });
  $("#pPlay").onclick = $("#ppPlay").onclick = toggle;
  $("#pNext").onclick = $("#ppNext").onclick = () => next();
  $("#pPrev").onclick = $("#ppPrev").onclick = prev;
  $("#pClose").onclick = close;
  $("#pShuffle").onclick = $("#ppShuffle").onclick = () => setShuffle(!st.shuffle);
  $("#ppRepeat").onclick = cycleRepeat;
  $("#pQueueBtn").onclick = e => { e.stopPropagation(); $("#pQueue").hidden = !$("#pQueue").hidden; };
  $("#pOpen").onclick = $("#pArt").onclick = $("#pMeta").onclick = () => go("player");
  $("#ppSpeed").onchange = e => { a.playbackRate = +e.target.value; };
  $("#ppQueue").addEventListener("wheel", () => { st.userScrolled = true; });

  /* --- Lautstärke --- */
  const vols = [$("#pVol"), $("#ppVol")];
  /* Lautstärke = Regler × Einblenden × Angleich (ohne Audio-Analyse nur leiser, nie lauter) */
  let fadeK = 1, normK = 1;
  st.vol = a.volume;
  function applyVol() {
    a.volume = Math.max(0, Math.min(1, st.vol * fadeK * (Audio_.live() ? 1 : Math.min(1, normK))));
    Audio_.setNorm(Audio_.live() ? normK : 1);
  }
  function setVolume(v, save) {
    st.vol = Math.max(0, Math.min(1, v)); st.muted = st.vol === 0; applyVol();
    vols.forEach(x => { x.value = Math.round(st.vol * 100); x.style.setProperty("--p", x.value + "%"); });
    $("#ppMute use").setAttribute("href", st.vol === 0 ? "#i-mute" : "#i-vol");
    if (save) { clearTimeout(setVolume.t); setVolume.t = setTimeout(() => call("save_settings", { volume: st.vol }), 500); }
  }
  async function loadNorm(t, tries = 0) {
    normK = 1; applyVol();
    if (!t || (t.kind && t.kind !== "file") || S.settings.norm_play === false) return;
    const nx = st.queue[nextIndex(1)], want = [t.path].concat(nx && (!nx.kind || nx.kind === "file") ? [nx.path] : []);
    try {
      const r = await call("loudness", want); if (cur() !== t) return;
      const db = r[t.path];
      if (db == null) { if (tries < 20) setTimeout(() => { if (cur() === t) loadNormRetry(t, tries + 1); }, 1500); return; }
      normK = Math.pow(10, db / 20); applyVol();
    } catch (e) { }
  }
  async function loadNormRetry(t, tries) {
    try { const r = await call("loudness", [t.path]); if (cur() !== t) return; const db = r[t.path];
      if (db == null) { if (tries < 20) setTimeout(() => { if (cur() === t) loadNormRetry(t, tries + 1); }, 1500); return; }
      normK = Math.pow(10, db / 20); applyVol(); } catch (e) { }
  }

  /* Überblenden: das Ende des alten Titels läuft auf einem zweiten Spieler aus, der neue blendet ein */
  const ax = $("#audio2"); let xf = null;
  const xfSec = () => +(S.settings.xfade ?? 4) || 0;
  function sameAlbumRun(c, n) {       // Alben am Stück (z. B. Live-Album) nicht überblenden
    if (!c || !n || !c.album || c.album !== n.album) return false;
    return !c.track || !n.track || n.track === c.track + 1;
  }
  function stopXfade() { if (!xf) return; clearInterval(xf.timer); ax.pause(); ax.removeAttribute("src"); ax.load(); xf = null; fadeK = 1; applyVol(); }
  function startXfade(X) {
    xf = { timer: 0, handing: false };
    const my = xf;
    ax.src = a.currentSrc; ax.playbackRate = a.playbackRate; ax.volume = a.volume;
    ax.addEventListener("loadedmetadata", () => {
      if (xf !== my) return;
      ax.currentTime = Math.min(ax.duration || 1e9, a.currentTime + .1);
      ax.play().then(() => {
        if (xf !== my) { ax.pause(); return; }
        const v0 = a.volume, rest = Math.max(.6, Math.min(X, (a.duration || 0) - a.currentTime)), T = performance.now();
        ax.volume = v0; fadeK = 0; applyVol();
        my.handing = true; next(true); my.handing = false;
        my.timer = setInterval(() => {
          const s = (performance.now() - T) / 1000, kIn = Math.min(1, s / X), kOut = Math.min(1, s / rest);
          fadeK = Math.sin(kIn * Math.PI / 2); applyVol();                       // gleich laut über den Übergang
          ax.volume = Math.max(0, v0 * Math.cos(kOut * Math.PI / 2));
          if (kIn >= 1 && kOut >= 1) { clearInterval(my.timer); ax.pause(); ax.removeAttribute("src"); ax.load(); if (xf === my) { xf = null; fadeK = 1; applyVol(); } }
        }, 40);
      }).catch(() => { if (xf === my) xf = null; });
    }, { once: true });
  }
  a.addEventListener("timeupdate", () => {
    const X = xfSec(), c = cur();
    if (!X || xf || a.paused || st.seeking || !c || c.kind === "radio" || c.kind === "podcast") return;
    if (!isFinite(a.duration) || a.duration < X * 2 + 8 || a.duration - a.currentTime > X + .25) return;
    if (st.repeat === "one" || Sleep.active()) return;
    const j = nextIndex(1), n = j >= 0 ? st.queue[j] : null;
    if (!n || n.kind === "radio" || n.kind === "podcast" || sameAlbumRun(c, n)) return;
    startXfade(X);
  });
  a.addEventListener("pause", () => { if (xf && !xf.handing) { ax.pause(); } });
  vols.forEach(x => x.oninput = () => setVolume(x.value / 100, true));
  $("#ppMute").onclick = () => { if (st.vol > 0) { st.lastVol = st.vol; setVolume(0, true); } else setVolume(st.lastVol || .8, true); };

  /* --- Tastatur --- */
  document.addEventListener("keydown", e => {
    if (e.target.closest("input:not([type=range]),textarea,select") || !$("#dlg").hidden || !$("#modal").hidden) return;
    const onPage = $("#page-player").classList.contains("active");
    if (e.key === "F11" && onPage) { e.preventDefault(); toggleFull(); return; }
    if (onPage && !e.ctrlKey && !e.altKey && (e.key === "b" || e.key === "B")) { toggleFx(); return; }
    if (onPage && !e.ctrlKey && !e.altKey && (e.key === "i" || e.key === "I")) { InfoMin.toggle(); return; }
    if (onPage && !e.ctrlKey && !e.altKey && (e.key === "q" || e.key === "Q")) { SideBar.toggle(); return; }
    if (onPage && !e.ctrlKey && !e.altKey && (e.key === "h" || e.key === "H")) { SideBar.toggleCtl(); return; }
    if (!cur()) return;
    if (e.code === "Space") { e.preventDefault(); toggle(); }
    else if (e.ctrlKey && e.code === "ArrowRight") next();
    else if (e.ctrlKey && e.code === "ArrowLeft") prev();
    else if (!onPage) return;
    else if (e.code === "ArrowRight") a.currentTime = Math.min(a.duration || 0, a.currentTime + 5);
    else if (e.code === "ArrowLeft") a.currentTime = Math.max(0, a.currentTime - 5);
    else if (e.code === "ArrowUp") { e.preventDefault(); setVolume(st.vol + .05, true); }
    else if (e.code === "ArrowDown") { e.preventDefault(); setVolume(st.vol - .05, true); }
    else if (e.key === "n" || e.key === "N") next();
    else if (e.key === "p" || e.key === "P") prev();
    else if (e.key === "s" || e.key === "S") setShuffle(!st.shuffle);
    else if (e.key === "r" || e.key === "R") cycleRepeat();
    else if (e.key === "m" || e.key === "M") $("#ppMute").click();
    else if (e.key === "v" || e.key === "V") Viz.cycle();
    else if (e.key === "l" || e.key === "L") $$(".pp-tabs button")[1].click();
  });

  /* --- Windows-Medientasten & Overlay --- */
  function mediaSession(t) {
    if (!("mediaSession" in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({ title: t.title || "", artist: t.artist || "", album: t.album || "", artwork: t.art ? [{ src: t.art, sizes: "512x512" }] : [] });
      const h = { play: () => { Viz.start(); a.play(); }, pause: () => a.pause(), previoustrack: prev, nexttrack: () => next(), seekto: d => { a.currentTime = d.seekTime; } };
      Object.entries(h).forEach(([k, f]) => navigator.mediaSession.setActionHandler(k, f));
    } catch (e) { }
  }

  /* --- Zustand merken --- */
  function persist() {
    if (st.restoring) return;
    clearTimeout(persist.t);
    persist.t = setTimeout(() => call("player_state_save", { items: st.queue.map(describe), idx: st.idx, pos: cur() && cur().live ? 0 : (a.currentTime || 0), shuffle: st.shuffle, repeat: st.repeat }).catch(() => { }), 600);
  }
  async function restore() {
    try {
      const s = await call("player_state_load");
      if (!s || !s.items || !s.items.length) return;
      st.restoring = true;
      st.queue = s.items; st.shuffle = !!s.shuffle; st.repeat = s.repeat || "off";
      if (st.queue.length) play(Math.min(Math.max(0, s.idx), st.queue.length - 1), { autoplay: false, at: s.pos || 0 });
    } catch (e) { } finally { st.restoring = false; }
  }

  return {
    setVolume: v => setVolume(v), markRows, restore, toggle, next, prev, close, refresh: ui,
    playItems(items, start = 0) { st.queue = items.slice(); st.order = []; if (st.shuffle) { st.idx = start; makeOrder(); } play(start); },
    addItems(items, { nextUp = false } = {}) {
      const empty = !st.queue.length;
      if (nextUp && !empty) st.queue.splice(st.idx + 1, 0, ...items); else st.queue.push(...items);
      st.order = [];
      if (empty) play(0); else { ui(); persist(); toast(nextUp ? `${items.length} Titel als Nächstes` : `${items.length} Titel angehängt`, "ok"); }
    },
    async playEntries(entries, start = 0) { const items = await call("items_resolve", entries); if (items.length) this.playItems(items, Math.min(start, items.length - 1)); else toast("Nichts Abspielbares gefunden.", "err"); },
    async addEntries(entries, opts) { const items = await call("items_resolve", entries); if (items.length) this.addItems(items, opts); },
    pause: () => a.pause(),
    async playPaths(paths, start = 0) { const items = await call("media_urls", paths); if (items.length) this.playItems(items, Math.min(start, items.length - 1)); else toast("Datei nicht gefunden.", "err"); },
    async addPaths(paths, opts) { const items = await call("media_urls", paths); if (items.length) this.addItems(items, opts); },
    current: cur, lyricsTrack, queue: () => st.queue, renorm() { loadNorm(cur()); },
    release(paths) {            // gelöschte Titel aus der Wiedergabe nehmen (Datei freigeben)
      const gone = new Set(paths), c = cur();
      if (c && gone.has(c.path)) { a.pause(); a.removeAttribute("src"); a.load(); }
      const keep = st.queue.filter(t => !gone.has(t.path));
      if (keep.length === st.queue.length) return;
      st.idx = c && !gone.has(c.path) ? keep.indexOf(c) : Math.min(st.idx, keep.length - 1);
      st.queue = keep; st.order = [];
      if (c && gone.has(c.path) && st.queue.length) { a.src = cur().src; artFor = null; }
      ui(); persist();
    },
  };
})();

/* ---------------------------------------------------------------- Klang: Equalizer + Analyse */
const EQ_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
const EQ_PRESETS = {
  flat: ["Neutral", [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]],
  bass: ["Bass-Boost", [7, 6, 4, 2, 0, 0, 0, 0, 0, 0]],
  pop: ["Pop", [-1, 1, 3, 4, 3, 0, -1, 1, 2, 2]],
  rock: ["Rock", [5, 3, 1, -1, -2, 0, 2, 4, 5, 5]],
  elektro: ["Elektro", [6, 5, 1, 0, -2, 1, 0, 2, 4, 5]],
  vocal: ["Stimme / Hörbuch", [-3, -2, -1, 1, 4, 5, 4, 2, 0, -2]],
  klassik: ["Klassik", [3, 2, 1, 0, 0, 0, -1, 1, 2, 3]],
  nacht: ["Nachtmodus (leise Lautheit)", [5, 4, 2, 0, -1, -1, 0, 2, 3, 3]],
};
const Audio_ = (() => {
  const a = $("#audio");
  let ctx = null, src = null, an = null, filters = [], connected = false, gains = EQ_PRESETS.flat[1].slice(), on = true, norm = null, normK = 1;
  function init() {
    if (ctx) return;
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      filters = EQ_FREQS.map((f, i) => { const b = ctx.createBiquadFilter(); b.type = i === 0 ? "lowshelf" : i === EQ_FREQS.length - 1 ? "highshelf" : "peaking"; b.frequency.value = f; b.Q.value = 1.1; return b; });
      an = ctx.createAnalyser(); an.fftSize = 2048; an.smoothingTimeConstant = .78;
      for (let i = 0; i < filters.length - 1; i++) filters[i].connect(filters[i + 1]);
      filters[filters.length - 1].connect(an); an.connect(ctx.destination);
      norm = ctx.createGain(); norm.gain.value = normK; norm.connect(filters[0]);
      apply();
    } catch (e) { ctx = null; }
  }
  // Erst verbinden, wenn der Audio-Kontext wirklich läuft – sonst bliebe die Wiedergabe stumm.
  async function connect() {
    init(); if (!ctx || connected) return;
    try { if (ctx.state !== "running") await ctx.resume(); } catch (e) { }
    if (ctx.state !== "running") return;
    try {
      const s = a.currentSrc || a.src;
      if (s && !s.startsWith("http://127.0.0.1")) return;           // nur eigene Dateien (CORS)
      src = ctx.createMediaElementSource(a); src.connect(norm); connected = true;
    } catch (e) { }
  }
  document.addEventListener("pointerdown", () => { if (ctx && ctx.state !== "running") connect(); }, true);
  function apply() { filters.forEach((f, i) => { f.gain.value = on ? gains[i] : 0; }); }
  return {
    connect, analyser: () => (connected && ctx && ctx.state === "running" ? an : null),
    setGains(g) { gains = g.slice(); apply(); }, gains: () => gains.slice(),
    setOn(v) { on = v; apply(); }, isOn: () => on, live: () => connected,
    setNorm(k) { normK = k; if (norm && ctx) { try { norm.gain.setTargetAtTime(k, ctx.currentTime, .4); } catch (e) { norm.gain.value = k; } } },
  };
})();

/* ---------------------------------------------------------------- Visualizer & Licht */
const Viz = (() => {
  const cv = $("#vizCanvas"), x = cv.getContext("2d"), a = $("#audio");
  let mode = "synth", theme = "synth", raf = 0, W = 0, H = 0, D = 1, t0 = performance.now();
  let freq = new Uint8Array(1024), wave = new Uint8Array(2048), bars = new Float32Array(72), peaks = new Float32Array(72), cover = null;
  let bassAvg = 0, beat = 0, gridZ = 0, stars = [], particles = [], energy = 0, ext = null;
  const pal = () => THEMES[theme];
  function resize() {
    const r = cv.getBoundingClientRect(); D = Math.min(window.devicePixelRatio || 1, 1.5);
    W = Math.max(1, Math.round(r.width * D)); H = Math.max(1, Math.round(r.height * D));
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; stars = Array.from({ length: 120 }, () => [Math.random(), Math.random() * .5, Math.random() * 1.6 + .3, Math.random() * 6]); }
  }
  function setTheme(k) {
    theme = k; const p = pal(), root = document.documentElement;
    root.style.setProperty("--c1", p.c[0]); root.style.setProperty("--c2", p.c[1]); root.style.setProperty("--c3", p.c[2]);
    root.style.setProperty("--amb-rgb", hexRgb(p.c[0]).join(","));
    $$("#vizThemes button").forEach(b => b.classList.toggle("on", b.dataset.t === k));
    $("#ppColorsBtn").classList.toggle("sel", k === "custom");
  }
  function setMode(m) {
    mode = m; $$("#vizModes button").forEach(b => b.classList.toggle("active", b.dataset.v === m));
    $("#page-player").classList.toggle("mode-ring", m === "ring");
  }
  function setCover(img) {
    cover = img;
    if (!img || theme !== "cover") return;
    try {   // kräftigste Farben aus dem Cover
      const c = document.createElement("canvas"); c.width = c.height = 24; const g = c.getContext("2d"); g.drawImage(img, 0, 0, 24, 24);
      const d = g.getImageData(0, 0, 24, 24).data, cols = [];
      for (let i = 0; i < d.length; i += 4) { const [r, gg, b] = [d[i], d[i + 1], d[i + 2]], mx = Math.max(r, gg, b), mn = Math.min(r, gg, b); cols.push({ r, g: gg, b, s: (mx - mn) * (mx / 255) }); }
      cols.sort((p, q) => q.s - p.s);
      const hx = o => "#" + [o.r, o.g, o.b].map(v => Math.min(255, Math.round(v * 1.15)).toString(16).padStart(2, "0")).join("");
      const c1 = cols[0], c2 = cols.find(o => Math.abs(o.r - c1.r) + Math.abs(o.g - c1.g) + Math.abs(o.b - c1.b) > 140) || cols[8];
      const c3 = cols.find(o => o !== c2 && Math.abs(o.r - c2.r) + Math.abs(o.g - c2.g) + Math.abs(o.b - c2.b) > 120 && Math.abs(o.r - c1.r) + Math.abs(o.g - c1.g) + Math.abs(o.b - c1.b) > 120) || cols[16];
      THEMES.cover.c = [hx(c1), hx(c2), hx(c3)]; THEMES.cover.sun = [hx({ r: 255, g: 230, b: 150 }), hx(c1), hx(c2)];
      const dk = o => "#" + [o.r, o.g, o.b].map(v => Math.round(v * .12).toString(16).padStart(2, "0")).join("");
      THEMES.cover.sky = [dk(c2), dk(c1), "#" + [c1.r, c1.g, c1.b].map(v => Math.round(v * .3).toString(16).padStart(2, "0")).join("")];
      setTheme("cover");
    } catch (e) { }
  }

  /* --- Audiodaten (oder sanfte Leerlauf-Animation) --- */
  function sample(now) {
    const an = Audio_.analyser(), n = bars.length;
    const playing = SysMode.on() ? !!(ext && ext.on && ext.peak > 0.002) : !a.paused && !a.ended;
    if (SysMode.on() && ext && ext.bands && ext.bands.length === n) {
      for (let i = 0; i < n; i++) { const v = Math.pow(ext.bands[i], 1.35) * (1 + i / n * .6); bars[i] += (v - bars[i]) * (v > bars[i] ? .55 : .18); }
      if (ext.wave && ext.wave.length) wave = Uint8Array.from(ext.wave);
    } else if (an && playing && !SysMode.on()) {
      if (freq.length !== an.frequencyBinCount) freq = new Uint8Array(an.frequencyBinCount);
      an.getByteFrequencyData(freq); an.getByteTimeDomainData(wave);
      const nyq = 22050, bin = nyq / freq.length;
      for (let i = 0; i < n; i++) {
        const f0 = 35 * Math.pow(16000 / 35, i / n), f1 = 35 * Math.pow(16000 / 35, (i + 1) / n);
        let s = 0, c = 0; for (let k = Math.floor(f0 / bin); k <= Math.ceil(f1 / bin) && k < freq.length; k++) { s += freq[k]; c++; }
        const v = Math.pow((c ? s / c : 0) / 255, 1.35) * (1 + i / n * .6);
        bars[i] += (v - bars[i]) * (v > bars[i] ? .55 : .18);
      }
    } else {
      const tt = now / 1000, idle = playing ? .55 : .22;      // ohne Analyse: ruhiges „Atmen“
      for (let i = 0; i < n; i++) { const v = idle * (.35 + .35 * Math.sin(tt * 1.6 + i * .33) * Math.sin(tt * .7 + i * .11) + .25 * Math.max(0, Math.sin(tt * 2.1 - i * .18))) * (1 - i / n * .5); bars[i] += (v - bars[i]) * .08; }
      for (let i = 0; i < wave.length; i++) wave[i] = 128 + Math.sin(i / 40 + tt * 3) * 20 * idle;
    }
    for (let i = 0; i < n; i++) peaks[i] = Math.max(bars[i], peaks[i] - .008);
    const bass = (bars[0] + bars[1] + bars[2] + bars[3] + bars[4]) / 5;
    energy += ((bars.reduce((s, v) => s + v, 0) / n) - energy) * .1;
    bassAvg += (bass - bassAvg) * .05;
    if (bass > bassAvg * 1.28 && bass > .22 && beat < .35) { beat = 1; if (mode === "ring" || mode === "bars") burst(); }
    beat *= .9;
    document.documentElement.style.setProperty("--beat", (Math.max(beat * .9, bass * .6)).toFixed(3));
    return bass;
  }
  function burst() {
    const p = pal().c;
    for (let i = 0; i < 18; i++) { const ang = Math.random() * Math.PI * 2, sp = (2 + Math.random() * 4) * D; particles.push({ x: W / 2, y: H * .44, vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp, life: 1, c: p[i % 3] }); }
    if (particles.length > 300) particles.splice(0, particles.length - 300);
  }

  /* --- Szenen --- */
  function sky(p, bassV) {
    const g = x.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, p.sky[0]); g.addColorStop(.55, p.sky[1]); g.addColorStop(1, p.sky[2]);
    x.fillStyle = g; x.fillRect(0, 0, W, H);
    const now = performance.now() / 1000;
    for (const s of stars) { x.globalAlpha = .25 + .5 * Math.abs(Math.sin(now * .8 + s[3])) * (.6 + bassV); x.fillStyle = "#fff"; x.fillRect(s[0] * W, s[1] * H, s[2] * D, s[2] * D); }
    x.globalAlpha = 1;
  }
  function synth(p, bassV) {
    sky(p, bassV);
    const hz = H * .62, cx = W * .42;
    // Sonne mit Streifen
    const r = H * .2 * (1 + bassV * .1);
    const sg = x.createLinearGradient(0, hz - r * 1.6, 0, hz);
    sg.addColorStop(0, p.sun[0]); sg.addColorStop(.5, p.sun[1]); sg.addColorStop(1, p.sun[2]);
    x.save(); x.shadowColor = p.sun[1]; x.shadowBlur = 60 * D + beat * 60 * D;
    x.beginPath(); x.arc(cx, hz - r * .55, r, 0, Math.PI * 2); x.fillStyle = sg; x.fill(); x.restore();
    const off = (performance.now() / 60) % 14;
    x.fillStyle = p.sky[2];
    for (let k = 0; k < 9; k++) { const y = hz - r * .55 + k * r * .14 + off * D * .4; const hgt = 1.5 * D + k * 1.4 * D; if (y < hz - r * .55 - r) continue; x.fillRect(cx - r - 2, y, r * 2 + 4, hgt); }
    // Skyline aus dem Spektrum
    const n = bars.length;
    for (const [layer, alpha, scale, shift] of [[0, .55, .6, .5], [1, 1, 1, 0]]) {
      x.beginPath(); x.moveTo(0, hz);
      for (let i = 0; i <= n; i++) {
        const k = (i + Math.round(shift * n)) % n, v = bars[k] * (layer ? 1 : .8);
        const px = i / n * W, py = hz - (v * H * .32 * scale + (layer ? 6 : 14) * D * (1 + Math.sin(i * 1.7 + layer)));
        x.lineTo(px, py);
      }
      x.lineTo(W, hz); x.closePath();
      x.fillStyle = layer ? "rgba(8,4,20,.96)" : "rgba(20,8,40,.75)"; x.fill();
      x.strokeStyle = rgba(layer ? p.c[0] : p.c[1], alpha); x.lineWidth = (layer ? 2 : 1.2) * D;
      x.save(); x.shadowColor = layer ? p.c[0] : p.c[1]; x.shadowBlur = 14 * D; x.stroke(); x.restore();
    }
    // Boden-Gitter
    const fg = x.createLinearGradient(0, hz, 0, H); fg.addColorStop(0, "#0A0418"); fg.addColorStop(1, "#000"); x.fillStyle = fg; x.fillRect(0, hz, W, H - hz);
    x.save(); x.beginPath(); x.rect(0, hz, W, H - hz); x.clip();
    x.strokeStyle = rgba(p.c[0], .55 + beat * .4); x.lineWidth = 1.4 * D; x.shadowColor = p.c[0]; x.shadowBlur = 8 * D;
    for (let i = -24; i <= 24; i++) { x.beginPath(); x.moveTo(cx + i * W * .012, hz); x.lineTo(cx + i * W * .2, H); x.stroke(); }
    gridZ = (gridZ + (.004 + energy * .03 + beat * .02)) % 1;
    for (let k = 0; k < 16; k++) { const z = (k + gridZ) / 16, y = hz + Math.pow(z, 2.4) * (H - hz); x.globalAlpha = Math.min(1, z * 2.5); x.beginPath(); x.moveTo(0, y); x.lineTo(W, y); x.stroke(); }
    x.restore(); x.globalAlpha = 1;
    // Horizont-Linie
    x.save(); x.shadowColor = p.c[2]; x.shadowBlur = 20 * D + beat * 30 * D; x.fillStyle = rgba(p.c[2], .9); x.fillRect(0, hz - 1 * D, W, 2 * D); x.restore();
  }
  function barsScene(p, bassV) {
    x.fillStyle = "rgba(4,3,10,.38)"; x.fillRect(0, 0, W, H);       // Nachleuchten
    const rg = x.createRadialGradient(W * .42, H * .7, 0, W * .42, H * .7, W * .6);
    rg.addColorStop(0, rgba(p.c[1], .10 + bassV * .25)); rg.addColorStop(1, "rgba(0,0,0,0)"); x.fillStyle = rg; x.fillRect(0, 0, W, H);
    const n = bars.length, base = H * .74, area = W * .70, bw = area / n, x0 = W * .42 - area / 2;
    const g = x.createLinearGradient(0, base - H * .5, 0, base); g.addColorStop(0, p.c[2]); g.addColorStop(.5, p.c[0]); g.addColorStop(1, p.c[1]);
    x.save(); x.shadowColor = p.c[0]; x.shadowBlur = 16 * D;
    for (let i = 0; i < n; i++) {
      const h = Math.max(2 * D, bars[i] * H * .52), bx = x0 + i * bw;
      x.fillStyle = g; x.fillRect(bx + bw * .15, base - h, bw * .7, h);
      x.fillStyle = "#fff"; x.fillRect(bx + bw * .15, base - peaks[i] * H * .52 - 4 * D, bw * .7, 2 * D);
    }
    x.restore();
    x.save(); x.globalAlpha = .22; x.scale(1, -1); x.translate(0, -base * 2);     // Spiegelung
    for (let i = 0; i < n; i++) { const h = bars[i] * H * .2; x.fillStyle = g; x.fillRect(x0 + i * bw + bw * .15, base - h, bw * .7, h); }
    x.restore();
    drawParticles();
  }
  function ring(p, bassV) {
    x.fillStyle = "rgba(4,3,10,.32)"; x.fillRect(0, 0, W, H);
    const cx = W * .42, cy = H * .44, R = Math.min(W, H) * .15 * (1 + bassV * .12), n = bars.length, rot = performance.now() / 9000;
    const rg = x.createRadialGradient(cx, cy, R * .5, cx, cy, R * 3.2); rg.addColorStop(0, rgba(p.c[1], .25 + beat * .3)); rg.addColorStop(1, "rgba(0,0,0,0)"); x.fillStyle = rg; x.fillRect(0, 0, W, H);
    x.save(); x.translate(cx, cy); x.rotate(rot); x.lineCap = "round"; x.shadowBlur = 14 * D;
    for (let i = 0; i < n * 2; i++) {
      const k = i < n ? i : n * 2 - 1 - i, v = bars[k], ang = i / (n * 2) * Math.PI * 2, len = R * .15 + v * R * 1.5;
      const col = [p.c[0], p.c[2], p.c[1]][i % 3]; x.strokeStyle = col; x.shadowColor = col; x.lineWidth = 3.2 * D;
      x.beginPath(); x.moveTo(Math.cos(ang) * (R + 6 * D), Math.sin(ang) * (R + 6 * D)); x.lineTo(Math.cos(ang) * (R + 6 * D + len), Math.sin(ang) * (R + 6 * D + len)); x.stroke();
    }
    x.restore();
    x.save(); x.beginPath(); x.arc(cx, cy, R, 0, Math.PI * 2); x.closePath();
    x.shadowColor = p.c[0]; x.shadowBlur = 30 * D + beat * 40 * D; x.fillStyle = "#0D0B18"; x.fill(); x.clip();
    if (cover) { x.translate(cx, cy); x.rotate(rot * 2.2); x.drawImage(cover, -R, -R, R * 2, R * 2); }
    x.restore();
    x.save(); x.beginPath(); x.arc(cx, cy, R, 0, Math.PI * 2); x.strokeStyle = rgba("#ffffff", .5); x.lineWidth = 2 * D; x.stroke(); x.restore();
    drawParticles(cx, cy);
  }
  /* Welle: 5 Ebenen – Bass, tiefe Mitten, Mitten, Höhen (jede mit eigenem Schwung) + echte Schwingung mit Auto-Pegel */
  let wGain = 3, wPeak = .2, wPhase = 0, ripples = [];
  const bandAvg = (a0, a1) => { let s = 0; for (let i = a0; i < a1; i++) s += bars[i]; return s / (a1 - a0); };
  function waveScene(p) {
    x.fillStyle = "rgba(4,3,10,.24)"; x.fillRect(0, 0, W, H);
    const mid = H * .46, tt = performance.now() / 1000;
    wPhase += .012 + energy * .05 + beat * .04;
    const g = x.createRadialGradient(W * .42, mid, 0, W * .42, mid, W * .6); g.addColorStop(0, rgba(p.c[1], .10 + beat * .12)); g.addColorStop(1, "rgba(0,0,0,0)");
    x.fillStyle = g; x.fillRect(0, 0, W, H);
    const layers = [   // [Farbe, Stärke, Wellen über die Breite, Tempo, Linienbreite, Bandbereich]
      [p.c[0], bandAvg(0, 8), 1.3, .9, 5, [0, 8]],
      [p.c[1], bandAvg(8, 24), 2.6, -1.4, 3.6, [8, 24]],
      [p.c[2], bandAvg(24, 46), 5, 2.2, 2.6, [24, 46]],
      ["#ffffff", bandAvg(46, 72), 11, -3.4, 1.4, [46, 72]],
    ];
    const N = Math.max(60, Math.round(W / (4 * D)));
    layers.forEach(([c, e, k, sp, lw, [b0, b1]], j) => {
      const A = H * (.06 + Math.min(1, e * 1.6) * .30) * (1 + beat * .25) / (1 + j * .25);
      const path = [];
      for (let i = 0; i <= N; i++) {
        const u = i / N, env = Math.pow(Math.sin(Math.PI * u), .7);
        const det = .55 + .9 * bars[b0 + Math.floor(u * (b1 - b0 - 1) + .5)];        // Spektrum formt die Welle entlang der Breite
        const y = Math.sin(u * Math.PI * 2 * k + wPhase * sp + j) * .75 + Math.sin(u * Math.PI * 2 * k * 2.1 - wPhase * sp * 1.3) * .25;
        path.push([u * W, mid + y * A * env * det]);
      }
      // Fläche + Spiegelung
      x.save(); x.globalCompositeOperation = "lighter";
      const fg = x.createLinearGradient(0, mid - A, 0, mid + A); fg.addColorStop(0, rgba(c === "#ffffff" ? p.c[2] : c, .0)); fg.addColorStop(.5, rgba(c === "#ffffff" ? p.c[2] : c, .07 + e * .08)); fg.addColorStop(1, rgba(c === "#ffffff" ? p.c[2] : c, 0));
      x.fillStyle = fg; x.beginPath(); path.forEach(([px, py], i) => i ? x.lineTo(px, py) : x.moveTo(px, py));
      for (let i = path.length - 1; i >= 0; i--) x.lineTo(path[i][0], 2 * mid - path[i][1]); x.closePath(); x.fill();
      x.strokeStyle = c; x.lineWidth = lw * D * (1 + beat * .6); x.shadowColor = c; x.shadowBlur = (16 + beat * 24) * D; x.lineJoin = "round";
      x.beginPath(); path.forEach(([px, py], i) => i ? x.lineTo(px, py) : x.moveTo(px, py)); x.stroke();
      x.globalAlpha = .28; x.lineWidth = lw * D * .7; x.beginPath(); path.forEach(([px, py], i) => i ? x.lineTo(px, 2 * mid - py) : x.moveTo(px, 2 * mid - py)); x.stroke();
      x.restore();
    });
    // echte Schwingung, automatisch verstärkt, geglättet
    let pk = 0; for (let i = 0; i < wave.length; i += 4) pk = Math.max(pk, Math.abs(wave[i] - 128) / 128);
    wPeak += (pk - wPeak) * (pk > wPeak ? .3 : .02); wGain += (Math.min(9, .8 / Math.max(.04, wPeak)) - wGain) * .1;
    x.save(); x.strokeStyle = "#ffffff"; x.globalAlpha = .9; x.lineWidth = 2 * D; x.shadowColor = p.c[0]; x.shadowBlur = 22 * D; x.beginPath();
    const n = wave.length, M = Math.min(n, Math.round(W / (3 * D))), win = Math.max(1, Math.floor(n / M));
    for (let i = 0; i < M; i++) {
      let s = 0; for (let k = 0; k < win; k++) s += wave[i * win + k] - 128;
      const u = i / (M - 1), v = s / win / 128 * wGain, env = Math.pow(Math.sin(Math.PI * u), .5);
      const py = mid + Math.max(-1, Math.min(1, v)) * H * .22 * env; i ? x.lineTo(u * W, py) : x.moveTo(u * W, py);
    }
    x.stroke(); x.restore();
    // Beat: Ringe laufen von der Mitte aus
    if (beat > .95) ripples.push({ r: 0, a: 1 });
    ripples.forEach(r => { r.r += 9 * D; r.a *= .94; x.save(); x.strokeStyle = rgba(p.c[0], r.a * .6); x.lineWidth = 2 * D; x.beginPath(); x.ellipse(W * .42, mid, r.r * 1.6, r.r * .45, 0, 0, Math.PI * 2); x.stroke(); x.restore(); });
    ripples = ripples.filter(r => r.a > .04);
  }

  /* Nordlichter: wehende Lichtschleier über Bergen – Bass hebt sie an, Höhen lassen sie flackern */
  let mtnCache = null, mtnKey = "";
  function mountains(p) {
    const key = [W, H, p.sky[0], p.sky[2]].join("|");
    if (mtnCache && mtnKey === key) return mtnCache;
    const c = document.createElement("canvas"); c.width = W; c.height = H; const g = c.getContext("2d");
    const ridge = (base, amp, seed, col) => {
      g.beginPath(); g.moveTo(0, H);
      for (let i = 0; i <= 80; i++) {
        const t = i / 80, y = base - amp * (.55 * Math.abs(Math.sin(t * 5.3 + seed)) + .3 * Math.abs(Math.sin(t * 13.1 + seed * 2)) + .15 * Math.sin(t * 31 + seed * 3));
        g.lineTo(t * W, y);
      }
      g.lineTo(W, H); g.closePath(); g.fillStyle = col; g.fill();
    };
    ridge(H * .80, H * .20, 1.3, "#0a0d1a");
    ridge(H * .86, H * .14, 4.1, "#05060d");
    const lake = g.createLinearGradient(0, H * .86, 0, H); lake.addColorStop(0, "rgba(255,255,255,.04)"); lake.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = lake; g.fillRect(0, H * .86, W, H * .14);
    mtnCache = c; mtnKey = key; return c;
  }
  const raySprites = {};
  function raySprite(col) {                 // ein senkrechter Lichtstreifen: unten hell, nach oben verblassend
    if (raySprites[col]) return raySprites[col];
    const c = document.createElement("canvas"); c.width = 4; c.height = 128; const g = c.getContext("2d");
    const gr = g.createLinearGradient(0, 0, 0, 128);
    gr.addColorStop(0, rgba(col, 0)); gr.addColorStop(.55, rgba(col, .35)); gr.addColorStop(.86, rgba(col, 1)); gr.addColorStop(.93, rgba("#ffffff", .55)); gr.addColorStop(1, rgba(col, 0));
    g.fillStyle = gr; g.fillRect(0, 0, 4, 128);
    return (raySprites[col] = c);
  }
  let auC = null, auX = null;
  function aurora(p, bassV) {
    const g0 = x.createLinearGradient(0, 0, 0, H);
    g0.addColorStop(0, "#010208"); g0.addColorStop(.7, p.sky[0]); g0.addColorStop(1, "#03040a");
    x.fillStyle = g0; x.fillRect(0, 0, W, H);
    const now = performance.now() / 1000;
    for (const s of stars) { x.globalAlpha = .2 + .45 * Math.abs(Math.sin(now * .6 + s[3])); x.fillStyle = "#fff"; x.fillRect(s[0] * W, s[1] * H * 1.4, s[2] * D * .8, s[2] * D * .8); }
    x.globalAlpha = 1;
    // Lichtschleier klein zeichnen und weich hochskalieren – keine harten Streifen
    const cw = Math.max(80, Math.round(W / 6)), ch = Math.max(50, Math.round(H / 6));
    if (!auC || auC.width !== cw || auC.height !== ch) { auC = document.createElement("canvas"); auC.width = cw; auC.height = ch; auX = auC.getContext("2d"); }
    auX.globalCompositeOperation = "source-over"; auX.clearRect(0, 0, cw, ch); auX.globalCompositeOperation = "lighter";
    const n = bars.length, hi = bandAvg(46, 72);
    [[p.c[2] || p.c[0], .40, 0, [0, 24], .9], [p.c[0], .50, 2.1, [8, 40], 1], [p.c[1], .60, 4.2, [24, 60], .8]].forEach(([col, yb, ph, rg, str]) => {
      const lv = bandAvg(rg[0], rg[1]), spr = raySprite(col);
      for (let i = 0; i < cw; i++) {
        const t = i / cw;
        const fold = Math.sin(t * 7 + now * .22 + ph) * .06 + Math.sin(t * 15 - now * .35 + ph * 1.7) * .02 + Math.sin(t * 2.4 + now * .1 + ph) * .05;
        const base = ch * (yb + fold);
        // Pegel über mehrere Bänder gemittelt → sanft statt zappelig
        const k0 = rg[0] + t * (rg[1] - rg[0]), b = ((bars[Math.floor(k0)] || 0) + (bars[Math.min(n - 1, Math.floor(k0) + 1)] || 0) + (bars[Math.max(0, Math.floor(k0) - 1)] || 0)) / 3;
        const hgt = ch * (.12 + .13 * Math.sin(t * 4 + now * .35 + ph) ** 2 + lv * .22 + b * .1 + bassV * .04);
        const band = .45 + .55 * Math.pow(Math.sin(t * 9 + now * .45 + ph * 3) * .5 + .5, 1.5);
        const shimmer = 1 + hi * .35 * Math.sin(now * 5 + t * 10 + ph);
        const edge = Math.min(1, t * 5, (1 - t) * 5);
        auX.globalAlpha = Math.min(1, (.32 + lv * .75 + beat * .15) * band * shimmer * edge * str);
        auX.drawImage(spr, i, base - hgt, 1.6, hgt * 1.08);
      }
    });
    x.save(); x.globalCompositeOperation = "lighter"; x.imageSmoothingEnabled = true; x.imageSmoothingQuality = "high";
    x.drawImage(auC, 0, 0, W, H); x.restore();
    x.drawImage(mountains(p), 0, 0);
    x.save(); x.globalAlpha = .12 + energy * .2; x.globalCompositeOperation = "lighter";
    const rf = x.createLinearGradient(0, H * .86, 0, H); rf.addColorStop(0, rgba(p.c[0], .5)); rf.addColorStop(1, rgba(p.c[1], 0));
    x.fillStyle = rf; x.fillRect(0, H * .86, W, H * .14); x.restore();
  }

  /* Disco-Kugel: dreht sich, wirft Lichtpunkte und Strahlen – Takt lässt alles aufblitzen */
  let discoDots = [];
  function disco(p, bassV) {
    const cx = W * .42, cy = H * .2, R = Math.min(W, H) * .1, now = performance.now() / 1000, rot = now * .35;
    const bg = x.createRadialGradient(cx, H * .55, 0, cx, H * .55, Math.max(W, H) * .8);
    bg.addColorStop(0, rgba(p.c[1], .16 + energy * .15)); bg.addColorStop(1, "#030209");
    x.fillStyle = bg; x.fillRect(0, 0, W, H);
    // Boden mit Lichtschein
    const fl = x.createLinearGradient(0, H * .72, 0, H); fl.addColorStop(0, "rgba(255,255,255,.03)"); fl.addColorStop(1, rgba(p.c[0], .10 + beat * .12));
    x.fillStyle = fl; x.fillRect(0, H * .72, W, H * .28);
    // Strahlen
    x.save(); x.globalCompositeOperation = "lighter";
    const beams = 8;
    for (let i = 0; i < beams; i++) {
      const ang = Math.PI / 2 + Math.sin(rot * 1.3 + i * 2.4) * 1.1, len = Math.max(W, H) * 1.1, wd = .05 + bassV * .03;
      const col = p.c[i % 3], al = .05 + beat * .16 + energy * .07;
      const gr = x.createLinearGradient(cx, cy, cx + Math.cos(ang) * len, cy + Math.sin(ang) * len);
      gr.addColorStop(0, rgba(col, al * 2)); gr.addColorStop(1, rgba(col, 0));
      x.fillStyle = gr; x.beginPath(); x.moveTo(cx, cy);
      x.lineTo(cx + Math.cos(ang - wd) * len, cy + Math.sin(ang - wd) * len); x.lineTo(cx + Math.cos(ang + wd) * len, cy + Math.sin(ang + wd) * len); x.closePath(); x.fill();
    }
    // Lichtpunkte im Raum (wandern mit der Drehung)
    if (discoDots.length !== 110) discoDots = Array.from({ length: 110 }, () => ({ a: Math.random() * Math.PI * 2, y: .1 + Math.random() * .85, s: .6 + Math.random(), c: Math.floor(Math.random() * 3) }));
    for (const d of discoDots) {
      const a2 = d.a + rot, vis = Math.cos(a2);
      if (vis < -.2) continue;
      const px = cx + Math.sin(a2) * W * .62, py = d.y * H, r = (2 + d.s * 3 + bassV * 4 + beat * 4) * D * (.6 + vis * .5);
      const g = x.createRadialGradient(px, py, 0, px, py, r * 2.2); g.addColorStop(0, rgba("#ffffff", .7 * (.4 + vis * .6))); g.addColorStop(.35, rgba(p.c[d.c], .55 * (.4 + vis * .6))); g.addColorStop(1, rgba(p.c[d.c], 0));
      x.fillStyle = g; x.fillRect(px - r * 2.2, py - r * 2.2, r * 4.4, r * 4.4);
    }
    x.restore();
    if (mode === "party") { x.save(); x.globalAlpha = .8; laser(p, bassV, true); x.restore(); }
    // Aufhängung
    x.strokeStyle = "rgba(200,200,220,.35)"; x.lineWidth = 1.5 * D; x.beginPath(); x.moveTo(cx, 0); x.lineTo(cx, cy - R); x.stroke();
    // Kugel: echte Spiegelplättchen mit Fugen, spiegeln die Farben im Raum, Glanzpunkte funkeln im Takt
    x.fillStyle = "#0b0b12"; x.beginPath(); x.arc(cx, cy, R, 0, Math.PI * 2); x.fill();
    const rows = 22, L = [-.45, -.55, .7].map(v => v / Math.hypot(-.45, -.55, .7)), glints = [];
    const envC = [hexRgb(p.c[0]), hexRgb(p.c[1]), hexRgb(p.c[2]), [42, 36, 64], [58, 63, 85]];
    const rnd = (a1, b1) => { const q = Math.sin(a1 * 127.1 + b1 * 311.7) * 43758.5453; return q - Math.floor(q); };
    for (let r = 0; r < rows; r++) {
      const la0 = -Math.PI / 2 + r / rows * Math.PI, la1 = la0 + Math.PI / rows, lam = (la0 + la1) / 2, cl = Math.cos(lam), sl = Math.sin(lam);
      const n = Math.max(4, Math.round(rows * 2 * cl));
      for (let c = 0; c < n; c++) {
        const lo0 = c / n * Math.PI * 2 + rot + (r % 2) * Math.PI / n, lo1 = lo0 + Math.PI * 2 / n, lom = (lo0 + lo1) / 2;
        const nz = cl * Math.cos(lom); if (nz < -.05) continue;
        const nx = cl * Math.sin(lom), d = nx * L[0] + sl * L[1] + nz * L[2];
        const env = sl < -.2 ? envC[3] : nx > .3 ? envC[1] : nx < -.3 ? envC[0] : envC[4];
        const v = .25 + Math.max(0, d) * .75 + rnd(r, c) * .25 + (rnd(r, c + 9) > .97 ? beat * .5 : 0);
        x.fillStyle = `rgb(${Math.min(255, (190 * .55 + env[0] * .45) * v) | 0},${Math.min(255, (195 * .55 + env[1] * .45) * v) | 0},${Math.min(255, (215 * .55 + env[2] * .45) * v) | 0})`;
        const pt = (la, lo) => [Math.cos(la) * Math.sin(lo) * R, Math.sin(la) * R];
        const q = [pt(la0, lo0), pt(la0, lo1), pt(la1, lo1), pt(la1, lo0)], mx = (q[0][0] + q[1][0] + q[2][0] + q[3][0]) / 4, my = (q[0][1] + q[2][1]) / 2;
        x.beginPath(); q.forEach(([px, py], i) => { const X = cx + mx + (px - mx) * .86, Y = cy + my + (py - my) * .86; i ? x.lineTo(X, Y) : x.moveTo(X, Y); }); x.closePath(); x.fill();
        if (d > .9 && rnd(r + 3, c) > .5) glints.push([cx + mx, cy + my, (r + c) % 3]);
      }
    }
    const shd = x.createRadialGradient(cx - R * .3, cy - R * .35, R * .2, cx, cy, R);
    shd.addColorStop(0, "rgba(0,0,0,0)"); shd.addColorStop(.75, "rgba(0,0,0,.15)"); shd.addColorStop(1, "rgba(0,0,0,.65)");
    x.fillStyle = shd; x.beginPath(); x.arc(cx, cy, R, 0, Math.PI * 2); x.fill();
    const star = (px, py, sz, col) => {
      const g = x.createRadialGradient(px, py, 0, px, py, sz); g.addColorStop(0, "rgba(255,255,255,.95)"); g.addColorStop(.25, rgba(col, .5)); g.addColorStop(1, rgba(col, 0));
      x.fillStyle = g; x.fillRect(px - sz, py - sz, sz * 2, sz * 2);
      x.strokeStyle = "rgba(255,255,255,.8)"; x.lineWidth = 1.1 * D; x.beginPath(); x.moveTo(px - sz * 1.6, py); x.lineTo(px + sz * 1.6, py); x.moveTo(px, py - sz * 1.6); x.lineTo(px, py + sz * 1.6); x.stroke();
    };
    x.save(); x.globalCompositeOperation = "lighter";
    glints.slice(0, 2 + Math.round(beat * 3)).forEach(([gx, gy, ci], i) => star(gx, gy, (6 + i * 2 + beat * 6) * D, p.c[ci]));
    star(cx - R * .42, cy - R * .48, (14 + beat * 10) * D, "#ffffff");
    x.restore();
    x.save(); x.globalCompositeOperation = "lighter";
    const glow = x.createRadialGradient(cx, cy, R * .8, cx, cy, R * 2.4); glow.addColorStop(0, rgba(p.c[0], .15 + beat * .3)); glow.addColorStop(1, "rgba(0,0,0,0)");
    x.fillStyle = glow; x.fillRect(cx - R * 3, cy - R * 3, R * 6, R * 6); x.restore();
  }

  /* Laser-Show: scharfe Strahlen im Nebel – Muster wechseln im Takt, Bass lässt sie aufblitzen */
  let lzPat = 0, lzBeats = 0, fogCv = null, fogKey = "";
  function fog() {
    const key = W + "|" + H; if (fogCv && fogKey === key) return fogCv;
    const c = document.createElement("canvas"); c.width = W; c.height = H; const g = c.getContext("2d");
    for (let i = 0; i < 40; i++) {
      const fx = Math.random() * W, fy = H * (.25 + Math.random() * .75), r = (60 + Math.random() * 220) * D;
      const gr = g.createRadialGradient(fx, fy, 0, fx, fy, r); gr.addColorStop(0, "rgba(255,255,255,.035)"); gr.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = gr; g.fillRect(fx - r, fy - r, r * 2, r * 2);
    }
    fogCv = c; fogKey = key; return c;
  }
  let lzPrev = -1, lzFade = 1, lzE = 0, lzPh = 0, lzT = 0, lzSince = 0;
  function lzBeams(pat, p, bassV, now) {
    const beams = [], cx = W * .42;
    const emit = (ex, ey, ang, col, len = Math.max(W, H) * 1.4) => beams.push([ex, ey, ex + Math.cos(ang) * len, ey + Math.sin(ang) * len, col]);
    const spread = .5 + bassV * .12 + lzE * .15, sw = Math.sin(lzPh);
    if (pat === 0) {                                      // Fächer von unten, schwenkt langsam hin und her
      [[cx, 0], [W * .12, 1], [W * .78, 2]].forEach(([ex, k]) => { const n = 5; for (let i = 0; i < n; i++) emit(ex, H * .96, -Math.PI / 2 + (i / (n - 1) - .5) * spread * 2 + sw * .35 * (k === 1 ? 1 : -1), p.c[(i + k) % 3]); });
    } else if (pat === 1) {                               // kreuzende Strahlen von links und rechts
      for (let i = 0; i < 6; i++) { const a1 = -.18 - i * .08 + sw * .12; emit(0, H * (.38 + i * .09), a1, p.c[i % 3]); emit(W, H * (.38 + i * .09), Math.PI - a1, p.c[(i + 1) % 3]); }
    } else if (pat === 2) {                               // Lichttunnel: langsam drehender Kegel von oben
      const n = 12, rr = Math.min(W, H) * (.34 + bassV * .04);
      for (let i = 0; i < n; i++) { const t = i / n * Math.PI * 2 + lzPh * .6; beams.push([cx, -10 * D, cx + Math.cos(t) * rr * 1.6, H * .9 + Math.sin(t) * rr * .25, p.c[i % 3]]); }
    } else {                                              // Lichtfläche, die ruhig auf und ab gleitet
      const yy = H * (.48 + Math.sin(lzPh * .7) * .2);
      for (let i = 0; i < 16; i++) beams.push([W * .04, H * .5, W * 1.05, yy + (i / 15 - .5) * H * .42 * spread, p.c[(i >> 2) % 3]]);
      for (let i = 0; i < 16; i++) beams.push([W * .96, H * .5, -W * .05, yy + (i / 15 - .5) * H * .42 * spread, p.c[((i >> 2) + 1) % 3]]);
    }
    return beams;
  }
  function laser(p, bassV, overlay) {
    const now = performance.now() / 1000, dt = Math.min(.1, lzT ? now - lzT : 0); lzT = now;
    lzE += (energy - lzE) * .02;                          // geglättete Lautstärke → ruhige Bewegung
    lzPh += dt * (.28 + lzE * .3);
    if (!overlay) {
      x.fillStyle = "rgba(2,2,8,.6)"; x.fillRect(0, 0, W, H);
      const fo = fog(), off = (now * 7 * D) % W;
      x.globalAlpha = .7 + lzE * .4; x.drawImage(fo, -off, 0); x.drawImage(fo, W - off, 0); x.globalAlpha = 1;
    }
    // Muster wechseln: alle 16 Takte (frühestens nach 20 s), weich überblendet
    if (beat > .95) lzBeats++;
    if ((lzBeats >= 16 && now - lzSince > 20) || (!lzSince)) { if (lzSince) { lzPrev = lzPat; lzPat = (lzPat + 1) % 4; lzFade = 0; } lzBeats = 0; lzSince = now; }
    lzFade = Math.min(1, lzFade + dt / 2.5);
    const sets = [[lzBeams(lzPat, p, bassV, now), lzFade]];
    if (lzFade < 1 && lzPrev >= 0) sets.push([lzBeams(lzPrev, p, bassV, now), 1 - lzFade]);
    const glow = 1 + beat * .25;
    x.save(); x.globalCompositeOperation = "lighter"; x.lineCap = "round";
    for (const [beams, wgt] of sets) {
      const pass = (w, al, white) => {
        const by = {}; beams.forEach(b => (by[white ? "#ffffff" : b[4]] = by[white ? "#ffffff" : b[4]] || []).push(b));
        for (const col in by) { x.strokeStyle = rgba(col, Math.min(1, al * glow * wgt)); x.lineWidth = w * D; x.beginPath(); by[col].forEach(([a1, b1, c1, d1]) => { x.moveTo(a1, b1); x.lineTo(c1, d1); }); x.stroke(); }
      };
      pass(8, .05 + lzE * .04); pass(3, .2 + lzE * .15); pass(1.1, .5 + beat * .12, true);
      const src = {}; beams.forEach(b => src[Math.round(b[0]) + "," + Math.round(b[1])] = b);
      Object.values(src).forEach(([ex, ey, , , col]) => { const r = (14 + beat * 6) * D, g = x.createRadialGradient(ex, ey, 0, ex, ey, r); g.addColorStop(0, rgba("#ffffff", .85 * wgt)); g.addColorStop(.3, rgba(col, .45 * wgt)); g.addColorStop(1, rgba(col, 0)); x.fillStyle = g; x.fillRect(ex - r, ey - r, r * 2, r * 2); });
    }
    x.restore();
  }

  /* Feuerwerk: Raketen steigen im Takt auf – je lauter, desto größer die Explosion */
  let rockets = [], sparks = [], cityCache = null, cityKey = "", skyFlash = 0, lastLaunch = 0;
  function city(p) {
    const key = [W, H].join("|");
    if (cityCache && cityKey === key) return cityCache;
    const c = document.createElement("canvas"); c.width = W; c.height = H; const g = c.getContext("2d");
    let xx = 0; g.fillStyle = "#04040a";
    while (xx < W) {
      const bw = (18 + Math.random() * 46) * D, bh = H * (.05 + Math.random() * .16);
      g.fillRect(xx, H - bh, bw, bh);
      g.fillStyle = "rgba(255,210,140,.35)";
      for (let wy = H - bh + 6 * D; wy < H - 6 * D; wy += 9 * D) for (let wx = xx + 4 * D; wx < xx + bw - 5 * D; wx += 8 * D) if (Math.random() < .18) g.fillRect(wx, wy, 3 * D, 4 * D);
      g.fillStyle = "#04040a"; xx += bw + Math.random() * 6 * D;
    }
    cityCache = c; cityKey = key; return c;
  }
  function launch(p, power) {
    const sx = W * (.12 + Math.random() * .62);
    rockets.push({ x: sx, y: H, vx: (Math.random() - .5) * 1.4 * D, vy: -(H * (.0115 + Math.random() * .004 + power * .004)), c: p.c[Math.floor(Math.random() * 3)], p: power });
  }
  function fireworks(p, bassV) {
    x.fillStyle = "rgba(3,3,10,.18)"; x.fillRect(0, 0, W, H);
    if (skyFlash > .01) { x.fillStyle = rgba(p.c[1], skyFlash * .12); x.fillRect(0, 0, W, H); skyFlash *= .85; }
    const now = performance.now(), playing = !a.paused || SysMode.on();
    if (beat > .95 && now - lastLaunch > 180) { launch(p, .5 + bassV); if (bassV > .55) launch(p, bassV); lastLaunch = now; }
    else if (playing && (Math.random() < .01 + energy * .04 || (!rockets.length && now - lastLaunch > 1100))) { launch(p, .3 + energy); lastLaunch = now; }
    else if (!playing && Math.random() < .004) launch(p, .3);
    x.save(); x.globalCompositeOperation = "lighter";
    for (const r of rockets) {
      r.x += r.vx; r.y += r.vy; r.vy += H * .00016;
      x.fillStyle = rgba("#fff3d6", .9); x.fillRect(r.x - D, r.y - D, 2.4 * D, 2.4 * D);
      if (Math.random() < .7) sparks.push({ x: r.x, y: r.y, vx: (Math.random() - .5) * .6 * D, vy: Math.random() * D, l: .5, c: "#ffcf8a", s: 1.4 });
      if (r.vy >= -H * .0012) {                       // Gipfel: Explosion
        r.done = true; skyFlash = Math.min(1, skyFlash + .4 + r.p * .4);
        const cnt = Math.round(70 + r.p * 120), sp = (2.2 + r.p * 3.2) * D, ring = Math.random() < .3, c2 = p.c[Math.floor(Math.random() * 3)];
        for (let i = 0; i < cnt; i++) {
          const ang = Math.random() * Math.PI * 2, v = ring ? sp : sp * (.3 + Math.random() * .8);
          sparks.push({ x: r.x, y: r.y, vx: Math.cos(ang) * v, vy: Math.sin(ang) * v, l: 1, c: i % 4 === 0 ? c2 : r.c, s: 2.2, tw: Math.random() < .3 });
        }
      }
    }
    rockets = rockets.filter(r => !r.done && r.y > -50);
    for (const s of sparks) {
      s.x += s.vx; s.y += s.vy; s.vx *= .975; s.vy = s.vy * .975 + .045 * D; s.l -= .011;
      const al = Math.max(0, s.l) * (s.tw && Math.random() < .4 ? .3 : 1);
      x.fillStyle = rgba(s.c, al); const sz = s.s * D * (.6 + s.l * .6); x.fillRect(s.x - sz / 2, s.y - sz / 2, sz, sz);
    }
    x.restore();
    sparks = sparks.filter(s => s.l > 0); if (sparks.length > 2500) sparks.splice(0, sparks.length - 2500);
    x.drawImage(city(p), 0, 0);
  }
  function calm(p, bassV) {
    const g = x.createRadialGradient(W * .42, H * .45, 0, W * .42, H * .45, Math.max(W, H) * .8);
    g.addColorStop(0, rgba(p.c[1], .35 + bassV * .25)); g.addColorStop(.5, rgba(p.c[0], .10)); g.addColorStop(1, "#05040B");
    x.fillStyle = g; x.fillRect(0, 0, W, H);
  }
  function drawParticles() {
    x.save(); x.globalCompositeOperation = "lighter";
    for (const q of particles) { q.x += q.vx; q.y += q.vy; q.vy += .03 * D; q.life -= .015; x.globalAlpha = Math.max(0, q.life); x.fillStyle = q.c; x.fillRect(q.x, q.y, 3 * D, 3 * D); }
    x.restore(); particles = particles.filter(q => q.life > 0);
  }
  let fx = true, still = false;
  function setFx(on) {
    fx = !!on; still = false;
    $("#page-player").classList.toggle("fx-off", !fx); document.body.classList.toggle("fx-off", !fx);
    const b = $("#ppFx"); b.classList.toggle("on", fx); $("#ppFxTxt").textContent = fx ? "Lichter an" : "Lichter aus";
    if (!fx) document.documentElement.style.setProperty("--beat", "0");
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    if (fx) { if (!a.paused || SysMode.on()) start(); SysMode.resume(); } else drawStill();
  }
  function drawStill() {            // ein einziges ruhiges Bild – keine Animation, keine Rechenlast
    if (!$("#page-player").classList.contains("active")) { still = false; return; }
    resize(); x.save(); x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = "source-over"; x.shadowBlur = 0;
    x.fillStyle = "#05040B"; x.fillRect(0, 0, W, H); calm(pal(), 0); x.restore(); still = true;
  }
  const mcv = $("#miniViz"), mx = mcv.getContext("2d");
  function miniFrame() {
    const r = mcv.getBoundingClientRect(), d = Math.min(devicePixelRatio || 1, 1.5), w = Math.round(r.width * d), h = Math.round(r.height * d);
    if (!w || !h) return;
    if (mcv.width !== w || mcv.height !== h) { mcv.width = w; mcv.height = h; }
    mx.clearRect(0, 0, w, h);
    if (!fx) return;
    const p = pal(), n = 48, bw = w / n, g = mx.createLinearGradient(0, h, 0, 0); g.addColorStop(0, p.c[1]); g.addColorStop(1, p.c[0]);
    mx.fillStyle = g;
    for (let i = 0; i < n; i++) { const v = bars[Math.floor(i / n * bars.length * .85)]; const bh = Math.max(1, v * h * .9); mx.globalAlpha = .35 + v * .65; mx.fillRect(i * bw + 1, h - bh, bw - 2, bh); }
    mx.globalAlpha = 1;
  }
  function frame(now) {
    raf = 0;
    if (document.body.classList.contains("is-mini")) { sample(now); miniFrame(); if (!a.paused || SysMode.on()) raf = requestAnimationFrame(frame); return; }
    if (!fx) { drawStill(); return; }
    if (!$("#page-player").classList.contains("active")) { if (!SysMode.on()) sample(now); if (!a.paused) raf = requestAnimationFrame(frame); return; }
    resize();
    const bassV = sample(now), p = pal();
    if (mode === "synth") synth(p, bassV); else if (mode === "bars") barsScene(p, bassV); else if (mode === "ring") ring(p, bassV); else if (mode === "wave") waveScene(p); else if (mode === "aurora") aurora(p, bassV); else if (mode === "disco" || mode === "party") disco(p, bassV); else if (mode === "laser") laser(p, bassV); else if (mode === "fireworks") fireworks(p, bassV); else calm(p, bassV);
    raf = requestAnimationFrame(frame);
  }
  function start() { Audio_.connect(); if (!fx) { drawStill(); return; } if (!raf) raf = requestAnimationFrame(frame); }
  window.addEventListener("resize", () => { if (!fx) drawStill(); });
  a.addEventListener("play", start);
  const MODES = ["synth", "bars", "ring", "wave", "aurora", "disco", "laser", "fireworks", "off"];
  return {
    start, setMode, setTheme, setCover, setFx, fx: () => fx, redraw() { if (!fx) drawStill(); }, mode: () => mode, theme: () => theme, external(f) { ext = f; },
    cycle() { const m = MODES[(MODES.indexOf(mode) + 1) % MODES.length]; setMode(m); call("save_settings", { viz_mode: m }); },
  };
})();
$("#vizThemes").innerHTML = Object.entries(THEMES).filter(([k]) => k !== "custom").map(([k, t]) => `<button data-t="${k}" title="${t.name}" style="background:${k === "cover" ? "conic-gradient(#FF2EA6,#FFD319,#00E5FF,#7B2FF7,#FF2EA6)" : `linear-gradient(135deg,${t.c[0]},${t.c[1]})`}"></button>`).join("");
$$("#vizThemes button").forEach(b => b.onclick = () => { Viz.setTheme(b.dataset.t); if (b.dataset.t === "cover") { const c = Player.current(); if (c && c.art) { const i = new Image(); i.crossOrigin = "anonymous"; i.onload = () => Viz.setCover(i); i.src = c.art; } } call("save_settings", { viz_theme: b.dataset.t }); });
$$("#vizModes button").forEach(b => b.onclick = () => { Viz.setMode(b.dataset.v); call("save_settings", { viz_mode: b.dataset.v }); });
/* Cover & Titel: groß in der Mitte ↔ klein oben links (Klick darauf) */
const InfoMin = (() => {
  const page = () => $("#page-player");
  function els() { return $$(".pp-now:not([hidden]) .pp-cover, .pp-now:not([hidden]) .pp-meta, .pp-sys:not([hidden]) .pp-cover, .pp-sys:not([hidden]) .pp-meta"); }
  function set(min, animate) {
    const list = animate ? els() : [], before = list.map(e => e.getBoundingClientRect());
    page().classList.toggle("info-min", !!min);
    $$(".pp-cover, .pp-now .pp-meta, .pp-sys .pp-meta").forEach(e => e.title = min ? "Groß in der Mitte anzeigen" : "Klein oben links anzeigen");
    list.forEach((e, i) => {            // sanft vom alten an den neuen Platz gleiten
      const a = before[i], b = e.getBoundingClientRect(); if (!a.width || !b.width || !e.animate) return;
      e.animate([{ transform: `translate(${a.left - b.left}px,${a.top - b.top}px) scale(${a.width / b.width},${a.height / b.height})`, transformOrigin: "top left" },
                 { transform: "none", transformOrigin: "top left" }], { duration: 380, easing: "cubic-bezier(.2,.8,.2,1)" });
    });
  }
  const toggle = () => { const min = !page().classList.contains("info-min"); set(min, true); call("save_settings", { pp_info_min: min }); };
  ["#ppCover", "#sysCover"].forEach(s => $(s).addEventListener("click", toggle));
  $$(".pp-now .pp-meta, .pp-sys .pp-meta").forEach(m => m.addEventListener("click", e => { if (page().classList.contains("info-min") || e.target.closest("h2")) toggle(); }));
  return { set, toggle };
})();
function toggleFx() { const on = !Viz.fx(); Viz.setFx(on); call("save_settings", { viz_fx: on }); toast(on ? "Lichtshow an" : "Lichtshow aus – nur Musik, ruhiges Bild"); }
$("#ppFx").onclick = toggleFx;

/* ---------------------------------------------------------------- EQ-Oberfläche */
(() => {
  const box = $("#eqBands");
  $("#eqPreset").innerHTML = Object.entries(EQ_PRESETS).map(([k, [n]]) => `<option value="${k}">${n}</option>`).join("") + `<option value="custom">Eigene Einstellung</option>`;
  const lbl = f => f >= 1000 ? f / 1000 + "k" : f;
  box.innerHTML = EQ_FREQS.map((f, i) => `<div class="eq-band" data-i="${i}"><em>0</em><div class="tr"><i class="fill"></i><i class="kn"></i></div><small>${lbl(f)}</small></div>`).join("");
  function draw() {
    Audio_.gains().forEach((g, i) => {
      const b = box.children[i], pos = 50 - g / 12 * 50;
      b.querySelector(".kn").style.top = pos + "%";
      const f = b.querySelector(".fill"); f.style.top = Math.min(pos, 50) + "%"; f.style.bottom = (100 - Math.max(pos, 50)) + "%";
      b.querySelector("em").textContent = (g > 0 ? "+" : "") + Math.round(g);
    });
  }
  function save() { call("save_settings", { eq_gains: Audio_.gains(), eq_preset: $("#eqPreset").value, eq_on: Audio_.isOn() }); }
  [...box.children].forEach(b => {
    const tr = b.querySelector(".tr"), i = +b.dataset.i;
    const set = e => { const r = tr.getBoundingClientRect(), v = Math.round((.5 - (e.clientY - r.top) / r.height) * 24); const g = Audio_.gains(); g[i] = Math.max(-12, Math.min(12, v)); Audio_.setGains(g); $("#eqPreset").value = "custom"; draw(); };
    tr.onmousedown = e => { set(e); const mv = ev => set(ev), up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); save(); }; addEventListener("mousemove", mv); addEventListener("mouseup", up); };
    tr.ondblclick = () => { const g = Audio_.gains(); g[i] = 0; Audio_.setGains(g); draw(); save(); };
  });
  $("#eqPreset").onchange = e => { if (EQ_PRESETS[e.target.value]) { Audio_.setGains(EQ_PRESETS[e.target.value][1]); draw(); save(); } };
  $("#eqOn").onchange = e => { Audio_.setOn(e.target.checked); box.classList.toggle("off", !e.target.checked); save(); };
  window.EQ = { load(s) { if (Array.isArray(s.eq_gains) && s.eq_gains.length === 10) Audio_.setGains(s.eq_gains); $("#eqPreset").value = s.eq_preset || "flat"; Audio_.setOn(s.eq_on !== false); $("#eqOn").checked = s.eq_on !== false; box.classList.toggle("off", s.eq_on === false); draw(); }, draw };
  draw();
})();
function togglePop(id, btn) {
  const p = $(id), open = p.hidden; $$(".pp-pop").forEach(x => x.hidden = true); $$(".pp-tool").forEach(x => x.classList.remove("on"));
  p.style.top = Math.round(btn.getBoundingClientRect().bottom - $("#page-player").getBoundingClientRect().top + 8) + "px";
  p.hidden = !open; btn.classList.toggle("on", open);
  if (id === "#ppEq" && open) { EQ.draw(); if (!Audio_.live()) $("#eqHint").textContent = "Der Equalizer wirkt, sobald ein Titel aus SongGrabber läuft · Doppelklick setzt auf 0 dB"; }
}
$("#ppEqBtn").onclick = e => { e.stopPropagation(); togglePop("#ppEq", e.currentTarget); };
$("#xfSel").onchange = e => { S.settings.xfade = +e.target.value; call("save_settings", { xfade: +e.target.value }); toast(+e.target.value ? `Überblenden: ${e.target.value} s` : "Überblenden aus"); };
$("#normPlay").onchange = e => { S.settings.norm_play = e.target.checked; call("save_settings", { norm_play: e.target.checked }); Player.renorm && Player.renorm(); };
$("#ppColorsBtn").onclick = e => {
  e.stopPropagation(); const b = e.currentTarget, top = $(".pp-top").getBoundingClientRect(), r = b.getBoundingClientRect(), pp = $("#page-player").getBoundingClientRect();
  $("#ppColors").style.left = Math.max(12, Math.min(r.left - pp.left - 120, pp.width - 452)) + "px";
  togglePop("#ppColors", b); if (!$("#ppColors").hidden) Colors.open();
};

/* ---------------------------------------------------------------- Eigene Farben für die Lichtshow */
const Colors = (() => {
  const hx = rgb => "#" + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
  const mix = (a, b, t) => { const A = hexRgb(a), B = hexRgb(b); return hx(A.map((x, i) => x + (B[i] - x) * t)); };
  const hsl = (h, s, l) => { h = ((h % 360) + 360) % 360 / 360; s /= 100; l /= 100;
    const f = n => { const k = (n + h * 12) % 12, a = s * Math.min(l, 1 - l); return 255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))); };
    return hx([f(0), f(8), f(4)]); };
  const fromTheme = t => ({ c0: t.c[0], c1: t.c[1], c2: t.c[2], sun0: t.sun[0], sun1: t.sun[2], sky: t.sky[2] });
  const toHsl = h => { let [r, g, b] = hexRgb(h).map(v => v / 255); const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2; let hh = 0, s = 0;
    if (mx !== mn) { const d = mx - mn; s = l > .5 ? d / (2 - mx - mn) : d / (mx + mn); hh = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; hh *= 60; }
    return [hh, s * 100, l * 100]; };
  let v = fromTheme(THEMES.synth), base = null, saveT = 0;
  function setHue(target) {           // alle Farben gemeinsam drehen – Abstände bleiben, also passt alles weiter
    base = base || Object.assign({}, v);
    const shift = target - toHsl(base.c0)[0];
    v = {}; Object.entries(base).forEach(([k, c]) => { const [h, s, l] = toHsl(c); v[k] = hsl(h + shift, s, l); });
    fill(true); apply();
  }
  function build() {
    THEMES.custom = { name: "Eigene Farben", c: [v.c0, v.c1, v.c2], sun: [v.sun0, mix(v.sun0, v.sun1, .5), v.sun1],
      sky: [mix("#000000", v.sky, .25), mix("#000000", v.sky, .6), v.sky] };
    const st = $("#ppColorsBtn").style; st.setProperty("--cc0", v.c0); st.setProperty("--cc1", v.c1); st.setProperty("--cc2", v.c2);
  }
  function fill(keepHue) { $$("#ppColors [data-ck]").forEach(i => i.value = v[i.dataset.ck]); if (!keepHue) $("#colHue").value = Math.round(toHsl(v.c0)[0]); }
  function apply(save = true) {
    build(); Viz.setTheme("custom");
    if (save) { clearTimeout(saveT); saveT = setTimeout(() => call("save_settings", { viz_custom: v, viz_theme: "custom" }), 400); }
  }
  $$("#ppColors [data-ck]").forEach(i => i.addEventListener("input", () => { v[i.dataset.ck] = i.value; base = null; if (i.dataset.ck === "c0") $("#colHue").value = Math.round(toHsl(v.c0)[0]); apply(); }));
  $("#colHue").addEventListener("input", e => setHue(+e.target.value));
  $("#colPresets").innerHTML = Object.entries(THEMES).filter(([k]) => k !== "custom" && k !== "cover").map(([k, t]) => `<button data-p="${k}" title="${t.name}" style="background:linear-gradient(135deg,${t.c[0]},${t.c[1]})"></button>`).join("");
  $$("#colPresets button").forEach(b => b.onclick = () => { v = fromTheme(THEMES[b.dataset.p]); base = null; fill(); apply(); });
  $("#colRandom").onclick = () => {
    const h = Math.random() * 360, sp = 30 + Math.random() * 60;
    v = { c0: hsl(h, 100, 58), c1: hsl(h + sp, 90, 55), c2: hsl(h + 180, 100, 60), sun0: hsl(h + 50, 100, 72), sun1: hsl(h - 10, 100, 52), sky: hsl(h + sp / 2, 70, 13) };
    base = null; fill(); apply();
  };
  return {
    load(s) { if (s.viz_custom && s.viz_custom.c0) v = Object.assign(fromTheme(THEMES.synth), s.viz_custom); build(); },
    open() { if (Viz.theme() !== "custom" && THEMES[Viz.theme()] && Viz.theme() !== "cover") v = fromTheme(THEMES[Viz.theme()]); base = null; fill(); if (Viz.theme() !== "custom") apply(); },
  };
})();
$("#ppSleepBtn").onclick = e => { e.stopPropagation(); togglePop("#ppSleep", e.currentTarget); };
document.addEventListener("mousedown", e => { if (!e.target.closest(".pp-pop,.pp-tool")) { $$(".pp-pop").forEach(x => x.hidden = true); $$(".pp-tool").forEach(x => x.classList.toggle("on", x.id === "ppSleepBtn" && Sleep.active())); } });

/* ---------------------------------------------------------------- Schlaf-Timer */
const Sleep = (() => {
  const a = $("#audio");
  let until = 0, eot = false, tick = null;
  function set(min) {
    clearInterval(tick); until = 0; eot = false;
    $$(".sleep-opts button").forEach(b => b.classList.toggle("on", +b.dataset.m === min));
    if (min === -1) eot = true;
    else if (min > 0) { until = Date.now() + min * 60000; tick = setInterval(step, 1000); }
    label(); if (min) toast(min === -1 ? "Pausiert nach diesem Titel" : `Schlaf-Timer: ${min} Minuten`, "ok");
  }
  function label() {
    const on = until || eot;
    $("#ppSleepTxt").textContent = eot ? "nach Titel" : until ? fmtTime((until - Date.now()) / 1000) : "Timer";
    $("#ppSleepBtn").classList.toggle("on", !!on);
  }
  function step() {
    const left = (until - Date.now()) / 1000;
    if (left <= 10 && left > 0 && !a.paused) a.volume = Math.max(0, a.volume * .8);
    if (left <= 0) { fade(); return; }
    label();
  }
  function fade() { const v = +$("#ppVol").value / 100; a.pause(); a.volume = v; clearInterval(tick); until = 0; eot = false; label(); $$(".sleep-opts button").forEach(b => b.classList.toggle("on", b.dataset.m === "0")); toast("Gute Nacht – Wiedergabe pausiert 🌙"); }
  $$(".sleep-opts button").forEach(b => b.onclick = () => { set(+b.dataset.m); $("#ppSleep").hidden = true; });
  return { active: () => !!(until || eot), endOfTrack() { if (!eot) return false; fade(); return true; } };
})();

/* ---------------------------------------------------------------- Player-Seite: Bedienung */
$$(".pp-tabs button").forEach(b => b.onclick = () => {
  $$(".pp-tabs button").forEach(x => x.classList.toggle("active", x === b));
  const ly = b.dataset.t === "lyrics";
  $("#ppQueue").hidden = $("#ppQHead").hidden = ly; $("#ppLyBody").hidden = $("#lyHead").hidden = !ly;
  if (ly) { LY.path = ""; loadLyrics(Player.lyricsTrack()); }
});
$("#ppGoLib").onclick = () => go("library");
$("#ppOnline").onclick = () => openOnlineSearch(); $("#ppRadio").onclick = () => go("radio"); $("#ppPcMode").onclick = () => SysMode.set(true);
async function pickAudioFiles() {
  const f = await call("choose_files"); if (!f.length) return [];
  const all = await call("files_expand_audio", f);
  if (!all.length) toast("Keine abspielbaren Audiodateien gefunden.", "err");
  return all;
}
$("#ppOpenFiles").onclick = async () => { const p = await pickAudioFiles(); if (p.length) Player.playPaths(p); };
$("#ppShuffleAll").onclick = async () => { if (!L.items.length) { const r = await call("lib_list"); L.items = r.items; } const p = L.items.map(i => i.path).sort(() => Math.random() - .5); if (p.length) Player.playPaths(p); else toast("Die Bibliothek ist noch leer."); };
$("#ppAdd").onclick = e => {
  ctxMenu(e, [
    { icon: "i-search", label: "Online suchen (YouTube) …", fn: () => openOnlineSearch() },
    { icon: "i-link", label: "Link abspielen …", fn: () => openLinkDialog() },
    { icon: "i-radio", label: "Radiosender …", fn: () => go("radio") },
    "-",
    { icon: "i-plus", label: "Dateien …", fn: async () => { const p = await pickAudioFiles(); if (p.length) Player.addPaths(p); } },
    { icon: "i-folder", label: "Ordner …", fn: async () => { const f = await call("choose_folder"); if (f) { const p = await call("files_expand_audio", [f]); if (p.length) Player.addPaths(p); } } },
    { icon: "i-list", label: "Playlist …", fn: async () => { const pls = await call("playlist_list"); if (!pls.length) return toast("Noch keine Playlists vorhanden."); dialog({ title: "Playlist hinzufügen", icon: "i-list", body: `<div class="pl-pick">${pls.map((p, i) => `<button class="ex-drive" data-i="${i}"><svg><use href="#i-list"/></svg><div><b>${esc(p.name)}</b><small>${p.count} Titel</small></div></button>`).join("")}</div>`, buttons: [{ label: "Abbrechen" }] }); $$("#dlgBox [data-i]").forEach(b => b.onclick = async () => { closeDialog(); Player.addPaths(await call("playlist_paths", pls[+b.dataset.i].path)); }); } },
    { icon: "i-lib", label: "Ganze Bibliothek", fn: async () => { const r = await call("lib_list"); Player.addPaths(r.items.map(i => i.path)); } },
  ]);
};
$("#ppSave").onclick = () => {
  const q = Player.queue(); if (!q.length) return toast("Die Warteschlange ist leer.");
  dialog({ title: "Warteschlange als Playlist speichern", icon: "i-list", body: `<label>Name<input id="plName" value="Meine Playlist ${new Date().toLocaleDateString("de-DE")}"></label>`,
    buttons: [{ label: "Abbrechen" }, { label: "Speichern", cls: "primary", fn: async btn => { await safe(btn, async () => { const n = await call("playlist_save", $("#plName").value.trim() || "Playlist", q.map(t => t.path)); closeDialog(); toast(`Playlist „${n}“ gespeichert`, "ok"); }); } }] });
  setTimeout(() => { const i = $("#plName"); if (i) { i.focus(); i.select(); } }, 50);
};
$("#ppClear").onclick = () => { if (Player.queue().length && confirm("Warteschlange leeren?")) Player.close(); };
async function toggleFull() { const on = await call("toggle_fullscreen").catch(() => false); $(".app").classList.toggle("fs", !!on); }
$("#ppFull").onclick = toggleFull;

/* ---------------------------------------------------------------- Bibliothek */
const L = { items: [], sel: new Set(), sort: { k: "", dir: 1 }, tab: "tracks", playlists: [] };
/* ---------------------------------------------------------------- Update-Hinweis */
async function checkUpdate(manual) {
  let r; try { r = await call("update_check", !!manual); } catch (e) { if (manual) toast("Update-Prüfung fehlgeschlagen.", "err"); return; }
  if (!r || r.skipped) return;
  if (!r.enabled) { if (manual) toast(`Du hast SongGrabber ${r.current}. Die Update-Prüfung ist in dieser Ausgabe noch nicht eingerichtet.`); return; }
  if (r.error) { if (manual) toast("Keine Verbindung zum Update-Server: " + r.error, "err"); return; }
  if (!r.newer) { if (manual) toast(`SongGrabber ${r.current} ist aktuell.`, "ok"); return; }
  if (!manual && S.settings.update_skip === r.version) return;
  const notes = esc(r.notes || "").replace(/^#+\s*/gm, "").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>");
  dialog({ title: `Neue Version ${r.version} verfügbar`, icon: "i-down",
    body: `<p>Du hast <b>${esc(r.current)}</b>. Die neue Version <b>${esc(r.version)}</b> kannst du einfach über die alte installieren${r.platform === "linux" ? " (Paket entpacken und <code>./install.sh</code> starten)" : ""} – Einstellungen, Bibliothek und Musik bleiben erhalten.</p>${notes ? `<div class="upd-notes">${notes}</div>` : ""}`,
    buttons: [{ label: "Diese Version überspringen", fn: () => { closeDialog(); call("save_settings", { update_skip: r.version }); S.settings.update_skip = r.version; } },
              { label: "Später" },
              { label: "Herunterladen", cls: "primary", fn: () => { closeDialog(); call("open_url", r.url); } }] });
}
$("#btnUpdate").onclick = () => checkUpdate(true);

/* ---------------------------------------------------------------- Mini-Player */
/* ---------------------------------------------------------------- Player: Leiste hochrollen & Bedienung einklappen */
const SideBar = (() => {
  const main = $(".pp-main"), side = $(".pp-side"), stage = $(".pp-stage"), dock = $("#ppDock"), AUTO = 60000;
  let off = false, ctl = false, last = Date.now(), leaveT = 0, ctlT = 0;
  const onPlayer = () => $("#page-player").classList.contains("active");
  /* rechte Leiste (Rollo) */
  function set(v, keep) {
    off = v; main.classList.toggle("side-off", v); main.classList.remove("peek");
    if (!keep) save({ pp_side_off: v });
  }
  const peek = v => { clearTimeout(leaveT); main.classList.toggle("peek", v && off); };
  $("#ppSideHide").onclick = e => { e.stopPropagation(); set(true); };
  $("#ppSideTab").onclick = () => { last = Date.now(); set(false); };
  $("#ppSideTab").addEventListener("mouseenter", () => peek(true));
  side.addEventListener("mouseenter", () => { if (off) peek(true); });
  side.addEventListener("mouseleave", () => { if (off) leaveT = setTimeout(() => peek(false), 500); });
  $("#ppSideTab").addEventListener("mouseleave", () => { if (off) leaveT = setTimeout(() => peek(false), 700); });
  /* Bedienung unten (einklappen zu kleinen Knöpfen) */
  function setCtl(v, keep) {
    ctl = v; stage.classList.toggle("ctl-off", v); stage.classList.remove("ctl-peek");
    if (!keep) save({ pp_ctl_off: v });
  }
  const ctlPeek = v => { clearTimeout(ctlT); stage.classList.toggle("ctl-peek", v && ctl); };
  const sys = () => SysMode.on();
  $("#ppCtlHide").onclick = e => { e.stopPropagation(); setCtl(true); };
  $("#dkOpen").onclick = e => { e.stopPropagation(); last = Date.now(); setCtl(false); };
  $("#dkPrev").onclick = () => sys() ? $("#sysPrev").click() : Player.prev();
  $("#dkNext").onclick = () => sys() ? $("#sysNext").click() : Player.next();
  $("#dkPlay").onclick = () => { sys() ? $("#sysPlay").click() : Player.toggle(); setTimeout(dockIcon, 80); };
  function dockIcon() {
    const playing = sys() ? $("#sysPlay use").getAttribute("href") === "#i-pause" : !$("#audio").paused;
    $("#dkPlay use").setAttribute("href", playing ? "#i-pause" : "#i-play");
  }
  setInterval(() => { if (ctl) dockIcon(); }, 700);
  dock.addEventListener("mouseenter", () => ctlPeek(true));
  [$("#ppNow"), $("#ppSys")].forEach(el => {
    el.addEventListener("mouseenter", () => { if (ctl && stage.classList.contains("ctl-peek")) clearTimeout(ctlT); });
    el.addEventListener("mouseleave", () => { if (ctl) ctlT = setTimeout(() => ctlPeek(false), 600); });
  });
  dock.addEventListener("mouseleave", () => { if (ctl) ctlT = setTimeout(() => ctlPeek(false), 900); });
  /* nach 1 Minute ohne Maus/Tastatur: Leiste hoch, Bedienung klein */
  ["mousemove", "keydown", "wheel", "pointerdown"].forEach(ev => document.addEventListener(ev, () => { last = Date.now(); }, { passive: true }));
  setInterval(() => {
    if (!onPlayer() || document.body.classList.contains("is-mini") || S.settings.pp_side_auto === false) return;
    if (Date.now() - last < AUTO) return;
    if (!off && !side.matches(":hover")) set(true, true);
    if (!ctl && !$("#ppNow").matches(":hover") && !$("#ppSys").matches(":hover")) setCtl(true, true);
  }, 5000);
  return { set, toggle: () => set(!off), toggleCtl: () => setCtl(!ctl), load: s => { set(!!s.pp_side_off, true); setCtl(!!s.pp_ctl_off, true); } };
})();

const Mini = (() => {
  let on = false, auto = false, T = 0;
  const sys = () => SysMode.on();
  function info() {
    const cover = sys() ? $("#sysCoverImg") : $("#ppCoverImg");
    const t = sys() ? $("#sysTitle").textContent : $("#ppTitle").textContent;
    const ar = sys() ? $("#sysArtist").textContent : $("#ppArtist").textContent;
    $("#miTitle").textContent = t && t !== "–" ? t : "Nichts in der Wiedergabe";
    $("#miArtist").textContent = ar && ar !== "–" ? ar : "";
    $("#miCover").style.backgroundImage = cover && !cover.classList.contains("none") ? cover.style.backgroundImage : "";
    const a = $("#audio"), lyr = LY.synced && LY.idx >= 0 && LY.lines[LY.idx] ? LY.lines[LY.idx].txt : "";
    $("#miLyric").textContent = lyr;
    $("#miProg").style.width = !sys() && isFinite(a.duration) && a.duration ? (a.currentTime / a.duration * 100) + "%" : "0%";
    const playing = sys() ? $("#sysPlay use").getAttribute("href") === "#i-pause" : !a.paused;
    $("#miPlay use").setAttribute("href", playing ? "#i-pause" : "#i-play");
  }
  function show(v, isAuto) {
    on = v; auto = !!isAuto; document.body.classList.toggle("is-mini", v); clearInterval(T);
    if (v) { info(); T = setInterval(info, 400); Viz.start(); }
  }
  async function set(v) {
    if (v === on && !auto) return;
    busy = Date.now() + 1500;
    show(v);
    try { await call("mini", v); } catch (e) { }
    busy = Date.now() + 400;
  }
  let busy = 0;
  window.addEventListener("resize", () => {             // sehr kleines Fenster → automatisch Mini-Ansicht
    if (Date.now() < busy || document.body.classList.contains("is-scrbar")) return;   // gerade selbst umgeschaltet / Aufnahme-Leiste
    const tiny = innerWidth < 860 || innerHeight < 520;
    if (tiny && !on) show(true, true);
    else if (!tiny && on) {                              // von Hand vergrößert/maximiert → Mini verlassen
      const was = auto; show(false);
      if (!was) call("mini", false, true).catch(() => { });
    }
  });
  $("#miPrev").onclick = () => sys() ? $("#sysPrev").click() : Player.prev();
  $("#miNext").onclick = () => sys() ? $("#sysNext").click() : Player.next();
  $("#miPlay").onclick = () => { sys() ? $("#sysPlay").click() : Player.toggle(); setTimeout(info, 80); };
  $("#miBack").onclick = () => set(false);
  $("#mini").addEventListener("dblclick", e => { if (!e.target.closest("button")) set(false); });
  $("#pMini").onclick = $("#ppMini").onclick = () => set(true);
  return { set, on: () => on };
})();

/* ---------------------------------------------------------------- Bibliothek aufräumen */
const mb = n => n >= 1073741824 ? (n / 1073741824).toFixed(1).replace(".", ",") + " GB" : Math.round(n / 1048576) + " MB";
$("#btnLibClean").onclick = () => openCleanup();
async function openCleanup() {
  dialog({ title: "Bibliothek aufräumen", icon: "i-wand", wide: true,
    body: `<div id="clBody"><div class="cl-wait"><span class="spinner"></span><span>Bibliothek wird geprüft … <b id="clProg"></b></span></div></div>`,
    buttons: [{ label: "Schließen" }] });
  try { await call("cleanup_start"); } catch (e) { }
  let st;
  for (;;) {
    st = await call("cleanup_status");
    if (!$("#clBody")) return;
    if (st.total) $("#clProg").textContent = `${st.done} / ${st.total}`;
    if (!st.running) break;
    await new Promise(r => setTimeout(r, 400));
  }
  if (st.error || !st.result) { $("#clBody").innerHTML = `<div class="cl-empty">Prüfen fehlgeschlagen: ${esc(st.error || "unbekannt")}</div>`; return; }
  const r = st.result, root = (S.settings.output_dir || "").replace(/[\\/]+$/, "");
  const rel = p => p.startsWith(root) ? p.slice(root.length + 1) : p;
  const nDup = r.dups.reduce((s, g) => s + g.files.length - 1, 0);
  $("#clBody").innerHTML = `
    <div class="seg cl-tabs" id="clTabs"><button data-t="dup" class="active">Doppelte Titel (${nDup})</button><button data-t="miss">Fehlende Angaben (${r.fill.length})</button><button data-t="dirs">Leere Ordner (${r.empty.length})</button></div>
    <div data-p="dup">${r.dups.length ? `
      <div class="cl-sum"><span><b>${r.dups.length}</b> Lieder liegen mehrfach vor – <b>${mb(r.dup_free)}</b> können frei werden. Vorgeschlagen wird jeweils die beste Fassung (FLAC/WAV vor MP3, höhere Bitrate, mit Cover). Häkchen = in den Papierkorb.</span></div>
      <div class="cl-list">${r.dups.map((g, gi) => `<div class="cl-group"><h5>${esc(g.artist || "")} – ${esc(g.title || "")}</h5>${g.files.map((f, fi) => `
        <label class="cl-file"><input type="checkbox" data-g="${gi}" data-p="${esc(f.path)}" ${f.keep ? "" : "checked"}>
          <button class="pl" data-play="${esc(f.path)}" title="Anhören"><svg><use href="#i-play"/></svg></button>
          <span><span class="q">${esc(f.q)}</span> · ${mb(f.size)}${f.cover ? " · mit Cover" : ""}${f.album ? " · " + esc(f.album) : ""}<br><span class="where">${esc(rel(f.path))}</span></span>
          <span></span><span class="badge ${f.keep ? "keep" : "del"}">${f.keep ? "BEHALTEN" : "LÖSCHEN"}</span></label>`).join("")}</div>`).join("")}</div>
      <div class="row" style="margin-top:12px;justify-content:flex-end"><button class="primary" id="clDel"><svg><use href="#i-trash"/></svg><span>Markierte in den Papierkorb</span></button></div>`
      : `<div class="cl-empty">Keine doppelten Titel gefunden. 🎉</div>`}</div>
    <div data-p="miss" hidden>${r.fill.length ? `
      <div class="cl-miss"><div><b>${r.missing.cover}</b><small>ohne Cover</small></div><div><b>${r.missing.album}</b><small>ohne Album</small></div><div><b>${r.missing.genre}</b><small>ohne Genre</small></div><div><b>${r.missing.year}</b><small>ohne Jahr</small></div></div>
      <p class="muted" style="font-size:13px">SongGrabber sucht für <b>${r.fill.length}</b> Titel online nach Album, Genre, Jahr, Titelnummer und Cover. <b>Vorhandene Angaben bleiben unverändert</b> – nur Lücken werden gefüllt. Danach werden die Titel passend einsortiert (Interpret / Album / Titel).</p>
      <div class="row" style="margin-top:12px;justify-content:flex-end"><button class="primary" id="clFill"><svg><use href="#i-wand"/></svg>Online ergänzen</button></div>`
      : `<div class="cl-empty">Alle Titel haben Cover, Album, Genre und Jahr. 🎉</div>`}</div>
    <div data-p="dirs" hidden>${r.empty.length ? `
      <p class="muted" style="font-size:13px">Diese Ordner enthalten keine Musik mehr (höchstens Reste wie <code>folder.jpg</code> oder <code>desktop.ini</code>):</p>
      <div class="cl-dirs">${r.empty.slice(0, 200).map(d => esc(rel(d))).join("<br>")}${r.empty.length > 200 ? `<br>… und ${r.empty.length - 200} weitere` : ""}</div>
      <div class="row" style="margin-top:12px;justify-content:flex-end"><button class="primary" id="clDirs"><svg><use href="#i-trash"/></svg>Leere Ordner entfernen</button></div>`
      : `<div class="cl-empty">Keine leeren Ordner. 🎉</div>`}</div>`;
  $$("#clTabs button").forEach(b => b.onclick = () => { $$("#clTabs button").forEach(x => x.classList.toggle("active", x === b)); $$("#clBody [data-p]").forEach(p => { if (p.tagName === "DIV") p.hidden = p.dataset.p !== b.dataset.t; }); });
  const count = () => { const n = $$("#clBody input[data-g]:checked").length; const b = $("#clDel"); if (b) { b.disabled = !n; b.querySelector("span").textContent = n ? `${n} markierte in den Papierkorb` : "Nichts markiert"; } };
  $$("#clBody input[data-g]").forEach(c => c.onchange = () => {
    const lab = c.closest(".cl-file").querySelector(".badge"); lab.className = "badge " + (c.checked ? "del" : "keep"); lab.textContent = c.checked ? "LÖSCHEN" : "BEHALTEN"; count();
  });
  $$("#clBody [data-play]").forEach(b => b.onclick = e => { e.preventDefault(); e.stopPropagation(); Player.playPaths([b.dataset.play]); });
  count();
  if ($("#clDel")) $("#clDel").onclick = e => safe(e.currentTarget, async () => {
    const sel = $$("#clBody input[data-g]:checked");
    const all = r.dups.findIndex((g, gi) => g.files.every(f => sel.some(c => +c.dataset.g === gi && c.dataset.p === f.path)));
    if (all >= 0) return toast(`Bei „${r.dups[all].title}“ sind alle Fassungen markiert – mindestens eine muss bleiben.`, "err");
    const list = sel.map(c => c.dataset.p);
    Player.release(list);
    const res = await call("lib_delete", list);
    sel.forEach(c => c.closest(".cl-file").remove());
    toast(`${res.deleted} Dateien ${res.recycle ? "in den Papierkorb verschoben" : "gelöscht"}`, "ok"); count(); loadLibrary();
  });
  if ($("#clFill")) $("#clFill").onclick = e => safe(e.currentTarget, async () => { await call("cleanup_fill", r.fill); e.currentTarget.disabled = true; toast(`${r.fill.length} Titel werden ergänzt – läuft in der Warteschlange`, "ok"); });
  if ($("#clDirs")) $("#clDirs").onclick = e => safe(e.currentTarget, async () => { const n = await call("cleanup_empty", r.empty); e.currentTarget.disabled = true; toast(`${n} leere Ordner entfernt`, "ok"); });
}

async function loadLibrary(force) {
  if (force) { await call("lib_scan", true); toast("Bibliothek wird neu eingelesen …"); }
  const r = await call("lib_list");
  L.items = r.items; renderLibrary(); libStatus(r.status);
  if (r.status.scanning) setTimeout(() => loadLibrary(false), 1200);
  if (L.tab === "playlists") loadPlaylists();
}
function libStatus(st) {
  $("#libCount").textContent = st.count || "";
  $("#libInfo").textContent = st.scanning ? `Lese ein … ${st.done}/${st.total}` : `${L.items.length} Titel`;
}
$("#btnLibScan").onclick = () => loadLibrary(true);
$$("#libTabs button").forEach(b => b.onclick = () => {
  L.tab = b.dataset.tab;
  $$("#libTabs button").forEach(x => x.classList.toggle("active", x === b));
  $("#libTracks").hidden = L.tab !== "tracks"; $("#libPlaylists").hidden = L.tab !== "playlists";
  $("#libSearchWrap").style.visibility = $("#libGroup").style.visibility = L.tab === "tracks" ? "" : "hidden";
  if (L.tab === "playlists") loadPlaylists();
});
$("#libSearch").oninput = () => { clearTimeout(L.t); L.t = setTimeout(renderLibrary, 150); };
$("#libGroup").onchange = renderLibrary;
$$("#libTracks [data-sort]").forEach(h => h.onclick = () => {
  const k = h.dataset.sort; L.sort = { k, dir: L.sort.k === k ? -L.sort.dir : 1 };
  $$("#libTracks [data-sort]").forEach(x => x.classList.remove("asc", "desc")); h.classList.add(L.sort.dir > 0 ? "asc" : "desc");
  renderLibrary();
});
function libFiltered() {
  const q = $("#libSearch").value.trim().toLowerCase();
  let arr = L.items;
  if (q) arr = arr.filter(i => [i.title, i.artist, i.album, i.genre, i.year].join(" ").toLowerCase().includes(q));
  if (L.sort.k) { const k = L.sort.k, d = L.sort.dir; arr = [...arr].sort((a, b) => { const x = a[k] ?? "", y = b[k] ?? ""; return (typeof x === "number" ? x - y : String(x).localeCompare(String(y), "de")) * d; }); }
  return arr;
}
const decade = i => /^\d{4}/.test(i.year || "") ? i.year.slice(0, 3) + "0er" : "Ohne Jahr";
function renderLibrary() {
  const arr = libFiltered(), g = $("#libGroup").value;
  const row = (i) => `<div class="lrow lib-cols ${L.sel.has(i.path) ? "sel" : ""}" data-path="${esc(i.path)}"><label class="check"><input type="checkbox" ${L.sel.has(i.path) ? "checked" : ""}><span></span></label><button class="pbtn" title="Abspielen"><svg><use href="#i-play"/></svg></button><span class="t" title="${esc(i.path)}">${esc(i.title)}</span><span class="muted">${esc(i.artist)}</span><span class="muted">${esc(i.album)}</span><span class="muted">${esc(i.genre)}</span><span class="muted">${esc(i.year)}</span><span class="d">${fmtTime(i.duration)}</span></div>`;
  let html = "";
  if (!arr.length) html = `<div class="empty" style="margin:18px;border:0">${L.items.length ? "Keine Treffer." : "Noch keine Titel im Zielordner. Sobald du etwas herunterlädst, rippst oder aufnimmst, erscheint es hier."}</div>`;
  else if (g) {
    const groups = new Map();
    arr.forEach(i => { const k = g === "decade" ? decade(i) : (i[g] || "Unbekannt"); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(i); });
    [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0], "de")).forEach(([k, list]) => {
      if (g === "album" || (g !== "decade" && !L.sort.k)) list.sort((a, b) => (a.album || "").localeCompare(b.album || "", "de") || (a.track - b.track));
      html += `<div class="group-h">${esc(k)} <small>${list.length} Titel</small><button class="ghost sm" data-gplay="${esc(k)}"><svg><use href="#i-play"/></svg>Abspielen</button></div>` + list.map(row).join("");
    });
    L.groups = groups;
  } else html = arr.map(row).join("");
  $("#libList").innerHTML = html;
  bindLibRows(arr);
  libSelInfo(); Player.markRows();
}
function bindLibRows(arr) {
  const byPath = new Map(L.items.map(i => [i.path, i]));
  $$("#libList [data-gplay]").forEach(b => b.onclick = () => Player.playPaths(L.groups.get(b.dataset.gplay).map(i => i.path)));
  $$("#libList .lrow").forEach(r => {
    const p = r.dataset.path, visible = () => $$("#libList .lrow").map(x => x.dataset.path);
    r.querySelector("input").onchange = e => { e.target.checked ? L.sel.add(p) : L.sel.delete(p); r.classList.toggle("sel", e.target.checked); libSelInfo(); };
    r.querySelector(".pbtn").onclick = () => { const v = visible(); Player.playPaths(v, v.indexOf(p)); };
    r.ondblclick = () => { const v = visible(); Player.playPaths(v, v.indexOf(p)); };
    r.oncontextmenu = e => {
      e.preventDefault();
      const sel = L.sel.size && L.sel.has(p) ? [...L.sel] : [p], it = byPath.get(p) || {};
      ctxMenu(e, [
        { icon: "i-play", label: sel.length > 1 ? `${sel.length} Titel abspielen` : "Abspielen", fn: () => Player.playPaths(sel) },
        { icon: "i-next", label: "Als Nächstes abspielen", fn: () => Player.addPaths(sel, { nextUp: true }) },
        { icon: "i-list", label: "An Wiedergabeliste anhängen", fn: () => Player.addPaths(sel) },
        "-",
        { icon: "i-tag", label: sel.length > 1 ? `Tags von ${sel.length} Titeln bearbeiten …` : "Tags bearbeiten …", fn: () => openTagEditor(sel) },
        { icon: "i-lyrics", label: "Songtext suchen & einbetten", fn: async () => { await call("lyrics_files", sel); toast("Songtexte werden gesucht – siehe Warteschlange", "ok"); } },
        { icon: "i-finger", label: "Titel erkennen (Fingerabdruck)", fn: () => identifyFiles(sel) },
        { icon: "i-cut", label: "Anfang/Ende kürzen …", disabled: sel.length > 1, fn: () => openTrim(p) },
        { icon: "i-usb", label: "Auf USB-Stick/Handy übertragen …", fn: () => openExport(sel.length > 1 ? "Auswahl" : (it.artist || "Musik"), sel) },
        { icon: "i-trash", label: sel.length > 1 ? `${sel.length} Titel löschen …` : "Löschen …", kbd: "Entf", fn: () => deleteTracks(sel) },
        "-",
        { icon: "i-wand", label: sel.length > 1 ? "Als Playlist speichern …" : "Playlist aus diesem Interpreten", fn: () => sel.length > 1 ? openPlModal("selection", sel) : openPlModal("random", null, { artist: it.artist, name: it.artist, count: 999 }) },
        "-",
        { icon: "i-search", label: `Mehr von „${it.artist || "?"}“`, disabled: !it.artist, fn: () => { $("#libSearch").value = it.artist; renderLibrary(); } },
        { icon: "i-folder", label: "Im Ordner anzeigen", fn: () => call("open_path", p) },
        { icon: "i-copy", label: "Pfad kopieren", fn: () => copyText(p) },
      ]);
    };
  });
}
function libSelInfo() {
  const n = L.sel.size;
  $("#libSel").textContent = n ? `${n} ausgewählt` : `${libFiltered().length} Titel angezeigt`;
  $("#btnLibPlaySel").disabled = $("#btnLibToPl").disabled = $("#btnLibDel").disabled = !n;
  $("#btnLibExport").innerHTML = `<svg><use href="#i-usb"/></svg>${n ? "Auswahl übertragen" : "Alle angezeigten übertragen"}`;
  const all = $$("#libList .lrow input"); $("#libAll").checked = all.length && all.every(c => c.checked);
}
$("#libAll").onchange = e => { $$("#libList .lrow").forEach(r => { const c = r.querySelector("input"); c.checked = e.target.checked; e.target.checked ? L.sel.add(r.dataset.path) : L.sel.delete(r.dataset.path); r.classList.toggle("sel", c.checked); }); libSelInfo(); };
$("#btnLibPlaySel").onclick = () => Player.playPaths([...L.sel]);
$("#btnLibShuffle").onclick = () => { const v = libFiltered().map(i => i.path).sort(() => Math.random() - .5); if (v.length) Player.playPaths(v); };
$("#btnLibToPl").onclick = () => openPlModal("selection", [...L.sel]);
$("#btnLibDel").onclick = () => deleteTracks([...L.sel]);
async function deleteTracks(sel) {
  if (!sel || !sel.length) return toast("Bitte zuerst Titel anhaken.");
  const byPath = new Map(L.items.map(i => [i.path, i]));
  const names = sel.slice(0, 5).map(p => { const i = byPath.get(p) || {}; return `<li>${esc((i.artist ? i.artist + " – " : "") + (i.title || p.split(/[\\/]/).pop()))}</li>`; }).join("");
  dialog({ title: sel.length > 1 ? `${sel.length} Titel löschen?` : "Titel löschen?", icon: "i-trash",
    body: `<ul style="margin:0 0 12px;padding-left:20px;color:#C9CDD6;line-height:1.6">${names}${sel.length > 5 ? `<li class="muted">… und ${sel.length - 5} weitere</li>` : ""}</ul>
      <p class="muted" style="margin:0">Die Dateien werden in den <b>Papierkorb</b> verschoben und lassen sich von dort wiederherstellen. Playlists überspringen gelöschte Titel automatisch.</p>`,
    buttons: [{ label: "Abbrechen" }, { label: "In den Papierkorb", cls: "danger", fn: async btn => {
      await safe(btn, async () => {
        Player.release(sel);
        await new Promise(r => setTimeout(r, 250));          // Wiedergabe gibt die Datei frei
        const r = await call("lib_delete", sel);
        closeDialog();
        sel.forEach(p => L.sel.delete(p));
        toast(r.errors.length ? `${r.deleted} gelöscht · ${r.errors.length} nicht möglich: ${r.errors[0]}` : `${r.deleted} Titel ${r.recycle ? "in den Papierkorb verschoben" : "gelöscht"}`, r.errors.length ? "err" : "ok");
        loadLibrary();
      });
    } }] });
}
document.addEventListener("keydown", e => {
  if (e.key !== "Delete" || !$("#page-library").classList.contains("active") || L.tab !== "tracks") return;
  if (e.target.closest("input,textarea,select") || !$("#dlg").hidden || !L.sel.size) return;
  e.preventDefault(); deleteTracks([...L.sel]);
});
$("#btnLibExport").onclick = () => { const sel = L.sel.size ? [...L.sel] : libFiltered().map(i => i.path); openExport(L.sel.size ? "Auswahl" : "Musik", sel); };

async function loadPlaylists() {
  L.playlists = await call("playlist_list");
  $("#libPlaylists").innerHTML = L.playlists.length ? L.playlists.map((p, i) => `<div class="pl-card" data-i="${i}"><div class="pl-ico"><svg><use href="#i-list"/></svg></div><b title="${esc(p.path)}">${esc(p.name)}</b><small>${p.count} Titel · ${p.auto ? "Playlist-Ordner" : "bei den Dateien"}</small><div class="row"><button class="primary sm" data-a="play"><svg><use href="#i-play"/></svg>Abspielen</button><button class="ghost sm" data-a="shuffle" title="Zufällig"><svg><use href="#i-shuffle"/></svg></button><button class="ghost sm" data-a="open" title="Im Ordner anzeigen"><svg><use href="#i-folder"/></svg></button><button class="ghost sm" data-a="usb" title="Auf USB-Stick/Handy übertragen"><svg><use href="#i-usb"/></svg></button><button class="ghost sm" data-a="del" title="Löschen"><svg><use href="#i-trash"/></svg></button></div></div>`).join("")
    : `<div class="empty" style="grid-column:1/-1"><div class="empty-art"><svg><use href="#i-list"/></svg></div><h3>Noch keine Playlists</h3><p>Lass sie dir über „Playlists erstellen“ automatisch anlegen – nach Interpret, Album, Genre, Jahrzehnt oder als Zufallsmix.</p></div>`;
  $$("#libPlaylists .pl-card").forEach(c => {
    const p = L.playlists[+c.dataset.i];
    const items = async () => call("playlist_items", p.path);
    c.querySelector("[data-a=play]").onclick = async () => { const it = await items(); it.length ? Player.playItems(it) : toast("Playlist ist leer.", "err"); };
    c.querySelector("[data-a=shuffle]").onclick = async () => { const it = (await items()).sort(() => Math.random() - .5); if (it.length) Player.playItems(it); };
    c.querySelector("[data-a=open]").onclick = () => call("open_path", p.path);
    c.querySelector("[data-a=usb]").onclick = async () => openExport(p.name, await call("playlist_paths", p.path));
    c.querySelector("[data-a=del]").onclick = async () => { if (confirm(`Playlist „${p.name}“ löschen? (Die Musikdateien bleiben erhalten.)`)) { await call("playlist_delete", p.path); loadPlaylists(); } };
  });
}

/* ---------------------------------------------------------------- Playlist-Generator */
const PL_HINT = {
  artist: "Legt für jeden Interpreten eine Playlist an, sortiert nach Album und Titelnummer.",
  album: "Eine Playlist pro Album in der richtigen Titelreihenfolge – ideal für Autoradio und Handy.",
  genre: "Gruppiert nach dem Genre-Tag. Fehlende Genres ergänzt SongGrabber bei neuen Downloads automatisch.",
  decade: "Sortiert nach Erscheinungsjahr in 70er, 80er, 90er … – braucht das Jahr im Tag.",
  recent: "Alles, was in den letzten Tagen dazugekommen ist, neueste zuerst.",
  random: "Zufällige Auswahl – optional auf ein Genre oder einen Interpreten beschränkt.",
  selection: "Die markierten Titel aus der Liste als eigene Playlist.",
};
let plMode = "artist", plSel = [];
function openPlModal(mode, sel, preset) {
  plSel = sel || [...L.sel];
  ["mName", "mGenre", "mArtist", "mPrefix"].forEach(id => $("#" + id).value = "");
  if (preset) { if (preset.artist) $("#mArtist").value = preset.artist; if (preset.name) $("#mName").value = preset.name; if (preset.count) $("#mCount").value = preset.count; }
  setPlMode(mode || "artist"); $("#modal").hidden = false;
}
function setPlMode(m) {
  plMode = m;
  $$("#plModes button").forEach(b => b.classList.toggle("active", b.dataset.m === m));
  $$(".pl-opts label").forEach(l => l.hidden = !l.dataset.for.split(" ").includes(m));
  $("#mHint").textContent = PL_HINT[m];
  plPreview();
}
function plPreview() {
  const items = L.items, min = +$("#mMin").value || 1;
  let txt = "";
  if (["artist", "album", "genre", "decade"].includes(plMode)) {
    const c = {}; items.forEach(i => { const k = plMode === "decade" ? (/^\d{4}/.test(i.year || "") ? decade(i) : "") : i[plMode]; if (k) c[k] = (c[k] || 0) + 1; });
    const n = Object.values(c).filter(v => v >= min).length; txt = `→ ${n} Playlist${n === 1 ? "" : "s"}`;
  } else if (plMode === "selection") txt = `→ ${plSel.length} Titel`;
  else if (plMode === "recent") { const cut = Date.now() / 1000 - (+$("#mDays").value || 30) * 86400; txt = `→ ${items.filter(i => i.mtime >= cut).length} Titel`; }
  else if (plMode === "random") { let p = items; const g = $("#mGenre").value.trim().toLowerCase(), a = $("#mArtist").value.trim().toLowerCase(); if (g) p = p.filter(i => (i.genre || "").toLowerCase() === g); if (a) p = p.filter(i => (i.artist || "").toLowerCase().includes(a)); txt = `→ ${Math.min(p.length, +$("#mCount").value || 50)} von ${p.length} Titeln`; }
  $("#mPreview").textContent = txt;
}
$$("#plModes button").forEach(b => b.onclick = () => setPlMode(b.dataset.m));
$$(".pl-opts input").forEach(i => i.oninput = plPreview);
$("#btnPlMake").onclick = async () => { if (!L.items.length) await loadLibrary(); openPlModal(L.sel.size ? "selection" : "artist"); };
$("#mClose").onclick = $("#mCancel").onclick = () => $("#modal").hidden = true;
$("#modal").onclick = e => { if (e.target.id === "modal") $("#modal").hidden = true; };
$("#mGo").onclick = e => safe(e.currentTarget, async () => {
  const made = await call("playlist_create", plMode, { min: +$("#mMin").value, prefix: $("#mPrefix").value, days: +$("#mDays").value, count: +$("#mCount").value, genre: $("#mGenre").value.trim(), artist: $("#mArtist").value.trim(), name: $("#mName").value.trim(), paths: plSel });
  $("#modal").hidden = true;
  toast(made.length === 1 ? `Playlist „${made[0].replace(/\.m3u8$/, "")}“ erstellt` : `${made.length} Playlists erstellt`, "ok");
  L.tab = "playlists"; $$("#libTabs button")[1].click();
});

/* ---------------------------------------------------------------- Dialog-Baustein */
let dlgClose = null;
function dialog({ title, icon = "i-tag", body = "", wide = false, buttons = [], onClose }) {
  const box = $("#dlgBox");
  box.className = "modal" + (wide ? " wide" : "");
  box.innerHTML = `<div class="m-head"><h3><svg><use href="#${icon}"/></svg>${esc(title)}</h3><button class="x" data-close><svg><use href="#i-x"/></svg></button></div><div class="m-body">${body}</div><div class="m-foot"><div class="grow muted" data-foot></div>${buttons.map((b, i) => `<button class="${b.cls || "ghost"}" data-b="${i}" ${b.id ? `id="${b.id}"` : ""}>${b.label}</button>`).join("")}</div>`;
  buttons.forEach((b, i) => { const el = box.querySelector(`[data-b="${i}"]`); el.onclick = () => b.fn ? b.fn(el) : closeDialog(); });
  box.querySelector("[data-close]").onclick = closeDialog;
  dlgClose = onClose || null;
  $("#dlg").hidden = false;
  return box;
}
function closeDialog() { if ($("#dlg").hidden) return; $("#dlg").hidden = true; const f = dlgClose; dlgClose = null; if (f) f(); }
$("#dlg").addEventListener("mousedown", e => { if (e.target.id === "dlg") closeDialog(); });

/* ---------------------------------------------------------------- Kapitel (Full-Album-Videos) */
function showChapters(info) {
  const ch = info.type === "single" && info.chapters && info.chapters.length ? info.chapters : null;
  $("#chapBox").hidden = !ch;
  if (!ch) { $("#resTrackWrap").hidden = $("#resNoWrap").hidden = info.type !== "single"; return; }
  $("#chapHead").textContent = `${ch.length} Kapitel gefunden` + (info.full_album ? " – das sieht nach einem kompletten Album aus" : "");
  $("#chapOn").checked = !!info.full_album;
  $("#chapList").innerHTML = ch.map(c => `<div class="chap-row"><span class="n">${String(c.n).padStart(2, "0")}</span><input value="${esc(c.title)}"><span class="d">${fmtTime(c.end - c.start)}</span></div>`).join("");
  chapToggle();
}
function chapToggle() {
  const on = $("#chapOn").checked, L = S.link || {};
  $("#chapList").classList.toggle("off", !on);
  $("#resTrackWrap").hidden = $("#resNoWrap").hidden = on;
  $("#chapSub").textContent = on ? "Jedes Kapitel wird ein eigener Titel – mit Nummer, Album und Cover. Titel lassen sich hier ändern." : "Aus: das Video wird als ein einziger Titel gespeichert.";
  if (on && !$("#resAlbum").value && L.chapter_album) $("#resAlbum").value = L.chapter_album;
  $("#btnDownload").textContent = on ? `${(L.chapters || []).length} Titel herunterladen & umwandeln` : "Herunterladen & umwandeln";
}
$("#chapOn").onchange = chapToggle;

/* ---------------------------------------------------------------- Tag-Editor */
const TE_FIELDS = [["title", "Titel", "span2"], ["artist", "Interpret"], ["album_artist", "Album-Interpret"], ["album", "Album", "span2"], ["track", "Titel-Nr. (z. B. 3/12)"], ["disc", "CD-Nr. (z. B. 1/2)"], ["date", "Jahr"], ["genre", "Genre"]];
async function openTagEditor(paths) {
  const data = await call("tags_read", paths);
  if (!data.length) return toast("Datei nicht gefunden.", "err");
  const multi = data.length > 1, first = data[0], dirty = new Set();
  let cover = { mode: "keep" }, lyricsDirty = false;
  const common = k => data.every(d => d[k] === first[k]) ? first[k] : null;
  const fields = TE_FIELDS.filter(([k]) => !(multi && (k === "title" || k === "track"))).map(([k, label, cls]) => {
    const v = common(k);
    return `<label class="${cls || ""}">${label}<input data-f="${k}" value="${esc(v ?? "")}" ${v === null ? `class="mixed" placeholder="‹verschiedene Werte – bleiben erhalten›"` : ""} ${k === "genre" ? 'list="genres"' : ""}></label>`;
  }).join("");
  const box = dialog({
    title: multi ? `Tags von ${data.length} Titeln bearbeiten` : "Tags bearbeiten", icon: "i-tag", wide: true,
    body: `<div class="te"><div class="te-cover"><div class="cv ${first.art ? "" : "none"}" id="teCv" style="${first.art ? `background-image:url('${first.art}')` : ""}"></div>
      <div class="row"><button class="ghost sm" id="teCvFile">Bild wählen</button><button class="ghost sm" id="teCvDel">Entfernen</button></div>
      <small class="muted">${esc(multi ? `${data.length} Dateien` : first.format + " · " + fmtTime(first.duration))}</small></div>
      <div><div class="te-fields">${fields}</div>
      <div class="te-online"><button class="ghost sm" id="teOnline"><svg><use href="#i-search"/></svg>Online ergänzen</button><span id="teOnInfo">Album, Jahr, Genre und Cover anhand von Interpret + Titel suchen</span></div>
      ${multi ? "" : `<label style="margin-top:14px">Songtext <span class="muted" id="teLyInfo">${tagsIsLrc(first.lyrics) ? "· mitlaufend (LRC)" : ""}</span><textarea id="teLy" spellcheck="false" placeholder="Kein Songtext – „Songtext suchen“ oder hier einfügen">${esc(first.lyrics || "")}</textarea></label>
      <div class="te-online"><button class="ghost sm" id="teLyFind"><svg><use href="#i-lyrics"/></svg>Songtext suchen</button><span id="teLyFound"></span></div>`}
      <label class="switch" style="margin-top:8px"><input type="checkbox" id="teRename" checked><i></i><span>Datei passend umbenennen &amp; einsortieren</span><small>nach deiner Ordnerstruktur (Interpret / Album / Titel)</small></label></div></div>`,
    buttons: [{ label: "Abbrechen" }, { label: "Speichern", cls: "primary", fn: saveTags }],
  });
  $$("[data-f]", box).forEach(i => i.oninput = () => { dirty.add(i.dataset.f); i.classList.remove("mixed"); });
  const setCv = (url, mode, value) => { const cv = $("#teCv"); cv.classList.toggle("none", !url); cv.style.backgroundImage = url ? `url("${url}")` : ""; cover = { mode, value }; };
  $("#teCv").dataset.drop = "image:te"; window.__teCover = p => setCv("file:///" + p.replace(/\\/g, "/"), "file", p);
  $("#teCvFile").onclick = async () => { const p = await call("choose_image"); if (p) setCv("file:///" + p.replace(/\\/g, "/"), "file", p); };
  $("#teCvDel").onclick = () => setCv("", "remove");
  $("#teOnline").onclick = e => safe(e.currentTarget, async () => {
    const a = $('[data-f="artist"]', box).value.trim(), t = multi ? "" : $('[data-f="title"]', box).value.trim();
    if (!a || (!multi && !t)) return toast("Bitte Interpret und Titel eintragen.");
    const m = await call("tags_online", a, t || first.title);
    if (!m || !m.album) return $("#teOnInfo").textContent = "Nichts gefunden – Schreibweise prüfen.";
    const fill = { album: m.album, album_artist: m.album_artist, genre: m.genre, date: m.date, ...(multi ? {} : { track: m.track }) };
    Object.entries(fill).forEach(([k, v]) => { const i = $(`[data-f="${k}"]`, box); if (i && v) { i.value = v; dirty.add(k); i.classList.remove("mixed"); } });
    if (m.cover_url) setCv(m.cover_url.replace("1000x1000", "600x600"), "url", m.cover_url);
    $("#teOnInfo").innerHTML = `<b style="color:var(--ok)">✓ Gefunden</b> über ${esc(m.source)}: ${esc([m.album, m.date, m.genre].filter(Boolean).join(" · "))}`;
  });
  if (!multi) {
    $("#teLy").oninput = () => { lyricsDirty = true; $("#teLyInfo").textContent = tagsIsLrc($("#teLy").value) ? "· mitlaufend (LRC)" : ""; };
    $("#teLyFind").onclick = e => safe(e.currentTarget, async () => {
      const r = await call("lyrics_fetch", $('[data-f="artist"]', box).value.trim(), $('[data-f="title"]', box).value.trim(), $('[data-f="album"]', box).value.trim(), first.duration);
      if (!r || !(r.synced || r.plain)) return $("#teLyFound").textContent = r && r.instrumental ? "Instrumental – kein Text." : "Kein Songtext gefunden.";
      $("#teLy").value = r.synced || r.plain; lyricsDirty = true;
      $("#teLyInfo").textContent = r.synced ? "· mitlaufend (LRC)" : "";
      $("#teLyFound").innerHTML = `<b style="color:var(--ok)">✓ Gefunden</b> ${r.synced ? "mit Zeitmarken" : "(ohne Zeitmarken)"}`;
    });
  }
  async function saveTags(btn) {
    const f = {};
    $$("[data-f]", box).forEach(i => { if (multi ? dirty.has(i.dataset.f) : i.value !== (first[i.dataset.f] || "")) f[i.dataset.f] = i.value.trim(); });
    const ly = !multi && lyricsDirty ? $("#teLy").value : null;
    if (!Object.keys(f).length && cover.mode === "keep" && ly === null) return closeDialog();
    await safe(btn, async () => {
      const r = await call("tags_save", paths, f, cover, ly, $("#teRename").checked);
      closeDialog();
      toast(r.errors.length ? `${r.paths.length} gespeichert · ${r.errors.length} Fehler: ${r.errors[0]}` : `${r.paths.length} Titel gespeichert`, r.errors.length ? "err" : "ok");
      if ($("#page-library").classList.contains("active")) { L.sel.clear(); loadLibrary(); }
    });
  }
}
function tagsIsLrc(t) { return (String(t || "").match(/\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]/g) || []).length >= 3; }

/* ---------------------------------------------------------------- Titel erkennen */
async function identifyFiles(sel) {
  const st = await call("identify_status");
  if (!st.key) {
    dialog({ title: "Musikerkennung einrichten", icon: "i-finger",
      body: `<p>Die Erkennung per Audio-Fingerabdruck nutzt den kostenlosen Dienst <b>AcoustID</b>. Dafür brauchst du einmalig einen eigenen Schlüssel:</p>
      <ol class="steps"><li>„Schlüssel holen“ öffnet acoustid.org – dort mit Google/GitHub o. ä. anmelden.</li><li><em>Register an application</em> → Name „SongGrabber“, Version „1“ → speichern.</li><li>Den angezeigten <b>API key</b> kopieren und hier einfügen:</li></ol>
      <input id="akKey" placeholder="API key einfügen" style="margin-top:10px">`,
      buttons: [{ label: "Schlüssel holen", fn: () => call("open_url", "https://acoustid.org/new-application") }, { label: "Speichern & erkennen", cls: "primary", fn: async () => { const k = $("#akKey").value.trim(); if (!k) return; await save({ acoustid_key: k }); closeDialog(); identifyFiles(sel); } }] });
    return;
  }
  await call("identify_files", sel);
  toast(`${sel.length} Titel werden erkannt – siehe Warteschlange`, "ok");
}
$("#btnAcoustKey").onclick = () => call("open_url", "https://acoustid.org/new-application");

/* ---------------------------------------------------------------- Kürzen */
async function openTrim(path) {
  $("#audio").pause();
  const box = dialog({ title: "Anfang & Ende kürzen", icon: "i-cut", wide: true,
    body: `<div class="tr-wave" id="trWave"><canvas id="trCv"></canvas><div class="tr-shade" id="trShL"></div><div class="tr-shade" id="trShR"></div><div class="tr-play" id="trPh"></div><div class="tr-handle" id="trHA" title="Anfang ziehen"></div><div class="tr-handle" id="trHB" title="Ende ziehen"></div></div>
      <div class="tr-times"><div class="t"><button class="ghost sm" id="trPA"><svg><use href="#i-play"/></svg>Anfang anhören</button><span class="muted">Start</span><b id="trA">–</b></div><div class="mid" id="trLen">Analysiere …</div><div class="t"><span class="muted">Ende</span><b id="trB">–</b><button class="ghost sm" id="trPB"><svg><use href="#i-play"/></svg>Ende anhören</button></div></div>
      <div class="tr-why" id="trWhy"><span class="spinner" style="display:inline-block;vertical-align:middle;margin-right:8px"></span>Suche Stille, Rauschen, Applaus und Ausblendungen …</div>
      <div class="tr-opts"><label class="switch"><input type="checkbox" id="trFade"><i></i><span>Sanft ein- und ausblenden</span><small>kodiert neu (minimal), sonst verlustfreier Schnitt</small></label><label class="switch"><input type="checkbox" id="trKeep"><i></i><span>Original zusätzlich behalten</span></label></div>`,
    buttons: [{ label: "Vorschlag", id: "trSug" }, { label: "Nichts kürzen", id: "trAll" }, { label: "Kürzen", cls: "primary", id: "trGo", fn: apply }],
    onClose: () => { au.pause(); au.removeAttribute("src"); cancelAnimationFrame(raf); } });
  const au = new Audio();
  let r = null, A = 0, B = 0, raf = 0, stopAt = null;
  const wave = $("#trWave", box), cv = $("#trCv", box);
  try { r = await call("trim_analyze", path); } catch (e) { $("#trWhy").className = "tr-why warn"; $("#trWhy").textContent = String(e.message || e); return; }
  au.src = r.src; A = r.start; B = r.end;
  $("#trWhy").className = "tr-why" + (r.why.startsWith("Vorschlag") ? "" : " warn");
  $("#trWhy").textContent = r.why + (r.why.startsWith("Vorschlag") ? " – bitte anhören, bevor du kürzt." : "");
  const fmtP = s => { const m = Math.floor(s / 60), x = s - m * 60; return `${m}:${x.toFixed(1).padStart(4, "0")}`; };
  function draw() {
    const d = fitCanvas(cv), x = cv.getContext("2d"), W = cv.width, H = cv.height, n = r.peaks.length, bw = W / n;
    x.clearRect(0, 0, W, H);
    const g = x.createLinearGradient(0, 0, 0, H); g.addColorStop(0, "#FFB547"); g.addColorStop(.5, "#FF7A30"); g.addColorStop(1, "#FFB547");
    x.fillStyle = g;
    r.peaks.forEach((p, i) => { const h = Math.max(d, p * H * .45); x.fillRect(i * bw, H / 2 - h, Math.max(1, bw - .5), h * 2); });
  }
  function layout() {
    const pa = A / r.duration * 100, pb = B / r.duration * 100;
    $("#trHA").style.left = pa + "%"; $("#trHB").style.left = pb + "%";
    $("#trShL").style.cssText = `left:0;width:${pa}%`; $("#trShR").style.cssText = `left:${pb}%;right:0`;
    $("#trA").textContent = fmtP(A); $("#trB").textContent = fmtP(B);
    const cut = A + (r.duration - B);
    $("#trLen").innerHTML = `Neue Länge <b>${fmtTime(B - A)}</b> · ${cut > .05 ? `${cut.toFixed(1)} s weg` : "unverändert"}`;
    $("#trGo").disabled = cut < .05;
  }
  draw(); layout();
  new ResizeObserver(draw).observe(wave);
  const tAt = ev => { const b = wave.getBoundingClientRect(); return Math.max(0, Math.min(r.duration, (ev.clientX - b.left) / b.width * r.duration)); };
  [["#trHA", v => { A = Math.min(v, B - 1); }], ["#trHB", v => { B = Math.max(v, A + 1); }]].forEach(([id, set]) => {
    $(id, box).onmousedown = e => { e.preventDefault(); e.stopPropagation(); const mv = ev => { set(tAt(ev)); layout(); }; const up = () => { removeEventListener("mousemove", mv); removeEventListener("mouseup", up); }; addEventListener("mousemove", mv); addEventListener("mouseup", up); };
  });
  wave.onmousedown = e => { if (e.target.classList.contains("tr-handle")) return; play(tAt(e), null); };
  function play(from, until) { au.currentTime = from; stopAt = until; au.play(); tick(); }
  function tick() {
    cancelAnimationFrame(raf);
    $("#trPh").style.left = (au.currentTime / r.duration * 100) + "%";
    if (stopAt !== null && au.currentTime >= stopAt) { au.pause(); stopAt = null; }
    if (!au.paused) raf = requestAnimationFrame(tick);
  }
  $("#trPA").onclick = () => play(A, A + 6);
  $("#trPB").onclick = () => play(Math.max(A, B - 6), B);
  $("#trSug").onclick = () => { A = r.start; B = r.end; layout(); };
  $("#trAll").onclick = () => { A = 0; B = r.duration; layout(); };
  async function apply(btn) {
    au.pause();
    await safe(btn, async () => {
      await call("trim_apply", path, A, B, $("#trFade").checked, $("#trKeep").checked);
      closeDialog(); toast(`Gekürzt – neue Länge ${fmtTime(B - A)}`, "ok");
      if ($("#page-library").classList.contains("active")) loadLibrary();
    });
  }
}

/* ---------------------------------------------------------------- Übertragen (USB/Handy) */
async function openExport(name, paths) {
  if (!paths || !paths.length) return toast("Keine Titel zum Übertragen.", "err");
  let target = "";
  const byPath = new Map(L.items.map(i => [i.path, i]));
  const box = dialog({ title: "Auf USB-Stick oder Handy übertragen", icon: "i-usb",
    body: `<h4 class="muted" style="margin:0 0 8px;font-size:12px;letter-spacing:1px;text-transform:uppercase">Ziel</h4><div class="ex-drives" id="exDrives"><div class="muted">Suche Laufwerke …</div></div>
      <div class="ex-grid"><label>Ordnername auf dem Ziel<input id="exName" value="${esc(name)}"></label>
      <label>Format<select id="exMode"><option value="copy">Unverändert kopieren (schnell)</option><option value="car">Autoradio-sicher: MP3 192 kbps, 44,1 kHz</option><option value="mp3_320">MP3 320 kbps</option></select></label></div>
      <label class="switch"><input type="checkbox" id="exNum" checked><i></i><span>Titel durchnummerieren</span><small>001 - Interpret - Titel.mp3 – Autoradios spielen dann in der richtigen Reihenfolge</small></label>
      <div class="ex-sum" id="exSum"></div>`,
    buttons: [{ label: "Abbrechen" }, { label: "Übertragen", cls: "primary", id: "exGo", fn: go_ }] });
  const sum = () => {
    const mode = $("#exMode").value, sec = paths.reduce((a, p) => a + ((byPath.get(p) || {}).duration || 0), 0);
    const bytes = mode === "copy" ? paths.reduce((a, p) => a + ((byPath.get(p) || {}).size || 0), 0) : sec * (mode === "car" ? 24000 : 40000);
    $("#exSum").textContent = `${paths.length} Titel` + (sec ? ` · ${fmtTime(sec)}` : "") + (bytes ? ` · ca. ${bytes > 1e9 ? (bytes / 1e9).toFixed(1).replace(".", ",") + " GB" : Math.round(bytes / 1e6) + " MB"}` : "") + (target ? ` → ${target}` : " · bitte Ziel wählen");
    $("#exGo").disabled = !target;
  };
  $("#exMode").onchange = sum;
  const drives = await call("export_drives").catch(() => []);
  const render = () => {
    $("#exDrives").innerHTML = drives.map((d, i) => `<button class="ex-drive ${target === d.root ? "active" : ""}" data-i="${i}"><svg><use href="#i-usb"/></svg><div><b>${esc(d.label)} (${esc(d.root.slice(0, 2))})</b><small>${(d.free / 1e9).toFixed(1).replace(".", ",")} GB frei · ${esc(d.fs)}</small></div></button>`).join("") +
      `<button class="ex-drive ${target && !drives.some(d => d.root === target) ? "active" : ""}" id="exOther"><svg><use href="#i-folder"/></svg><div><b>Anderer Ordner …</b><small>${target && !drives.some(d => d.root === target) ? esc(target) : "z. B. Handy-Ordner, Netzwerk"}</small></div></button>`;
    $$("#exDrives [data-i]").forEach(b => b.onclick = () => { target = drives[+b.dataset.i].root; render(); sum(); });
    $("#exOther").onclick = async () => { const f = await call("choose_folder"); if (f) { target = f; render(); sum(); } };
  };
  if (drives.length === 1) target = drives[0].root;
  render(); sum();
  async function go_(btn) {
    await safe(btn, async () => {
      await call("export_start", $("#exName").value.trim() || name, paths, target, $("#exMode").value, $("#exNum").checked);
      closeDialog(); toast("Übertragung läuft – siehe Warteschlange", "ok"); go("queue");
    });
  }
}

/* ---------------------------------------------------------------- Abos */
const ago = ts => { if (!ts) return "nie"; const m = Math.round((Date.now() / 1000 - ts) / 60); return m < 1 ? "gerade eben" : m < 60 ? `vor ${m} Min.` : m < 1440 ? `vor ${Math.round(m / 60)} Std.` : Math.round(m / 1440) === 1 ? "vor 1 Tag" : `vor ${Math.round(m / 1440)} Tagen`; };
let aboT = null;
async function loadAbos() {
  clearTimeout(aboT);
  const r = await call("abos_list");
  $("#aboCount").textContent = r.items.length || "";
  $("#aboHours").value = String(r.hours);
  $("#aboAutostart").checked = !!r.autostart;
  $("#aboList").innerHTML = r.items.length ? r.items.map(a => `<div class="abo ${a.enabled ? "" : "off"}" data-id="${a.id}"><div class="ai"><svg><use href="#i-bell"/></svg></div>
    <div style="min-width:0"><b>${esc(a.name)}</b><small>${esc(a.url)}</small><small>${a.checking ? "Prüfe gerade …" : `Geprüft ${ago(a.last_check)}`} · ${a.count || 0} Titel geladen${a.last_new ? ` · zuletzt neu ${ago(a.last_new)}` : ""}${a.skip_live ? " · ohne Live" : ""}</small>${a.error ? `<small class="err">${esc(a.error)}</small>` : ""}</div>
    <div class="acts"><label class="switch inline-sw" title="Aktiv"><input type="checkbox" data-a="en" ${a.enabled ? "checked" : ""}><i></i></label><button class="ghost sm" data-a="chk"><svg><use href="#i-refresh"/></svg>Jetzt prüfen</button><button class="ghost sm" data-a="del" title="Abo entfernen"><svg><use href="#i-trash"/></svg></button></div></div>`).join("")
    : `<div class="empty"><div class="empty-art"><svg><use href="#i-bell"/></svg></div><h3>Noch keine Abos</h3><p>Kanal- oder Playlist-Link oben einfügen. Neue Videos landen dann automatisch als Audio in deiner Bibliothek – z. B. jede neue Folge eines Podcasts oder die neuesten Lieder eines Künstlers.</p></div>`;
  $$("#aboList .abo").forEach(el => {
    const id = el.dataset.id;
    el.querySelector("[data-a=en]").onchange = e => call("abos_update", id, { enabled: e.target.checked }).then(loadAbos);
    el.querySelector("[data-a=chk]").onclick = e => safe(e.currentTarget, async () => { const n = await call("abos_check", id); toast(n ? `${n} neue Titel gefunden` : "Keine neuen Titel", n ? "ok" : ""); loadAbos(); });
    el.querySelector("[data-a=del]").onclick = async () => { if (confirm("Abo entfernen? Bereits geladene Titel bleiben erhalten.")) { await call("abos_remove", id); loadAbos(); } };
  });
  if ($("#page-abos").classList.contains("active")) aboT = setTimeout(loadAbos, 5000);
}
$("#btnAboAdd").onclick = e => safe(e.currentTarget, async () => {
  const url = $("#aboUrl").value.trim();
  if (!/^https?:\/\//i.test(url)) return toast("Bitte einen Kanal- oder Playlist-Link einfügen.");
  const a = await call("abos_add", url, $("#aboName").value, +$("#aboBack").value, $("#aboSkipLive").checked);
  toast(`Abonniert: ${a.name}`, "ok"); $("#aboUrl").value = $("#aboName").value = ""; loadAbos();
});
$("#aboUrl").addEventListener("keydown", e => { if (e.key === "Enter") $("#btnAboAdd").click(); });
$("#btnAboAll").onclick = e => safe(e.currentTarget, async () => { const n = await call("abos_check", null); toast(n ? `${n} neue Titel gefunden` : "Keine neuen Titel", n ? "ok" : ""); loadAbos(); });
$("#aboHours").onchange = e => save({ abo_hours: +e.target.value });
$("#aboAutostart").onchange = e => call("autostart_set", e.target.checked).then(v => toast(v ? "Startet ab jetzt mit dem Computer (minimiert)" : "Autostart aus", "ok"));

/* ---------------------------------------------------------------- Songtext (Mini-Player + Player-Seite) */
const LY = { lines: [], synced: false, path: "", idx: -1, clock: null, ckind: "audio", offset: 0, state: "" };
/* Uhren für den mitlaufenden Songtext: eigene Wiedergabe, Radio (ab Titelwechsel), Alles am PC (Windows-Position) */
const AC = { get: () => $("#audio").currentTime, set(t) { $("#audio").currentTime = t; }, label: () => "läuft mit" };
const RC = {           // Radio: Liedanfang = Zeitpunkt, an dem der Sender den neuen Titel meldet
  key: "", S: null, dur: 0,
  note(m) {
    if (m.duration) this.dur = m.duration;
    if (m.text === this.key) return;
    this.key = m.text; this.S = null; this.dur = m.duration || 0;
    if (!m.first && m.changed) {
      const a = $("#audio"), be = a.buffered.length ? a.buffered.end(a.buffered.length - 1) : a.currentTime;
      this.S = be - Math.max(0, (m.now || 0) - m.changed);
    }
  },
  stale() { return this.S != null && this.dur > 0 && $("#audio").currentTime - this.S > this.dur + 45; },   // Sender hängt mit dem Titel
  get() { return this.S == null || this.stale() ? null : $("#audio").currentTime - this.S; },
  set(t) { if (this.get() == null) { this.S = $("#audio").currentTime - t; LY.offset = 0; } else LY.offset = t - this.get(); },
  label() { return this.stale() ? "Sender meldet noch den alten Titel" : this.S == null ? "Zeile anklicken, die gerade gesungen wird" : "läuft mit (ungefähr)"; },
};
const SC = {           // Alles am PC: Position aus der Windows-Mediensteuerung, sonst ab Titelwechsel geschätzt
  key: "", anchor: null, tl: false, est: false, playing: false, lastRaw: null,
  get() { const A = this.anchor; return A ? A.pos + (A.playing ? (performance.now() - A.at) / 1000 : 0) : null; },
  at(pos, playing) { this.anchor = { pos, at: performance.now(), playing }; },
  note(n) {
    const key = n.active ? `${n.artist}|${n.title}` : "", changed = key !== this.key;
    if (changed) { const fresh = this.key !== "" && key !== ""; this.key = key; this.anchor = null; this.lastRaw = null; this.est = false; if (fresh) { this.est = true; this.at(.8, !!n.playing); } }
    this.tl = n.duration > 0 && n.position != null;
    if (this.tl) {
      const raw = n.pos_now != null ? n.pos_now : n.position, pred = this.get();
      const moved = this.lastRaw == null || Math.abs(n.position - this.lastRaw) > .05;
      if (!this.anchor || this.est || this.anchor.playing !== !!n.playing || (n.pos_live ? Math.abs(raw - pred) > 1.2 : moved)) this.at(raw, !!n.playing);
      this.est = false; this.lastRaw = n.position;
    } else if (this.anchor && this.anchor.playing !== !!n.playing) this.at(this.get(), !!n.playing);
    this.playing = !!n.playing;
    return changed;
  },
  set(t) { const g = this.get(); if (g == null) { this.at(t, this.playing); LY.offset = 0; } else LY.offset = t - g; },
  label() { return this.tl ? "läuft mit" : this.anchor ? "geschätzt – bei Bedarf Zeile anklicken" : "Zeile anklicken, die gerade gesungen wird"; },
};
function lyPos() { const c = LY.clock || AC, v = c.get(); return v == null ? null : v + (c === AC ? 0 : LY.offset); }
function lyState() {
  const c = LY.clock || AC, txt = !LY.lines.length ? "" : LY.synced ? c.label() : "ohne Zeitangaben";
  if (txt !== LY.state) { LY.state = txt; const e = $("#lyState"); e.textContent = txt ? "· " + txt : ""; e.classList.toggle("ok", /läuft mit/.test(txt)); }
  $("#lyAdj").hidden = !(LY.synced && c !== AC && c.get() != null);
}
function parseLrc(t) {
  const out = [];
  String(t || "").split(/\r?\n/).forEach(line => {
    const st = [...line.matchAll(/\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]/g)], txt = line.replace(/\[[^\]]*\]/g, "").trim();
    st.forEach(m => out.push({ t: (+m[1] * 60 + +m[2]) + (m[3] ? +("0." + m[3]) : 0), txt }));
  });
  return out.sort((a, b) => a.t - b.t);
}
const lyBodies = () => [$("#pLyBody"), $("#ppLyBody")];
const lyVisible = () => !$("#pLyrics").hidden || (!$("#ppLyBody").hidden && $("#page-player").classList.contains("active"));
function lyHtml(html, cls) { lyBodies().forEach(b => { b.className = b.id === "ppLyBody" ? "ly-body pp-ly" + (cls || "") : "ly-body" + (cls || ""); b.innerHTML = html; b.scrollTop = 0; }); }
async function loadLyrics(t) {
  if (!t || !lyVisible() || LY.path === t.path) return;
  LY.path = t.path; LY.idx = -1; LY.synced = false; LY.lines = [];
  const ck = t.kind === "radio" ? "radio" : t.kind === "sys" ? "sys" : "audio";
  if (ck !== LY.ckind) { LY.ckind = ck; LY.offset = 0; }
  LY.clock = ck === "radio" ? RC : ck === "sys" ? SC : AC;
  lyState();
  lyHtml(`<div class="empty-ly"><span class="spinner" style="display:inline-block"></span></div>`);
  let text = "";
  if (!t.kind || t.kind === "file") text = await call("lyrics_for", t.path).catch(() => "");
  else if (t.title && t.kind !== "podcast") { const r = await call("lyrics_smart", t.kind === "radio" ? (t.artist || "") : t.artist || "", t.title, t.album || "", t.duration || 0, t.raw || "").catch(() => null); text = r ? (r.synced || r.plain || "") : ""; }
  if (LY.path !== t.path) return;
  if (!text && t.kind && t.kind !== "file") {
    const msg = t.kind === "podcast" ? "Für Podcasts gibt es keinen Songtext."
      : t.kind === "radio" && !t.title ? "Sobald der Sender den Titel meldet, erscheint hier der Songtext (wenn vorhanden)."
      : t.kind === "sys" && !t.title ? "Spiel etwas ab – der Songtext erscheint hier automatisch.<br><small>Spotify, YouTube im Browser, Apple Music …</small>"
      : `Für „${esc(t.raw || [t.artist, t.title].filter(Boolean).join(" – "))}“ wurde kein Songtext gefunden.<br><small>Nicht jedes Lied ist bei lrclib.net eingetragen – bei Wortbeiträgen, Werbung oder Nachrichten gibt es keinen.</small>`;
    lyHtml(`<div class="empty-ly">${msg}</div>`); $("#pLySrc").textContent = ""; lyState(); return;
  }
  if (!text) {
    lyHtml(`<div class="empty-ly">Kein Songtext gespeichert.<br><br><button class="ghost sm lyFind"><svg><use href="#i-search"/></svg>Online suchen &amp; einbetten</button></div>`);
    $$(".lyFind").forEach(btn => btn.onclick = e => safe(e.currentTarget, async () => {
      const r = await call("lyrics_fetch", t.artist || "", t.title || "", t.album || "", t.duration || 0);
      if (!r || !(r.synced || r.plain)) return toast(r && r.instrumental ? "Instrumental – kein Songtext." : "Kein Songtext gefunden.");
      await call("tags_save", [t.path], {}, { mode: "keep" }, r.synced || r.plain, false);
      LY.path = ""; loadLyrics(t);
    }));
    $("#pLySrc").textContent = "";
    return;
  }
  const lrc = parseLrc(text);
  LY.synced = lrc.length >= 3;
  LY.lines = LY.synced ? lrc : text.split(/\r?\n/).map(txt => ({ t: 0, txt }));
  lyHtml(LY.lines.map(l => `<p>${esc(l.txt) || "&nbsp;"}</p>`).join(""), LY.synced ? " synced" : "");
  $("#pLySrc").textContent = LY.synced ? "läuft mit" : "";
  LY.state = ""; lyState(); lySync(true);
}
$("#pLyricsBtn").onclick = e => {
  e.stopPropagation();
  const p = $("#pLyrics"); p.hidden = !p.hidden; $("#pLyricsBtn").classList.toggle("on", !p.hidden);
  $("#pQueue").hidden = true;
  if (!p.hidden) { if (SysMode.on()) SysMode.lyrics(true); else { LY.path = ""; loadLyrics(Player.lyricsTrack()); } }
};
window.addEventListener("ag-track", e => { if (SysMode.on()) return; LY.path = ""; loadLyrics(e.detail); });
function lySync(force) {
  if (!LY.synced || !lyVisible()) return;
  lyState();
  const pos = lyPos();
  lyBodies().forEach(b => b.classList.toggle("noclock", pos == null));
  let i = -1;
  if (pos != null) { i = LY.lines.findIndex(l => l.t > pos + 0.25) - 1; if (i === -2) i = LY.lines.length - 1; }
  if (i === LY.idx && !force) return;
  LY.idx = i;
  lyBodies().forEach(b => {
    const ps = $$("p", b);
    ps.forEach((p, j) => { p.classList.toggle("cur", j === i); p.classList.toggle("done", j < i); });
    if (ps[i]) b.scrollTop = ps[i].offsetTop - b.clientHeight / 2 + ps[i].offsetHeight / 2;
  });
}
setInterval(lySync, 200);
lyBodies().forEach(b => b.addEventListener("click", e => {
  if (!LY.synced) return; const ps = $$("p", b), j = ps.indexOf(e.target.closest("p")); if (j < 0) return;
  const c = LY.clock || AC; c.set(LY.lines[j].t + (c === AC ? 0 : .3));
  if (c !== AC) toast("Songtext angepasst – läuft ab hier mit", "ok");
  lySync(true);
}));
$("#lyEarlier").onclick = () => { LY.offset += .5; lySync(true); };
$("#lyLater").onclick = () => { LY.offset -= .5; lySync(true); };
document.addEventListener("click", e => { if (!e.target.closest("#player") && !$("#pLyrics").hidden) { $("#pLyrics").hidden = true; $("#pLyricsBtn").classList.remove("on"); } });

/* ---------------------------------------------------------------- Alles am PC (Spotify & Co.) */
const SysMode = (() => {
  let on = false, url = "", vizT = 0, infoT = 0, last = {}, track = null;
  function lyrics(force) {
    const n = last || {};
    if (!force && track && track.path === "sys:" + SC.key) return;
    track = { kind: "sys", path: "sys:" + SC.key, artist: n.artist || "", title: n.active ? n.title || "" : "", album: n.album || "", duration: n.duration || 0 };
    LY.path = ""; loadLyrics(track);
  }
  async function frame() {
    if (!on || !Viz.fx() || !$("#page-player").classList.contains("active")) { vizT = 0; Viz.external(null); return; }
    try { const r = await fetch(url, { cache: "no-store" }); Viz.external(await r.json()); } catch (e) { Viz.external(null); }
    vizT = setTimeout(frame, 33);
  }
  async function info() {
    if (!on) return;
    try {
      const n = await call("now_playing"); last = n;
      if (SC.note(n) || !track) lyrics(true);
      if (n.unavailable) {
        $("#sysApp").textContent = "Alles am PC"; $("#sysTitle").textContent = "Lichtshow für alles, was läuft";
        $("#sysArtist").textContent = "Titel-Anzeige ist auf diesem PC nicht verfügbar – Steuerung über Medientasten";
      } else if (!n.active) {
        $("#sysApp").textContent = "Alles am PC"; $("#sysTitle").textContent = "Spiel etwas ab …";
        $("#sysArtist").textContent = "Spotify, YouTube im Browser, Spiele – die Lichtshow tanzt mit"; $("#sysAlbum").textContent = "";
      } else {
        $("#sysApp").textContent = n.app || "App"; $("#sysTitle").textContent = n.title || "–";
        $("#sysArtist").textContent = n.artist || ""; $("#sysAlbum").textContent = n.album || "";
      }
      const img = $("#sysCoverImg");
      if (n.art && img.dataset.src !== n.art) {
        img.dataset.src = n.art; const i = new Image(); i.crossOrigin = "anonymous";
        i.onload = () => { img.style.backgroundImage = `url("${n.art}")`; img.classList.remove("none"); Viz.setCover(i); };
        i.src = n.art;
      } else if (!n.art && img.dataset.src) { img.dataset.src = ""; img.style.backgroundImage = ""; img.classList.add("none"); Viz.setCover(null); }
      $("#sysPlay use").setAttribute("href", n.playing ? "#i-pause" : "#i-play");
      if (n.viz_error) $("#sysHint").textContent = "Systemsound nicht erreichbar: " + n.viz_error;
    } catch (e) { }
    infoT = setTimeout(info, 1500);
  }
  async function set(v) {
    on = v;
    $$("#ppSource button").forEach(b => b.classList.toggle("active", (b.dataset.s === "system") === v));
    $("#ppSys").hidden = !v; const side = $(".pp-side"); side.classList.toggle("sys", v);
    if (v) { $("#ppLyBody").hidden = $("#lyHead").hidden = false; track = null; SC.key = ""; SC.anchor = null; }
    else { track = null; $(".pp-tabs button.active").click(); }
    if (v) {
      $("#ppEmpty").hidden = true; $("#ppNow").hidden = true;
      if (Player.current() && !$("#audio").paused) { Player.pause(); toast("SongGrabber pausiert – die Lichtshow folgt jetzt dem Ton vom PC"); }
      url = url || await call("sys_viz_url");
      clearTimeout(vizT); clearTimeout(infoT); frame(); info();
    } else {
      clearTimeout(vizT); clearTimeout(infoT); Viz.external(null); Player.refresh();
      const c = Player.current(); if (c && c.art) { const i = new Image(); i.crossOrigin = "anonymous"; i.onload = () => Viz.setCover(i); i.src = c.art; } else Viz.setCover(null);
    }
    Viz.start();
  }
  const ctl = async cmd => { await call("media_control", cmd); setTimeout(() => { clearTimeout(infoT); info(); }, 350); };
  $("#sysPlay").onclick = () => ctl("toggle"); $("#sysNext").onclick = () => ctl("next"); $("#sysPrev").onclick = () => ctl("prev");
  $$("#ppSource button").forEach(b => b.onclick = () => set(b.dataset.s === "system"));
  return { on: () => on, resume() { if (on) { clearTimeout(vizT); frame(); } }, set, lyrics };
})();

/* ---------------------------------------------------------------- Online abspielen (YouTube & Co.) */
function linkEntries() {
  const L = S.link; if (!L) return [];
  if (L.type === "playlist") return $$("#plList input:checked").map(c => L.entries[+c.dataset.i]).map(e => ({ kind: "stream", url: e.url, title: e.title, artist: e.uploader || L.uploader || "", duration: e.duration, thumb: e.thumb || "" }));
  if (L.type === "stream" || L.is_live) return [{ kind: "radio", url: L.url, name: L.title || "Livestream", tags: [L.uploader || "Live"].filter(Boolean), favicon: L.thumb || "" }];
  return [{ kind: "stream", url: L.url, title: $("#resTrack").value.trim() || L.track || L.title, artist: $("#resArtist").value.trim() || L.artist || "", album: $("#resAlbum").value.trim(), duration: L.duration, thumb: L.cover_url || L.thumb || "" }];
}
$("#btnStreamPlay").onclick = e => safe(e.currentTarget, async () => {
  const en = linkEntries(); if (!en.length) return toast("Nichts ausgewählt.");
  await Player.playEntries(en); toast(en.length > 1 ? `${en.length} Titel werden abgespielt` : "Wird abgespielt – ohne Download", "ok");
});
async function openOnlineSearch(q0) {
  const box = dialog({ title: "Online suchen (YouTube)", icon: "i-search", wide: true,
    body: `<div class="rp-bar"><div class="search grow"><svg><use href="#i-search"/></svg><input id="osQ" placeholder="Interpret, Titel oder Album …" value="${esc(q0 || "")}"></div><button class="primary" id="osGo">Suchen</button></div><div class="search-res" id="osRes"><div class="muted">Suchbegriff eingeben und Enter drücken.</div></div>`,
    buttons: [{ label: "Schließen" }] });
  const run = () => safe($("#osGo"), async () => {
    const q = $("#osQ").value.trim(); if (!q) return;
    $("#osRes").innerHTML = `<div class="live-wait"><i class="spinner"></i>Suche …</div>`;
    const r = await call("online_search", q);
    const en = r.map(x => ({ kind: "stream", url: x.url, title: x.track || x.title, artist: x.artist, duration: x.duration, thumb: x.thumb }));
    $("#osRes").innerHTML = r.length ? r.map((x, i) => `<div class="sr"><div class="ct" style="background-image:url('${esc(x.thumb)}')"></div><div><b>${esc(x.title)}</b><small>${esc(x.uploader)}${x.duration ? " · " + fmtTime(x.duration) : ""}${x.live ? " · Live-Auftritt" : ""}</small></div><div class="acts"><button class="primary sm" data-p="${i}" title="Jetzt abspielen"><svg><use href="#i-play"/></svg></button><button class="ghost sm" data-n="${i}" title="Als Nächstes">+1</button><button class="ghost sm" data-a="${i}" title="Anhängen"><svg><use href="#i-plus"/></svg></button><button class="ghost sm" data-d="${i}" title="Herunterladen"><svg><use href="#i-down"/></svg></button></div></div>`).join("") : `<div class="muted">Nichts gefunden.</div>`;
    $$("#osRes [data-p]").forEach(b => b.onclick = () => Player.playEntries([en[+b.dataset.p]]));
    $$("#osRes [data-n]").forEach(b => b.onclick = () => Player.addEntries([en[+b.dataset.n]], { nextUp: true }));
    $$("#osRes [data-a]").forEach(b => b.onclick = () => Player.addEntries([en[+b.dataset.a]]));
    $$("#osRes [data-d]").forEach(b => b.onclick = async () => { await call("link_download", [{ url: r[+b.dataset.d].url, title: r[+b.dataset.d].title }], {}); toast("Download gestartet – siehe Warteschlange", "ok"); });
  });
  $("#osGo").onclick = run; $("#osQ").addEventListener("keydown", e => { if (e.key === "Enter") run(); });
  setTimeout(() => $("#osQ").focus(), 50); if (q0) run();
}
async function openLinkDialog() {
  dialog({ title: "Link abspielen", icon: "i-link", body: `<label>YouTube-, SoundCloud-, Bandcamp-Link …<input id="olU" placeholder="https://…"></label>`,
    buttons: [{ label: "Abbrechen" }, { label: "Abspielen", cls: "primary", fn: async btn => { await safe(btn, async () => {
      const u = $("#olU").value.trim(); if (!/^https?:\/\//i.test(u)) return toast("Bitte einen Link einfügen.");
      const info = await call("link_analyze", u); closeDialog();
      const en = info.type === "playlist" ? info.entries.map(e => ({ kind: "stream", url: e.url, title: e.title, artist: e.uploader || info.uploader, duration: e.duration })) : info.is_live || info.type === "stream" ? [{ kind: "radio", url: info.url, name: info.title, tags: ["Live"] }] : [{ kind: "stream", url: info.url, title: info.track || info.title, artist: info.artist, album: info.album, duration: info.duration, thumb: info.cover_url || info.thumb }];
      Player.addEntries(en);
    }); } }] });
  setTimeout(() => $("#olU").focus(), 50);
}

/* ---------------------------------------------------------------- Radio */
const R = { list: [], favs: [], recent: [], tag: "", loaded: false };
const stEntry = s => ({ kind: "radio", uuid: s.uuid, name: s.name, url: s.url, favicon: s.favicon, tags: s.tags });
function stCard(s, list, i) {
  const fav = R.favs.some(f => f.uuid === s.uuid), cur = Player.current(), on = cur && cur.kind === "radio" && cur.uuid === s.uuid;
  return `<div class="st ${on ? "on" : ""}" data-l="${list}" data-i="${i}"><span class="fav" ${s.favicon ? `style="background-image:url('${esc(s.favicon)}')"` : ""}>${s.favicon ? "" : '<svg><use href="#i-radio"/></svg>'}</span><span style="min-width:0"><b title="${esc(s.name)}">${esc(s.name)}</b><small>${esc([(s.tags || []).slice(0, 3).join(", "), s.bitrate ? s.bitrate + " kbit/s" : "", s.country].filter(Boolean).join(" · "))}</small></span><span class="acts"><button class="star ${fav ? "on" : ""}" title="${fav ? "Aus Favoriten entfernen" : "Zu Favoriten"}"><svg><use href="#i-star"/></svg></button><button class="more" title="Mehr"><svg><use href="#i-list"/></svg></button></span></div>`;
}
function renderRadio() {
  $("#radioFavWrap").hidden = !R.favs.length; $("#radioRecentWrap").hidden = !R.recent.length;
  $("#radioFavs").innerHTML = R.favs.map((s, i) => stCard(s, "favs", i)).join("");
  $("#radioRecent").innerHTML = R.recent.slice(0, 6).map((s, i) => stCard(s, "recent", i)).join("");
  $("#radioList").innerHTML = R.list.length ? R.list.map((s, i) => stCard(s, "list", i)).join("") : `<div class="muted">Keine Sender gefunden.</div>`;
  $$("#rpRadio .st").forEach(el => {
    const arr = R[el.dataset.l], s = arr[+el.dataset.i];
    el.onclick = e => {
      if (e.target.closest(".star")) { call("radio_toggle_fav", s).then(on => { toast(on ? `„${s.name}“ in den Favoriten` : "Aus Favoriten entfernt", "ok"); loadRadioSide(); }); return; }
      if (e.target.closest(".more")) { e.stopPropagation(); return stMenu(e, s); }
      Player.playEntries(arr.map(stEntry), +el.dataset.i);
      setTimeout(renderRadio, 400);
    };
    el.oncontextmenu = e => { e.preventDefault(); stMenu(e, s); };
  });
}
function stMenu(e, s) {
  ctxMenu(e, [
    { icon: "i-play", label: "Abspielen", fn: () => Player.playEntries([stEntry(s)]) },
    { icon: "i-list", label: "An Wiedergabeliste anhängen", fn: () => Player.addEntries([stEntry(s)]) },
    { icon: "i-mic", label: "Mitschneiden …", fn: () => recordRadio({ url: s.url, station: s.name }) },
    { icon: "i-star", label: R.favs.some(f => f.uuid === s.uuid) ? "Aus Favoriten entfernen" : "Zu Favoriten", fn: () => call("radio_toggle_fav", s).then(loadRadioSide) },
    "-",
    s.homepage && { icon: "i-globe", label: "Webseite des Senders", fn: () => call("open_url", s.homepage) },
    { icon: "i-copy", label: "Stream-Adresse kopieren", fn: () => copyText(s.url) },
  ]);
}
function recordRadio(t) {
  dialog({ title: "Sender mitschneiden", icon: "i-mic", body: `<p class="muted" style="margin-top:0">„${esc(t.station || t.name)}“ wird im Hintergrund aufgenommen und danach im eingestellten Format gespeichert – auch wenn du weiterhörst oder den Sender wechselst.</p><label>Dauer in Minuten (0 = bis du stoppst)<input id="rrMin" type="number" min="0" value="60"></label>`,
    buttons: [{ label: "Abbrechen" }, { label: "Aufnahme starten", cls: "primary", fn: async btn => { await safe(btn, async () => { await call("radio_record", { url: t.url, name: t.station || t.name }, +$("#rrMin").value || 0); closeDialog(); toast("Mitschnitt läuft – beenden unter Links & Streams", "ok"); }); } }] });
}
$("#ppRecRadio").onclick = () => { const t = Player.current(); if (t && t.kind === "radio") recordRadio(t); };
async function loadRadioSide() { try { const r = await call("radio_favorites"); R.favs = r.favorites; R.recent = r.recent; } catch (e) { } renderRadio(); }
async function radioSearch() {
  const q = $("#radioQ").value.trim(), c = $("#radioCountry").value;
  $("#radioResHead").innerHTML = `<svg><use href="#i-globe"/></svg>${q ? `Ergebnisse für „${esc(q)}“` : R.tag ? `Genre: ${esc(R.tag)}` : "Beliebt"}`;
  $("#radioList").innerHTML = `<div class="live-wait"><i class="spinner"></i>Lade Sender …</div>`;
  try { R.list = await call("radio_search", q, R.tag, c); } catch (e) { R.list = []; $("#radioList").innerHTML = `<div class="muted">${esc(String(e.message || e))}</div>`; return; }
  renderRadio();
}
async function loadRadio() {
  if (R.loaded) return renderRadio();
  R.loaded = true; await loadRadioSide(); radioSearch();
  try { const t = await call("radio_tags"); $("#radioTags").innerHTML = t.slice(0, 24).map(x => `<span data-t="${esc(x)}">${esc(x)}</span>`).join(""); $$("#radioTags span").forEach(s => s.onclick = () => { R.tag = R.tag === s.dataset.t ? "" : s.dataset.t; $$("#radioTags span").forEach(x => x.classList.toggle("on", x.dataset.t === R.tag)); radioSearch(); }); } catch (e) { }
}
$("#radioQ").addEventListener("keydown", e => { if (e.key === "Enter") radioSearch(); });
$("#radioQ").addEventListener("input", () => { clearTimeout(R.t); R.t = setTimeout(radioSearch, 500); });
$("#radioCountry").onchange = radioSearch;
$$("#rpTabs button").forEach(b => b.onclick = () => { $$("#rpTabs button").forEach(x => x.classList.toggle("active", x === b)); $("#rpRadio").hidden = b.dataset.t !== "radio"; $("#rpPod").hidden = b.dataset.t !== "podcasts"; if (b.dataset.t === "podcasts") loadPodcasts(); });

/* ---------------------------------------------------------------- Podcasts */
const P = { subs: [], show: null };
const podCard = (p, i, src) => `<button class="pod" data-src="${src}" data-i="${i}"><span class="img" style="background-image:url('${esc(p.image || "")}')"></span><b>${esc(p.title)}</b><small>${esc(p.author || p.genre || "")}</small></button>`;
async function loadPodcasts() {
  P.subs = await call("podcast_subs").catch(() => []);
  PodProg = await call("podcast_progress").catch(() => ({}));
  $("#podSubs").innerHTML = P.subs.length ? P.subs.map((p, i) => podCard(p, i, "subs")).join("") : `<div class="muted" style="grid-column:1/-1">Noch keine Podcasts abonniert – oben suchen und „Abonnieren“.</div>`;
  $$("#podSubs .pod").forEach(b => b.onclick = () => openShow(P.subs[+b.dataset.i].feed));
}
async function podSearch() {
  const q = $("#podQ").value.trim(); if (!q) { $("#podSearchWrap").hidden = true; return; }
  $("#podSearchWrap").hidden = false; $("#podResults").innerHTML = `<div class="live-wait"><i class="spinner"></i>Suche …</div>`;
  try {
    P.res = await call("podcast_search", q);
    $("#podResults").innerHTML = P.res.length ? P.res.map((p, i) => podCard(p, i, "res")).join("") : `<div class="muted">Nichts gefunden.</div>`;
    $$("#podResults .pod").forEach(b => b.onclick = () => openShow(P.res[+b.dataset.i].feed));
  } catch (e) { $("#podResults").innerHTML = `<div class="muted">${esc(String(e.message || e))}</div>`; }
}
$("#podQ").addEventListener("keydown", e => { if (e.key === "Enter") podSearch(); });
$("#btnPodFeed").onclick = () => dialog({ title: "Podcast-Feed hinzufügen", icon: "i-podcast", body: `<label>RSS-Adresse des Podcasts<input id="pfU" placeholder="https://…/feed.xml"></label>`,
  buttons: [{ label: "Abbrechen" }, { label: "Öffnen", cls: "primary", fn: async btn => { await safe(btn, async () => { const u = $("#pfU").value.trim(); if (!u) return; closeDialog(); await openShow(u); }); } }] });
const epEntry = (sh, e) => ({ kind: "podcast", url: e.url, guid: e.guid, title: e.title, show: sh.title, image: e.image || sh.image, duration: e.duration, feed: sh.feed });
async function openShow(feed) {
  const box = $("#podShow"); box.hidden = false;
  box.innerHTML = `<div class="live-wait" style="padding:20px"><i class="spinner"></i>Lade Folgen …</div>`; box.scrollIntoView({ behavior: "smooth", block: "start" });
  let sh;
  try { sh = await call("podcast_open", feed, true); } catch (e) { box.innerHTML = `<div class="muted" style="padding:20px">${esc(String(e.message || e))}</div>`; return; }
  P.show = sh; PodProg = await call("podcast_progress").catch(() => PodProg);
  const subbed = P.subs.some(s => s.feed === sh.feed), date = t => t ? new Date(t * 1000).toLocaleDateString("de-DE") : "";
  box.innerHTML = `<div class="ps-head"><span class="img" style="background-image:url('${esc(sh.image)}')"></span><div><h2>${esc(sh.title)}</h2><small class="muted">${esc(sh.author)} · ${sh.episodes.length} Folgen</small><p>${esc(sh.description)}</p></div><div class="acts"><button class="${subbed ? "ghost" : "primary"}" id="psSub">${subbed ? "Abonniert ✓" : "Abonnieren"}</button><button class="ghost" id="psNew" title="Neueste Folge"><svg><use href="#i-play"/></svg>Neueste</button><button class="ghost icon" id="psClose" title="Schließen"><svg><use href="#i-x"/></svg></button></div></div>` +
    sh.episodes.slice(0, 120).map((e, i) => { const pr = PodProg[e.guid] || {}; const pct = pr.dur ? Math.min(100, pr.pos / pr.dur * 100) : 0;
      return `<div class="ep ${pr.done ? "done" : ""}" data-i="${i}"><button class="pbtn" title="${pr.pos > 15 && !pr.done ? "Fortsetzen" : "Abspielen"}"><svg><use href="#i-play"/></svg></button><div style="min-width:0"><b>${esc(e.title)}</b><small>${esc(date(e.date))}${e.duration ? " · " + fmtTime(e.duration) : ""}${pr.done ? " · gehört ✓" : pr.pos > 15 ? ` · noch ${fmtTime((pr.dur || e.duration) - pr.pos)}` : ""}</small><p>${esc(e.description)}</p>${pct && !pr.done ? `<div class="prog"><i style="width:${pct}%"></i></div>` : ""}</div><div class="acts"><button class="ghost sm" data-a="add" title="An Wiedergabeliste"><svg><use href="#i-plus"/></svg></button><button class="ghost sm" data-a="dl" title="Herunterladen"><svg><use href="#i-down"/></svg></button></div></div>`; }).join("");
  $("#psClose").onclick = () => { box.hidden = true; };
  $("#psSub").onclick = async () => { if (subbed) await call("podcast_unsubscribe", sh.feed); else await call("podcast_subscribe", sh); toast(subbed ? "Abo beendet" : `„${sh.title}“ abonniert`, "ok"); await loadPodcasts(); openShow(sh.feed); };
  $("#psNew").onclick = () => sh.episodes[0] && Player.playEntries([epEntry(sh, sh.episodes[0])]);
  $$("#podShow .ep").forEach(r => {
    const e = sh.episodes[+r.dataset.i];
    r.querySelector(".pbtn").onclick = () => Player.playEntries([epEntry(sh, e)]);
    r.querySelector("[data-a=add]").onclick = () => Player.addEntries([epEntry(sh, e)]);
    r.querySelector("[data-a=dl]").onclick = async () => { await call("podcast_download", sh, e); toast("Folge wird heruntergeladen – siehe Warteschlange", "ok"); };
  });
}

/* ---------------------------------------------------------------- Start */
async function boot() {
  if (booted) return; booted = true;
  const i = await refreshTools();
  S.presets = i.presets; S.settings = i.settings;
  Player.setVolume(S.settings.volume ?? .8);
  $("#xfSel").value = String(S.settings.xfade ?? 4); $("#normPlay").checked = S.settings.norm_play !== false;
  Colors.load(S.settings); SideBar.load(S.settings); Viz.setMode(S.settings.viz_mode === "tesla" ? "aurora" : (S.settings.viz_mode || "synth")); Viz.setTheme(THEMES[S.settings.viz_theme] ? S.settings.viz_theme : "synth"); Viz.setFx(S.settings.viz_fx !== false); InfoMin.set(S.settings.pp_info_min !== false); EQ.load(S.settings);
  Player.refresh(); Player.restore();
  fillPresets(presetFmt(S.settings.preset), S.settings.preset);
  $("#aboutVer").textContent = "Version " + i.version;
  renderSettings(); poll();
  $("#urlInput").focus();
  const seen = S.settings.seen_version;
  if (!S.settings.welcome_done) $("#welcome").hidden = false;
  else if (!seen || verCmp(i.version, seen) > 0) setTimeout(() => showWhatsNew(seen || (CHANGES[1] || ["0"])[0]), 400);
  else setTimeout(checkClipboard, 800);
  if (seen !== i.version) save({ seen_version: i.version });
}
window.addEventListener("pywebviewready", boot);
setTimeout(() => { if (!booted && !(window.pywebview && window.pywebview.api)) boot(); }, 700);

/* ---------------------------------------------------------------- Demo-Modus (im Browser ohne Python) */
const Mock = (() => {
  const P = [["mp3_v0", "MP3", "VBR V0 · ≈245 kbps (empfohlen)", "mp3"], ["mp3_320", "MP3", "CBR 320 kbps · maximal", "mp3"], ["mp3_192", "MP3", "CBR 192 kbps", "mp3"], ["wav_16_44", "WAV", "16 Bit · 44,1 kHz (CD-Qualität)", "wav"], ["wav_24_48", "WAV", "24 Bit · 48 kHz (Studio)", "wav"], ["flac_16", "FLAC", "16 Bit · verlustfrei", "flac"]].map(([id, fmt, label, ext]) => ({ id, fmt, label, ext }));
  let settings = { output_dir: "C:\\Users\\Pezhy\\Music\\SongGrabber", preset: "mp3_v0", normalize: "off", name_single: "{albumartist}/{album}/{track:02} - {title}", name_album: "{albumartist}/{album}/{track:02} - {title}", embed_cover: true, square_cover: true, playlist_m3u: true, musicbrainz: true, cd_verify: true, metadata_online: true, prefer_album_cover: true, skip_existing: true, auto_playlist_links: true, clipboard_watch: true, watch_enabled: true, watch_dir: "C:\\Users\\Pezhy\\Music\\SongGrabber\\_Übergabe", tools_dir: "" };
  const jobs = [
    { id: 3, kind: "cd", title: "Nena", subtitle: "Nena · 10 Titel", status: "läuft", progress: .46, stage: "Lese Titel 5 von CD …", outputs: [], count: 4, error: "" },
    { id: 2, kind: "link", title: "Daft Punk – Get Lucky", subtitle: "Daft Punk", status: "wartet", progress: 0, stage: "In der Warteschlange", outputs: [], count: 0, error: "" },
    { id: 1, kind: "rec", title: "Pink Floyd – The Wall (Seite A)", subtitle: "21:48 min aufgenommen", status: "fertig", progress: 1, stage: "Fertig · 6 Titel", outputs: ["x"], count: 6, error: "" },
  ];
  let t0 = 0, rec = "idle", w = [], scr = { state: "idle" };
  const LIB = [["Rolling in the Deep", "Adele", "21", "Pop", "2011", 228], ["Someone Like You", "Adele", "21", "Pop", "2011", 285], ["Skyfall", "Adele", "Skyfall", "Pop", "2012", 286], ["99 Luftballons", "Nena", "Nena", "Pop", "1983", 232], ["Major Tom", "Peter Schilling", "Fehler im System", "Pop", "1983", 300], ["Bohemian Rhapsody", "Queen", "A Night at the Opera", "Rock", "1975", 355], ["Get Lucky", "Daft Punk", "Random Access Memories", "Electronic", "2013", 369], ["Atemlos durch die Nacht", "Helene Fischer", "Farbenspiel", "Schlager", "2013", 219], ["Wonderwall", "Oasis", "(What's the Story) Morning Glory?", "Rock", "1995", 258]].map(([title, artist, album, genre, year, duration], i) => ({ title, artist, album, genre, year, duration, track: 1, path: "C:\\Musik\\" + artist + " - " + title + ".mp3", mtime: Date.now() / 1000 - i * 86400 * 9, format: "MP3" }));
  return {
    init: () => ({ version: "1.0.0", presets: P, settings, tools: { ffmpeg: true, ffprobe: true, ytdlp: true, ffmpeg_version: "ffmpeg version 7.1 (libmp3lame 3.100)", ytdlp_version: "2026.10.10" }, windows: true }),
    save_settings: p => (settings = { ...settings, ...p }),
    jobs_list: () => { jobs[0].progress = Math.min(.99, jobs[0].progress + .003); return { jobs, stream: { running: false }, inbox: 0 }; },
    link_analyze: url => new Promise(r => setTimeout(() => r(url.includes("album") ? { type: "single", title: "Adele - 21 (Full Album)", uploader: "Adele", duration: 2900, thumb: "", url, artist: "Adele", track: "21 (Full Album)", extractor: "Youtube", album: "21", genre: "Pop", date: "2011", meta_source: "iTunes", live: "", full_album: true, chapter_album: "21", chapters: ["Rolling in the Deep", "Rumour Has It", "Turning Tables", "Don't You Remember", "Set Fire to the Rain", "He Won't Go", "Take It All", "I'll Be Waiting", "One and Only", "Lovesong", "Someone Like You"].map((t, i) => ({ n: i + 1, start: i * 240, end: i * 240 + 228 + (i % 3) * 12, title: t })) } : url.includes("live") ? { type: "single", title: "Adele - Rolling in the Deep (Live at the Royal Albert Hall)", uploader: "Adele", duration: 233, thumb: "", url, artist: "Adele", track: "Rolling in the Deep (Live at the Royal Albert Hall)", extractor: "Youtube", album: "Live at the Royal Albert Hall", genre: "Pop", date: "2011", live: "Titel enthält „Live at the Royal Albert Hall“", can_search: true } : url.includes("list") ? { type: "playlist", title: "Synthwave Essentials", uploader: "NightDrive", count: 6, thumb: "", entries: ["Neon Skyline", "Midnight Run", "Chrome Hearts", "Afterglow", "Vapor Coast", "Last Exit"].map((t, i) => ({ title: "NightDrive – " + t, url: "u" + i, duration: 190 + i * 23 })) } : { type: "single", title: "Adele - Rolling in the Deep (Official Music Video)", uploader: "Adele", duration: 234, thumb: "", url, artist: "Adele", track: "Rolling in the Deep", extractor: "Youtube", album: "21", genre: "Pop", date: "2011", track_no: "1/11", cover_url: "", meta_source: "iTunes" }), 500)),
    link_download: items => items.map((_, i) => i),
    cd_drives: () => [{ letter: "E", label: "NENA" }],
    cd_read: L => String(L).endsWith(".cue") ? ({ letter: L, image: true, discid: "6CnCrrw52SEJyyfWnK3QxEJxvXc-", releases: [], lookup_error: "", cdtext: { album: "Testalbum ohne Laufwerk", artist: "SongGrabber Testband", date: "2026", genre: "Pop", tracks: { 1: { title: "Morgensonne" }, 2: { title: "Regentropfen" }, 3: { title: "Nachtfahrt" }, 4: { title: "Abschied (Live)" } } }, tracks: [24, 20, 27, 15].map((s, i) => ({ n: i + 1, start: i * 2000, end: i * 2000 + s * 75, seconds: s })) }) : ({ letter: "E", discid: "TqvKjMu7dMliSfmVEBtrL7sBSno-", tracks: [252, 228, 241, 199, 237, 262, 213, 205, 248, 227].map((s, i) => ({ n: i + 1, start: i * 20000, end: i * 20000 + s * 75, seconds: s })), releases: [{ album: "Nena", artist: "Nena", date: "1983-01-01", country: "DE", label: "CBS", disc: "", cover_url: "", tracks: ["Kino", "Nur geträumt", "Tanz auf dem Vulkan", "Ich häng an dir", "Leuchtturm", "99 Luftballons", "Satellitenstadt", "Lass mich dein Pirat sein", "Indianer", "Vollmond"].map((t, i) => ({ n: i + 1, title: t, artist: "Nena" })) }] }),
    cd_rip: () => 1, cd_eject: () => true,
    rec_devices: () => [{ id: "a", name: "Line-In (Realtek High Definition Audio)", loopback: false }, { id: "b", name: "Mikrofon (USB Headset)", loopback: false, default: true }, { id: "d", name: "Mikrofonarray (Realtek)", loopback: false }, { id: "c", name: "Lautsprecher (Realtek High Definition Audio)", loopback: true, default: true }, { id: "e", name: "Kopfhörer (USB Headset)", loopback: true }],
    rec_monitor: () => { const t = performance.now() / 1000, talk = Math.sin(t * 2.2) > 0; return { privacy: "ok", levels: { a: { peak: -62 + Math.random() * 3, rms: -70, hold: -58, zero: 0, state: "ok" }, b: { peak: talk ? -14 - Math.random() * 10 : -55, rms: -30, hold: -12, zero: 0, state: "ok" }, d: { peak: -90, rms: -90, hold: -90, zero: 4, state: "ok" }, c: { peak: -9 - Math.random() * 8, rms: -20, hold: -8, zero: 0, state: "ok", loop: true }, e: { peak: -90, rms: -90, hold: -90, zero: 3, state: "ok", loop: true } } }; },
    screen_sources: () => ({ supported: true, reason: "", screens: [{ id: "screen:0", name: "Bildschirm 1 (Hauptbildschirm)", size: "2560 × 1440", w: 2560, h: 1440, primary: true }, { id: "screen:1", name: "Bildschirm 2", size: "1920 × 1080", w: 1920, h: 1080, primary: false }],
      windows: [{ id: "win:11", title: "Zoom Meeting", app: "Zoom", w: 1600, h: 900, minimized: false }, { id: "win:12", title: "Wochenmeeting Vertrieb | Microsoft Teams", app: "Microsoft Teams", w: 1480, h: 920, minimized: false },
        { id: "win:13", title: "Live-Coaching: Zeitmanagement – YouTube – Google Chrome", app: "Google Chrome", w: 1920, h: 1040, minimized: false }, { id: "win:14", title: "Dokumente", app: "Explorer", w: 1100, h: 700, minimized: true }] }),
    screen_preview: id => {
      const c = document.createElement("canvas"); c.width = 480; c.height = 300; const g = c.getContext("2d");
      g.fillStyle = "#1b1d22"; g.fillRect(0, 0, 480, 300);
      if (id.startsWith("win:1") && id !== "win:13") {
        const names = ["Anna", "Marco", "Du", "Lea"], cols = ["#3d5a80", "#6d597a", "#2a9d8f", "#b56576"];
        names.forEach((n, i) => { const x = 8 + (i % 2) * 236, y = 8 + Math.floor(i / 2) * 136; g.fillStyle = cols[i]; g.fillRect(x, y, 228, 128); g.fillStyle = "rgba(255,255,255,.85)"; g.beginPath(); g.arc(x + 114, y + 56, 26, 0, 7); g.fill(); g.fillRect(x + 74, y + 88, 80, 30); g.fillStyle = "rgba(0,0,0,.5)"; g.fillRect(x + 6, y + 104, 54, 18); g.fillStyle = "#fff"; g.font = "12px sans-serif"; g.fillText(n, x + 12, y + 117); });
        g.fillStyle = "#111"; g.fillRect(0, 280, 480, 20); g.fillStyle = "#e5484d"; g.fillRect(212, 284, 56, 12);
      } else {
        g.fillStyle = "#2b2f38"; g.fillRect(0, 0, 480, 22); g.fillStyle = "#0f0f0f"; g.fillRect(20, 36, 300, 170); g.fillStyle = "#f4a261"; g.beginPath(); g.moveTo(150, 95); g.lineTo(190, 121); g.lineTo(150, 147); g.fill();
        g.fillStyle = "#cfd3da"; g.fillRect(20, 216, 240, 10); g.fillStyle = "#6b7280"; g.fillRect(20, 234, 160, 8); for (let i = 0; i < 4; i++) { g.fillStyle = "#30343d"; g.fillRect(336, 36 + i * 46, 124, 38); }
      }
      return c.toDataURL("image/jpeg", .8);
    },
    screen_start: o => { scr = { state: "recording", t: performance.now(), acc: 0, o }; return Mock.screen_status(); },
    screen_pause: () => { scr.acc += (performance.now() - scr.t) / 1000; scr.state = "paused"; return Mock.screen_status(); },
    screen_resume: () => { scr.t = performance.now(); scr.state = "recording"; return Mock.screen_status(); },
    screen_stop: () => { if (scr.state === "recording") scr.acc += (performance.now() - scr.t) / 1000; scr.state = "finishing"; scr.f = performance.now(); return Mock.screen_status(); },
    screen_mic: v => { scr.o = { ...scr.o, mic: v }; scr.micT = performance.now(); return Mock.screen_status(); },
    screen_discard: () => { scr = { state: "idle" }; return { state: "idle" }; },
    screen_close: () => true, open_file: () => true, video_url: () => "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4", screen_bar: () => ({ ok: true, hidden: true }),
    screen_status: () => {
      if (scr.state === "finishing" && performance.now() - scr.f > 2600) scr.state = "done";
      const el = scr.acc + (scr.state === "recording" ? (performance.now() - scr.t) / 1000 : 0) + (scr.fake || 0), t = performance.now() / 1000, o = scr.o || {}, lv = {};
      if (o.sys_audio) lv.sys = scr.state === "recording" ? -14 - Math.random() * 12 * (Math.sin(t * 1.7) > 0) : -90;
      if (o.mic) lv.mic = scr.state === "recording" && Math.sin(t * 2.3) > .3 ? -18 - Math.random() * 9 : -66;
      return { state: scr.state, elapsed: el, mic_on: !!o.mic, sys_on: !!o.sys_audio, mic_ready: !!o.mic && performance.now() - (scr.micT || 0) > 600, video_error: "", size: el * 92000, levels: lv, error: "", progress: scr.state === "finishing" ? Math.min(.98, (performance.now() - scr.f) / 2600) : 0,
        source: o.source === "win:11" ? "Zoom Meeting" : o.source === "win:12" ? "Wochenmeeting Vertrieb | Microsoft Teams" : "Bildschirm 1",
        result: scr.state === "done" ? { mp4: "C:\\Users\\Pezhy\\Music\\SongGrabber\\Bildschirmaufnahmen\\2026-10-31 14-05 Zoom Meeting.mp4", mp3: o.mp3 ? "x.mp3" : "", duration: el, size: el * 92000, has_audio: !!(o.sys_audio || o.mic) } : null };
    },
    rec_privacy_settings: () => true,
    rec_start: () => { rec = "recording"; t0 = performance.now(); w = []; return {}; },
    rec_stop: () => { rec = "idle"; return {}; }, rec_pause: () => { rec = rec === "paused" ? "recording" : "paused"; }, rec_discard: () => { rec = "idle"; }, rec_gain: () => true,
    rec_status: () => {
      const t = (performance.now() - t0) / 1000, a = rec === "recording" ? .35 + .3 * Math.abs(Math.sin(t * 1.3)) * Math.random() + .2 * Math.random() : 0;
      if (rec === "recording") { w.push(a); if (w.length > 300) w.shift(); }
      const db = a ? 20 * Math.log10(a) : -90;
      return { state: rec, peak: [db, db - 1.5 * Math.random()], rms: [db - 8, db - 9], elapsed: rec === "idle" ? 0 : t, clips: 0, wave: w, error: "" };
    },
    drop_sort: ps => { const d = { media: [], audio: [], folders: [], dvd: [], images: [], cue: [], playlists: [], links: [], other: [] }; ps.forEach(p => { const e = (p.match(/\.\w+$/) || [""])[0].toLowerCase(); if (!e) d.folders.push(p); else if (e === ".cue") d.cue.push(p); else if (/\.m3u8?$/.test(e)) d.playlists.push(p); else if (/\.(jpe?g|png|webp)$/.test(e)) d.images.push(p); else if (/\.(mp3|flac|wav|m4a|ogg|opus|mp4|mkv|webm|avi|mov)$/.test(e)) { d.media.push(p); if (/\.(mp3|flac|wav|m4a|ogg|opus)$/.test(e)) d.audio.push(p); } else if (e === ".url") d.links.push("https://youtu.be/demo"); else d.other.push(p); }); return d; },
    dvd_from: () => [], output_check: () => ({ ok: true }), update_check: f => ({ enabled: true, newer: !!f, version: "1.9.1", current: "1.9.0", url: "https://example.org", notes: "**Neu:** Handy-Fernbedienung\n- schnellere Bibliothek" }), mini: () => true, cleanup_start: () => true, cleanup_fill: p => 1, cleanup_empty: d => d.length,
    cleanup_status: () => ({ running: false, done: 9, total: 9, result: { dup_free: 9.4e6, dups: [{ artist: "Adele", title: "Rolling in the Deep", files: [{ path: "C:\\Users\\Pezhy\\Music\\SongGrabber\\Adele\\21\\01 - Rolling in the Deep.flac", q: "FLAC · 16 Bit / 44,1 kHz", size: 31e6, cover: true, album: "21", keep: true }, { path: "C:\\Users\\Pezhy\\Music\\SongGrabber\\Adele\\Singles\\Rolling in the Deep.mp3", q: "MP3 · 128 kbps", size: 3.6e6, cover: false, album: "" }, { path: "C:\\Users\\Pezhy\\Music\\SongGrabber\\Singles\\Adele - Rolling in the Deep.mp3", q: "MP3 · 192 kbps", size: 5.8e6, cover: true, album: "" }] }, { artist: "Nena", title: "99 Luftballons", files: [{ path: "C:\\Users\\Pezhy\\Music\\SongGrabber\\Nena\\Nena\\03 - 99 Luftballons.mp3", q: "MP3 · 320 kbps", size: 9e6, cover: true, album: "Nena", keep: true }, { path: "C:\\Users\\Pezhy\\Music\\SongGrabber\\Nena\\Singles\\99 Luftballons.mp3", q: "MP3 · 256 kbps", size: 7e6, cover: true, album: "" }] }], missing: { cover: 12, album: 7, genre: 9, year: 15 }, fill: Array(23).fill("x"), empty: ["C:\\Users\\Pezhy\\Music\\SongGrabber\\Alt\\Leer"] } }), loudness: ps => Object.fromEntries(ps.map((p, i) => [p, i ? -3 : 2.5])),
    files_probe: () => [{ path: "C:\\Videos\\Konzert.mp4", name: "Konzert Live 2024.mp4", duration: 3721, artist: "", title: "Konzert Live 2024", codec: "aac", rate: 48000, streams: [{ codec: "aac", channels: 2 }], video: true, ok: true }],
    choose_files: () => ["x"], choose_folder: () => "", files_convert: f => f.map((_, i) => i), get_clipboard: () => "https://www.youtube.com/watch?v=demo",
    lib_list: () => ({ items: LIB, status: { scanning: false, done: LIB.length, total: LIB.length, count: LIB.length } }),
    lib_status: () => ({ count: LIB.length }), lib_scan: () => true,
    media_urls: p => p.map(x => { const i = LIB.find(l => l.path === x) || { title: x }; return { ...i, src: "", art: "", path: x }; }),
    playlist_list: () => [{ path: "a.m3u8", name: "Adele", count: 12, auto: true, mtime: 1 }, { path: "b.m3u8", name: "80er", count: 46, auto: true, mtime: 1 }, { path: "c.m3u8", name: "Zufallsmix 2026-10-26", count: 50, auto: true, mtime: 1 }],
    playlist_items: () => LIB.slice(0, 5).map(i => ({ ...i, src: "", art: "" })), playlist_create: () => ["Adele.m3u8", "Pop.m3u8"], playlist_delete: () => true,
    radio_search: () => [["1LIVE", "pop,charts,news", 128], ["SWR3", "pop,rock", 128], ["Radio Bob!", "rock,classic rock", 192], ["Klassik Radio", "classical", 128], ["sunshine live", "electronic,dance,techno", 192], ["Deutschlandfunk", "news,culture", 128], ["bigFM", "hiphop,urban", 128], ["Antenne Bayern", "pop,80s", 128], ["Jazz Radio", "jazz,smooth jazz", 128]].map(([name, t, br], i) => ({ uuid: "u" + i, name, url: "x", favicon: "", tags: t.split(","), country: "DE", bitrate: br })),
    radio_tags: () => ["pop", "rock", "news", "dance", "classical", "jazz", "80s", "electronic", "hiphop", "schlager", "oldies", "chillout", "metal", "country", "kinder"],
    radio_favorites: () => ({ favorites: [{ uuid: "u2", name: "Radio Bob!", url: "x", favicon: "", tags: ["rock"], country: "DE", bitrate: 192 }], recent: [] }),
    radio_toggle_fav: () => true, radio_played: () => true, radio_now: () => ({}), radio_record: () => ({}),
    podcast_subs: () => [{ feed: "f1", title: "Gemischtes Hack", author: "Felix Lobrecht & Tommi Schmitt", image: "" }, { feed: "f2", title: "Tagesschau", author: "ARD", image: "" }],
    podcast_progress: () => ({ e1: { pos: 1200, dur: 3600, done: false } }), podcast_progress_set: () => true,
    podcast_search: () => [{ feed: "f3", title: "Fest & Flauschig", author: "Spotify Studios", image: "", genre: "Comedy" }],
    podcast_open: f => ({ feed: f, title: "Gemischtes Hack", author: "Felix Lobrecht & Tommi Schmitt", image: "", description: "Der Podcast mit Felix Lobrecht und Tommi Schmitt.", episodes: [1, 2, 3, 4].map(i => ({ guid: "e" + i, title: `#${300 - i} Folgentitel ${i}`, url: "x", date: Date.now() / 1000 - i * 86400 * 7, duration: 3600 + i * 120, description: "Kurze Beschreibung dieser Folge mit ein paar Worten mehr, damit man sieht, wie es umbricht.", image: "" })) }),
    podcast_subscribe: () => true, podcast_unsubscribe: () => true, podcast_download: () => 1,
    items_resolve: en => en.map(e => typeof e === "string" ? { kind: "file", path: e, title: e } : e.kind === "radio" ? { kind: "radio", src: "", path: "radio:" + e.uuid, uuid: e.uuid, url: e.url, title: e.name, station: e.name, artist: (e.tags || []).join(" · "), favicon: e.favicon, art: "", live: true, tags: e.tags } : Object.assign({ src: "", art: "", path: e.url }, e)),
    online_search: () => [{ url: "u1", title: "Daft Punk - Get Lucky (Official Audio)", artist: "Daft Punk", track: "Get Lucky", uploader: "Daft Punk", duration: 369, thumb: "" }, { url: "u2", title: "Daft Punk - Get Lucky (Live at Coachella)", artist: "Daft Punk", track: "Get Lucky (Live)", uploader: "Fan", duration: 400, thumb: "", live: true }],
    sys_viz_url: () => "", now_playing: () => ({ active: true, app: "Chrome", title: "Adele - Someone Like You (Official Music Video)", artist: "Adele", album: "", playing: true, art: "", position: 3, pos_now: (Date.now() / 1000 - (window.__t0 || (window.__t0 = Date.now() / 1000 - 3))) , duration: 285, pos_live: true }),
    lyrics_smart: () => ({ synced: "[00:00.00]I heard that you're settled down\n[00:04.00]That you found a girl and you're married now\n[00:08.00]I heard that your dreams came true\n[00:12.00]Guess she gave you things I didn't give to you\n[00:16.00]Old friend, why are you so shy?\n[00:20.00]Ain't like you to hold back or hide from the light\n[00:24.00]I hate to turn up out of the blue, uninvited\n[00:28.00]But I couldn't stay away, I couldn't fight it", plain: "", instrumental: false, artist: "Adele", title: "Someone Like You" }), media_control: () => true,
    set_clipboard: () => true, open_url: () => true, player_state_load: () => ({}), player_state_save: () => true, playlist_save: n => n, files_expand_audio: ps => ps.filter(x => /\.(mp3|flac|wav|m4a|ogg|opus)$/i.test(x)), toggle_fullscreen: () => false, log_js: () => true, cd_make_test: () => "C:\\Test-CD\\Test-CD.cue", log_open: () => true, cd_open_image: () => "C:\\Musik\\Test-CD\\Test-CD.cue", diagnose: () => "SongGrabber – Diagnose", lib_delete: p => ({ deleted: p.length, errors: [], recycle: true }),
    link_find_original: () => new Promise(r => setTimeout(() => r({ clean_title: "Rolling in the Deep", candidates: [
      { url: "u1", title: "Rolling in the Deep", uploader: "Adele - Topic", duration: 228, kind: "Studioaufnahme (YouTube Music)", thumb: "" },
      { url: "u2", title: "Adele - Rolling in the Deep (Official Music Video)", uploader: "Adele", duration: 234, kind: "Offizielles Musikvideo", thumb: "" }] }), 700)),
    tags_read: p => p.map((x, i) => ({ ...(LIB.find(l => l.path === x) || LIB[0]), path: x, album_artist: "Adele", track: i === 0 ? "1/11" : String(i + 1), disc: "", date: "2011", format: "MP3", has_cover: false, art: "", lyrics: i === 0 ? "[00:01.00]There's a fire starting in my heart\n[00:05.00]Reaching a fever pitch\n[00:09.00]And it's bringing me out the dark" : "" })),
    tags_online: () => ({ album: "21", album_artist: "Adele", genre: "Pop", date: "2011", track: "1/11", cover_url: "", source: "iTunes" }),
    tags_save: p => ({ paths: p, errors: [] }), lyrics_fetch: () => ({ synced: "[00:01.00]Zeile eins\n[00:04.00]Zeile zwei\n[00:07.00]Zeile drei", plain: "", instrumental: false }),
    lyrics_for: () => "[00:00.50]There's a fire starting in my heart\n[00:04.00]Reaching a fever pitch and it's bringing me out the dark\n[00:08.00]Finally, I can see you crystal clear\n[00:12.00]Go ahead and sell me out and I'll lay your ship bare\n[00:16.00]See how I'll leave with every piece of you",
    identify_status: () => ({ available: true, key: false }), identify_files: () => 1, lyrics_files: () => 1,
    trim_analyze: () => { const peaks = []; for (let i = 0; i < 1200; i++) { const t = i / 1200 * 84; peaks.push(t < 6 ? .03 : t < 10 ? .25 * Math.abs(Math.sin(t * 9)) : t < 73 ? .55 + .4 * Math.abs(Math.sin(t * 3.1)) * Math.random() : t < 81 ? .45 * Math.random() : 0); } return { duration: 84, peaks, start: 9.75, end: 73.6, why: "Vorschlag: 9.8 s am Anfang (Stille, Rauschen oder Ansage) und 10.4 s am Ende (Applaus, Stille oder Rauschen)", src: "" }; },
    trim_apply: () => ({ duration: 63.8 }),
    export_drives: () => [{ root: "E:\\", label: "AUTO-USB", fs: "FAT32", free: 28.4e9, total: 32e9 }],
    export_start: () => 1, playlist_paths: () => LIB.slice(0, 5).map(i => i.path),
    abos_list: () => ({ hours: 6, autostart: false, items: [{ id: "a1", name: "LALELU Traumwelt", url: "https://www.youtube.com/@LALELU-Traumwelt", enabled: true, last_check: Date.now() / 1000 - 1500, last_new: Date.now() / 1000 - 86400 * 2, count: 14, skip_live: true, error: "" }, { id: "a2", name: "Synthwave Radio", url: "https://www.youtube.com/playlist?list=PL123", enabled: false, last_check: Date.now() / 1000 - 90000, count: 3, skip_live: true, error: "" }] }),
    abos_add: u => ({ name: "Neuer Kanal" }), abos_check: () => 2, abos_update: () => true, abos_remove: () => true, autostart_set: v => v,
    set_layout: k => (settings = { ...settings, name_single: LAYOUTS[k][0], name_album: LAYOUTS[k][1] }),
    lib_reorganize: () => ({ count: 2, preview: [{ from: "Adele - Rolling in the Deep.mp3", to: "Adele/21/01 - Rolling in the Deep.mp3" }], errors: [] }),
    open_path: () => true, jobs_clear: () => true, job_cancel: () => true, pop_inbox: () => [], ytdlp_update: () => "yt-dlp ist aktuell",
  };
})();
