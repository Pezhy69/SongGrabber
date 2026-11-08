"use strict";
/* Handy-Mikro – Empfang am Rechner (Test).
   Das Handy schickt seine Stimme per WebRTC. Sie läuft hier durch denselben Tonweg wie die Karaoke-Videos.
   measure(): Klicks über den Lautsprecher spielen, das Handy hört sie und schickt sie zurück –
   die Zeit bis zur Rückkehr ist genau der Weg, den die Stimme beim Singen nimmt (Handy → Rechner → Lautsprecher). */
const MicRx = (() => {
  const FS_CLICK = 0.02, MAX_LAG = 0.9;
  let ctx = null, pc = null, cur = null, gain = null, an = null, cap = null, node = null, onState = () => { };
  let rec = null;                                // { start: frame, chunks: [] } während einer Messung
  const WORKLET = `class SgCap extends AudioWorkletProcessor{process(i){const c=i[0]&&i[0][0];if(c)this.port.postMessage({f:currentFrame,d:c.slice(0)});return true}}registerProcessor("sg-cap",SgCap);`;

  async function ensureCtx() {
    if (ctx) { if (ctx.state === "suspended") await ctx.resume(); return ctx; }
    ctx = new AudioContext({ latencyHint: "interactive", sampleRate: 48000 });
    await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" })));
    gain = ctx.createGain(); gain.gain.value = 0; gain.connect(ctx.destination);
    an = ctx.createAnalyser(); an.fftSize = 1024;
    cap = new AudioWorkletNode(ctx, "sg-cap");
    const sink = ctx.createGain(); sink.gain.value = 0; cap.connect(sink); sink.connect(ctx.destination);
    cap.port.onmessage = e => { if (rec) rec.chunks.push(e.data); };
    return ctx;
  }
  function iceDone(p) {
    return new Promise(ok => {
      if (p.iceGatheringState === "complete") return ok();
      const f = () => { if (p.iceGatheringState === "complete") ok(); };
      p.addEventListener("icegatheringstatechange", f); setTimeout(ok, 2500);
    });
  }
  const fast = sdp => {
    const m = sdp.match(/a=rtpmap:(\d+) opus\/48000/i); if (!m) return sdp;
    if (!/a=ptime:/.test(sdp)) sdp = sdp.replace(/(m=audio[^\r\n]*\r\n)/, "$1a=ptime:10\r\n");
    return sdp.replace(new RegExp("a=fmtp:" + m[1] + " ([^\\r\\n]*)"), (_, p) => "a=fmtp:" + m[1] + " " + p.replace(/;?(minptime|useinbandfec)=[^;]*/g, "") + ";minptime=10;useinbandfec=0");
  };
  /* Verbindungsangebot eines Handys (kommt über die Party) */
  async function offer(a) {
    try {
      await ensureCtx();
      if (pc) { try { pc.close(); } catch { } }
      pc = new RTCPeerConnection({ iceServers: [] });
      cur = { sid: a.sid, name: a.name, state: "verbinde" }; onState(cur);
      pc.ontrack = e => {
        const st = e.streams[0] || new MediaStream([e.track]);
        try { e.receiver.jitterBufferTarget = 0; } catch { }
        try { e.receiver.playoutDelayHint = 0; } catch { }
        const el = new Audio(); el.muted = true; el.srcObject = st; el.play().catch(() => { });   // sonst fließt der Ton in Chromium nicht
        if (node) try { node.disconnect(); } catch { }
        node = ctx.createMediaStreamSource(st);
        node.connect(gain); node.connect(an); node.connect(cap);
      };
      pc.onconnectionstatechange = () => { if (!cur) return; cur.state = pc.connectionState; onState(cur); };
      await pc.setRemoteDescription({ type: "offer", sdp: a.sdp });
      const ans = await pc.createAnswer(); ans.sdp = fast(ans.sdp);
      await pc.setLocalDescription(ans); await iceDone(pc);
      await call("party_rtc_answer", a.sid, pc.localDescription.sdp);
    } catch (e) { cur = { sid: a.sid, name: a.name, state: "failed", error: String(e.message || e) }; onState(cur); }
  }
  function bye(a) { if (cur && a.sid === cur.sid) { try { pc.close(); } catch { } pc = null; cur = { ...cur, state: "closed" }; onState(cur); } }
  function level() {
    if (!an) return 0;
    const b = new Float32Array(an.fftSize); an.getFloatTimeDomainData(b);
    let p = 0; for (const x of b) p = Math.max(p, Math.abs(x)); return p;
  }
  function monitor(on, vol) { if (gain) gain.gain.setTargetAtTime(on ? vol : 0, ctx.currentTime, .02); }
  async function rtt() {                      // reine Netzwerk-Laufzeit (Hin und zurück) laut WebRTC
    if (!pc) return null;
    try { const s = await pc.getStats(); let v = null; s.forEach(r => { if (r.type === "candidate-pair" && r.nominated && r.currentRoundTripTime != null) v = r.currentRoundTripTime; }); return v; } catch { return null; }
  }
  function chirp(sr) {
    const n = Math.round(sr * FS_CLICK), out = new Float32Array(n), f0 = 1200, f1 = 6000, T = (n - 1) / sr;
    for (let i = 0; i < n; i++) { const t = i / sr; out[i] = Math.sin(2 * Math.PI * (f0 * t + (f1 - f0) / (2 * T) * t * t)) * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1))); }
    return out;
  }
  /* Abgleich: frühester kräftiger Treffer pro Klick (spätere Spitzen = Raumecho) */
  function analyze(sig, start, ch, clicks, sr) {
    const env = (a, b) => { const out = new Float32Array(Math.max(0, b - a)); for (let k = a; k < b; k++) { let s = 0; for (let j = 0; j < ch.length; j++) s += (sig[k + j] || 0) * ch[j]; out[k - a] = Math.abs(s); } return out; };
    const lags = [], all = [];
    const wins = clicks.map(c => { const a = Math.max(0, Math.round(c - start)), b = Math.min(sig.length - ch.length, a + Math.round(MAX_LAG * sr)); const e = env(a, b); all.push(...e.filter((_, i) => i % 7 === 0)); return e; });
    all.sort((x, y) => x - y); const noise = (all[all.length >> 1] || 0) + 1e-9;
    for (const w of wins) {
      if (!w.length) { lags.push(null); continue; }
      let top = 0; for (const x of w) top = Math.max(top, x);
      if (top / noise <= 12) { lags.push(null); continue; }
      let i = w.findIndex(x => x >= top * .5); const j = Math.min(w.length, i + Math.round(.003 * sr));
      for (let k = i; k < j; k++) if (w[k] > w[i]) i = k;
      // Echtheitsprüfung: Form muss zum Klick passen (normierte Korrelation), sonst ist es nur Geräusch/Brummen
      const at = Math.max(0, Math.round(clicks[lags.length] - start)) + i;
      let e = 0, c2 = 0; for (let j2 = 0; j2 < ch.length; j2++) { const v = sig[at + j2] || 0; e += v * v; c2 += ch[j2] * ch[j2]; }
      lags.push(w[i] / Math.sqrt(e * c2 + 1e-12) > .35 ? i / sr * 1000 : null);
    }
    return lags;
  }
  function summary(lags) {
    const g = lags.filter(x => x != null).sort((a, b) => a - b);
    if (g.length < 3) return { ok: false, heard: g.length, of: lags.length };
    const q = p => g[Math.min(g.length - 1, Math.floor(p * (g.length - 1)))];
    return { ok: true, ms: Math.round(q(.5)), min: Math.round(g[0]), max: Math.round(g[g.length - 1]), spread: Math.round(q(.9) - q(.1)), heard: g.length, of: lags.length };
  }
  async function measure() {
    if (!pc || !cur || cur.state !== "connected") throw new Error(T("Kein Handy verbunden."));
    await ensureCtx();
    const sr = ctx.sampleRate, ch = chirp(sr), buf = ctx.createBuffer(1, ch.length, sr); buf.copyToChannel(ch, 0);
    const out = ctx.createGain(); out.gain.value = .8; out.connect(ctx.destination);
    const t0 = ctx.currentTime + .4, times = [0]; for (let i = 1; i < 7; i++) times.push(times[i - 1] + 0.95 + Math.random() * .25);
    rec = { chunks: [] };
    times.forEach(t => { const s = ctx.createBufferSource(); s.buffer = buf; s.connect(out); s.start(t0 + t); });
    await new Promise(ok => setTimeout(ok, (times[times.length - 1] + .4 + MAX_LAG + .4) * 1000));
    const chunks = rec.chunks; rec = null; out.disconnect();
    if (!chunks.length) throw new Error(T("Vom Handy kommt kein Ton an."));
    const start = chunks[0].f, len = chunks[chunks.length - 1].f + chunks[chunks.length - 1].d.length - start, sig = new Float32Array(len);
    for (const c of chunks) sig.set(c.d, c.f - start);
    const clicks = times.map(t => (t0 + t) * sr);
    const res = summary(analyze(sig, start, ch, clicks, sr));
    const r = await rtt(); if (r != null) res.net = Math.round(r * 1000);
    res.out = Math.round(((ctx.outputLatency || 0) + (ctx.baseLatency || 0)) * 1000);
    return res;
  }
  return { offer, bye, level, monitor, measure, onState: f => { onState = f; if (cur) f(cur); }, state: () => cur, _analyze: analyze, _chirp: chirp, _summary: summary };
})();
window.MicRx = MicRx;
