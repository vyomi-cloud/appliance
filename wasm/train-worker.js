/* Nano head-training worker (classic Web Worker): plain typed-array JS Adam heads on frozen embeddings (spike: spikes/nano-training-trainhead).
 * Same artifact + same split/baseline contract as core/training_core.py's head-py runner, so either substrate can serve either head.
 *   in : {cmd:"train", id, task, labels, rows, epochs, lr, bs, seed, texts, vecs:Float32Array(n*D), D, embedder}   |   {cmd:"cancel", id}
 *   out: {id, status}, {id, metric:{epoch,loss,accuracy,valAccuracy}, progress}, {id, head:{kind,labels,embedder,dims,metrics,heldOut}}, {id, error}
 * Cancellation: the loop yields to the event loop between batches so a "cancel" message is seen within one mini-batch. */
const cancelled = new Set();
const out = (m) => postMessage(m);
const tick = () => new Promise((r) => setTimeout(r, 0));
const b64 = (u8) => { let s = ""; for (let i = 0; i < u8.length; i += 8192) s += String.fromCharCode.apply(null, u8.subarray(i, i + 8192)); return btoa(s); };
function mulberry(a) { return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
class Net {
  constructor(dims, outAct, seed = 3) {
    this.dims = dims; this.outAct = outAct; const r = mulberry(seed), g = () => Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r());
    this.W = []; this.b = [];
    for (let l = 0; l < dims.length - 1; l++) { const w = new Float32Array(dims[l] * dims[l + 1]); const sc = Math.sqrt(2 / dims[l]) * (l === dims.length - 2 ? 0.5 : 1); for (let i = 0; i < w.length; i++) w[i] = g() * sc; this.W.push(w); this.b.push(new Float32Array(dims[l + 1])); }
    const P = this.W.concat(this.b); this.m = P.map((a) => new Float32Array(a.length)); this.v = P.map((a) => new Float32Array(a.length)); this.t = 0;
  }
  forward(x, B) {
    const acts = [x]; let a = x; const L = this.dims.length - 1;
    for (let l = 0; l < L; l++) {
      const di = this.dims[l], dout = this.dims[l + 1], W = this.W[l], bb = this.b[l], z = new Float32Array(B * dout);
      for (let n = 0; n < B; n++) { const zo = n * dout; for (let j = 0; j < dout; j++) z[zo + j] = bb[j]; for (let i = 0; i < di; i++) { const xv = a[n * di + i]; if (xv === 0) continue; const wo = i * dout; for (let j = 0; j < dout; j++) z[zo + j] += xv * W[wo + j]; } }
      if (l < L - 1) { for (let i = 0; i < z.length; i++) if (z[i] < 0) z[i] = 0; }
      else if (this.outAct === "softmax") { for (let n = 0; n < B; n++) { let mx = -1e9; for (let j = 0; j < dout; j++) mx = Math.max(mx, z[n * dout + j]); let s = 0; for (let j = 0; j < dout; j++) { z[n * dout + j] = Math.exp(z[n * dout + j] - mx); s += z[n * dout + j]; } for (let j = 0; j < dout; j++) z[n * dout + j] /= s; } }
      else for (let i = 0; i < z.length; i++) z[i] = 1 / (1 + Math.exp(-Math.max(-30, Math.min(30, z[i]))));
      acts.push(z); a = z;
    }
    return acts;
  }
  step(x, y, B, lr) {
    const acts = this.forward(x, B), L = this.dims.length - 1, o = acts[L], dout = this.dims[L]; let loss = 0, ok = 0;
    let dz = new Float32Array(B * dout);
    if (this.outAct === "softmax") for (let n = 0; n < B; n++) { let bi = 0; for (let j = 0; j < dout; j++) { dz[n * dout + j] = (o[n * dout + j] - (y[n] === j ? 1 : 0)) / B; if (o[n * dout + j] > o[n * dout + bi]) bi = j; } loss -= Math.log(o[n * dout + y[n]] + 1e-9) / B; if (bi === y[n]) ok++; }
    else for (let n = 0; n < B; n++) { const p = o[n]; dz[n] = (p - y[n]) / B; loss -= (y[n] * Math.log(p + 1e-9) + (1 - y[n]) * Math.log(1 - p + 1e-9)) / B; if ((p >= 0.5) === (y[n] === 1)) ok++; }
    const gW = [], gb = [];
    for (let l = L - 1; l >= 0; l--) {
      const di = this.dims[l], dO = this.dims[l + 1], a = acts[l], W = this.W[l], gw = new Float32Array(di * dO), g0 = new Float32Array(dO);
      for (let n = 0; n < B; n++) { for (let j = 0; j < dO; j++) g0[j] += dz[n * dO + j]; for (let i = 0; i < di; i++) { const av = a[n * di + i]; if (av === 0) continue; for (let j = 0; j < dO; j++) gw[i * dO + j] += av * dz[n * dO + j]; } }
      gW[l] = gw; gb[l] = g0;
      if (l > 0) { const nd = new Float32Array(B * di); for (let n = 0; n < B; n++) for (let i = 0; i < di; i++) { if (a[n * di + i] <= 0) continue; let s = 0; for (let j = 0; j < dO; j++) s += dz[n * dO + j] * W[i * dO + j]; nd[n * di + i] = s; } dz = nd; }
    }
    this.t++; const b1 = 0.9, b2 = 0.999, c1 = 1 - Math.pow(b1, this.t), c2 = 1 - Math.pow(b2, this.t), P = this.W.concat(this.b), G = gW.concat(gb);
    for (let k = 0; k < P.length; k++) { const p = P[k], g = G[k], m = this.m[k], v = this.v[k]; for (let i = 0; i < p.length; i++) { m[i] = b1 * m[i] + (1 - b1) * g[i]; v[i] = b2 * v[i] + (1 - b2) * g[i] * g[i]; p[i] -= lr * (m[i] / c1) / (Math.sqrt(v[i] / c2) + 1e-8); } }
    return [loss, ok / B];
  }
  predict(x, B) { return this.forward(x, B)[this.dims.length - 1]; }
  toJSON() { return { dims: this.dims, outAct: this.outAct, W: this.W.map((w) => b64(new Uint8Array(w.buffer))), b: this.b.map((w) => b64(new Uint8Array(w.buffer))) }; }
}
const pairFeat = (q, d, D) => { const f = new Float32Array(2 * D); for (let i = 0; i < D; i++) { f[i] = q[i] * d[i]; f[D + i] = Math.abs(q[i] - d[i]); } return f; };
const dot = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };
const argmax = (a, o, n) => { let b = 0; for (let i = 1; i < n; i++) if (a[o + i] > a[o + b]) b = i; return b; };

async function train(m) {
  const { id, task, labels, rows, epochs, lr, bs, seed, texts, vecs, D, embedder } = m;
  const idx = new Map(texts.map((t, i) => [t, i])), E = (t) => vecs.subarray(idx.get(t) * D, (idx.get(t) + 1) * D);
  const rnd = mulberry(seed || 7), order = Array.from({ length: rows.length }, (_, i) => i);
  for (let i = order.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [order[i], order[j]] = [order[j], order[i]]; }
  const nho = Math.max(2, Math.floor(rows.length * 0.2)), ho = order.slice(0, nho).map((i) => rows[i]), tr = order.slice(nho).map((i) => rows[i]);
  out({ id, status: "Training", progress: 0.2 });
  let net, X, Y, heldacc, baseAcc, baseKind;
  if (task === "reranker") {
    X = new Float32Array(tr.length * 2 * 2 * D); Y = new Float32Array(tr.length * 2);
    tr.forEach((r, i) => { X.set(pairFeat(E(r.query), E(r.positive), D), (2 * i) * 2 * D); Y[2 * i] = 1; X.set(pairFeat(E(r.query), E(r.negative), D), (2 * i + 1) * 2 * D); Y[2 * i + 1] = 0; });
    net = new Net([2 * D, 1], "sigmoid", 3);
    heldacc = () => ho.filter((r) => net.predict(pairFeat(E(r.query), E(r.positive), D), 1)[0] > net.predict(pairFeat(E(r.query), E(r.negative), D), 1)[0]).length / ho.length;
    baseAcc = ho.filter((r) => dot(E(r.query), E(r.positive)) > dot(E(r.query), E(r.negative))).length / ho.length; baseKind = "zero-shot cosine(query, positive) > cosine(query, negative)";
  } else {
    const li = new Map(labels.map((l, i) => [l, i])); X = new Float32Array(tr.length * D); Y = new Int32Array(tr.length);
    tr.forEach((r, i) => { X.set(E(r.text), i * D); Y[i] = li.get(r.label); });
    net = new Net(task === "router" ? [D, 64, labels.length] : [D, labels.length], "softmax", 3);
    const K = labels.length; heldacc = () => ho.filter((r) => argmax(net.predict(E(r.text), 1), 0, K) === li.get(r.label)).length / ho.length;
    const cnt = new Array(K).fill(0); for (const y of Y) cnt[y]++; const maj = cnt.indexOf(Math.max(...cnt)); baseAcc = ho.filter((r) => li.get(r.label) === maj).length / ho.length; baseKind = "majority class";
  }
  const d = X.length / Y.length, n = Y.length, metrics = [], ord = Int32Array.from({ length: n }, (_, i) => i), r2 = mulberry((seed || 7) + 1);
  for (let e = 1; e <= epochs; e++) {
    for (let i = n - 1; i > 0; i--) { const j = Math.floor(r2() * (i + 1)); const t = ord[i]; ord[i] = ord[j]; ord[j] = t; }
    let tot = 0, acc = 0, nb = 0;
    for (let s = 0; s < n; s += bs) {
      if (cancelled.has(id)) { cancelled.delete(id); return; }
      const B = Math.min(bs, n - s), xb = new Float32Array(B * d), yb = new (Y instanceof Float32Array ? Float32Array : Int32Array)(B);
      for (let k = 0; k < B; k++) { xb.set(X.subarray(ord[s + k] * d, (ord[s + k] + 1) * d), k * d); yb[k] = Y[ord[s + k]]; }
      const [l, a] = net.step(xb, yb, B, lr); tot += l; acc += a; nb++;
      if (nb % 8 === 0) await tick();
    }
    const metric = { epoch: e, loss: +(tot / nb).toFixed(5), accuracy: +(acc / nb).toFixed(4), valAccuracy: +heldacc().toFixed(4) }; metrics.push(metric);
    out({ id, metric, progress: +(0.2 + 0.75 * e / epochs).toFixed(3) }); await tick();
  }
  out({ id, status: "Evaluating" });
  const heldOut = { accuracy: +heldacc().toFixed(4), baseline: +baseAcc.toFixed(4), baselineKind: baseKind, n: ho.length };
  out({ id, head: { kind: task, labels, embedder, dims: net.toJSON(), metrics, heldOut } });
}
onmessage = (ev) => {
  const m = ev.data || {};
  if (m.cmd === "cancel") cancelled.add(m.id);
  else if (m.cmd === "train") train(m).catch((e) => out({ id: m.id, error: String((e && e.message) || e) }));
};
