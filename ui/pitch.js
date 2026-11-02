/* SongGrabber – Tonart ändern (Karaoke): Phase-Vocoder als AudioWorklet.
   Verschiebt die Tonhöhe in Halbtönen, das Tempo bleibt gleich. Wird erst beim ersten Umstellen
   eingehängt – wer die Tonart nie ändert, hört das Video ganz unverändert. */
"use strict";

/* Kern (läuft im Audio-Thread): klassischer Phase-Vocoder nach S. M. Bernsee, 2048er FFT, 4-fach überlappend */
function sgShifter(sr) {
  const N = 2048, OS = 4, STEP = N / OS, LAT = N - STEP, H = N / 2;
  const win = new Float32Array(N);
  for (let k = 0; k < N; k++) win[k] = -0.5 * Math.cos(2 * Math.PI * k / N) + 0.5;
  const inF = new Float32Array(N), outF = new Float32Array(N), acc = new Float32Array(2 * N);
  const lastPh = new Float32Array(H + 1), sumPh = new Float32Array(H + 1);
  const re = new Float32Array(N), im = new Float32Array(N);
  const aMag = new Float32Array(H + 1), aFrq = new Float32Array(H + 1), sMag = new Float32Array(H + 1), sFrq = new Float32Array(H + 1);
  const rev = new Uint16Array(N);
  for (let i = 0, j = 0; i < N; i++) { rev[i] = j; let b = N >> 1; while (j & b) { j ^= b; b >>= 1; } j |= b; }
  const cosT = new Float32Array(H), sinT = new Float32Array(H);
  for (let i = 0; i < H; i++) { cosT[i] = Math.cos(2 * Math.PI * i / N); sinT[i] = Math.sin(2 * Math.PI * i / N); }
  function fft(sign) {
    for (let i = 0; i < N; i++) { const j = rev[i]; if (j > i) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; } }
    for (let size = 2; size <= N; size <<= 1) {
      const half = size >> 1, step = N / size;
      for (let s = 0; s < N; s += size) {
        for (let k = 0, t = 0; k < half; k++, t += step) {
          const wr = cosT[t], wi = sign * sinT[t], a = s + k, b = a + half;
          const xr = re[b] * wr - im[b] * wi, xi = re[b] * wi + im[b] * wr;
          re[b] = re[a] - xr; im[b] = im[a] - xi; re[a] += xr; im[a] += xi;
        }
      }
    }
  }
  const expct = 2 * Math.PI * STEP / N, fpb = sr / N;
  let ratio = 1, rover = LAT;
  function frame() {
    if (ratio === 1) {                                   // unverändert: nur gleich lang verzögern, damit Bild und Ton beim Umschalten nicht springen
      for (let k = 0; k < STEP; k++) outF[k] = inF[k];
      lastPh.fill(0); sumPh.fill(0); acc.fill(0);
    } else {
      for (let k = 0; k < N; k++) { re[k] = inF[k] * win[k]; im[k] = 0; }
      fft(-1);
      for (let k = 0; k <= H; k++) {
        const r = re[k], i = im[k], mag = 2 * Math.sqrt(r * r + i * i), ph = Math.atan2(i, r);
        let t = ph - lastPh[k]; lastPh[k] = ph;
        t -= k * expct;
        let q = Math.trunc(t / Math.PI); q += q >= 0 ? (q & 1) : -(q & 1);
        t -= Math.PI * q;
        aMag[k] = mag; aFrq[k] = k * fpb + OS * t / (2 * Math.PI) * fpb;
      }
      sMag.fill(0); sFrq.fill(0);
      for (let k = 0; k <= H; k++) { const j = Math.floor(k * ratio); if (j <= H) { sMag[j] += aMag[k]; sFrq[j] = aFrq[k] * ratio; } }
      for (let k = 0; k <= H; k++) {
        let t = (sFrq[k] - k * fpb) / fpb;
        t = 2 * Math.PI * t / OS + k * expct;
        sumPh[k] += t;
        re[k] = sMag[k] * Math.cos(sumPh[k]); im[k] = sMag[k] * Math.sin(sumPh[k]);
      }
      for (let k = H + 1; k < N; k++) { re[k] = 0; im[k] = 0; }
      fft(1);
      const g = 2 / (H * OS) / 1.25;              // gemessen: so bleibt die Lautstärke bei ±1…3 Halbtönen fast gleich
      for (let k = 0; k < N; k++) acc[k] += g * win[k] * re[k];
      for (let k = 0; k < STEP; k++) outF[k] = acc[k];
      acc.copyWithin(0, STEP); acc.fill(0, 2 * N - STEP);
    }
    inF.copyWithin(0, STEP, N);
  }
  return {
    set(semi) { ratio = Math.pow(2, (semi || 0) / 12); if (Math.abs(ratio - 1) < 1e-6) ratio = 1; },
    run(x, y) {
      for (let i = 0; i < x.length; i++) {
        inF[rover] = x[i]; y[i] = outF[rover - LAT]; rover++;
        if (rover >= N) { rover = LAT; frame(); }
      }
    },
  };
}

const KPitch = (() => {
  const CODE = `${sgShifter.toString()}
class SgPitch extends AudioWorkletProcessor {
  constructor() { super(); this.semi = 0; this.s = []; this.port.onmessage = e => { this.semi = e.data; this.s.forEach(s => s.set(this.semi)); }; }
  process(ins, outs) {
    const inp = ins[0] || [], out = outs[0];
    for (let c = 0; c < out.length; c++) {
      const x = inp[c] || inp[0];
      if (!this.s[c]) { this.s[c] = sgShifter(sampleRate); this.s[c].set(this.semi); }
      if (!x) { out[c].fill(0); continue; }
      this.s[c].run(x, out[c]);
    }
    return true;
  }
}
registerProcessor("sg-pitch", SgPitch);`;
  let ctx = null, node = null, attached = null, semi = 0, failed = false;
  async function ensure(media) {
    if (failed) return false;
    if (attached === media && node) { if (ctx.state !== "running") await ctx.resume().catch(() => { }); return true; }
    try {
      if (!ctx) {
        ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: "playback" });
        if (!ctx.audioWorklet) throw new Error("kein AudioWorklet");
        await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([CODE], { type: "application/javascript" })));
      }
      if (ctx.state !== "running") await ctx.resume().catch(() => { });
      const src = ctx.createMediaElementSource(media);
      node = new AudioWorkletNode(ctx, "sg-pitch", { outputChannelCount: [2] });
      node.port.postMessage(semi);
      src.connect(node).connect(ctx.destination);
      attached = media;
      return true;
    } catch (e) { console.warn("Tonart:", e); failed = true; return false; }
  }
  return {
    /** Tonart für ein <video>/<audio> setzen (Halbtöne, -6 … +6). Gibt false zurück, wenn der Browser es nicht kann. */
    async set(media, n) {
      semi = Math.max(-6, Math.min(6, Math.round(n || 0)));
      if (!semi && !node) return true;                       // nie umgestellt → gar nicht erst einhängen
      if (!(await ensure(media))) return false;
      node.port.postMessage(semi);
      return true;
    },
    get value() { return semi; },
    get available() { return !failed && !!(window.AudioContext || window.webkitAudioContext); },
  };
})();
if (typeof module !== "undefined") module.exports = { sgShifter };
