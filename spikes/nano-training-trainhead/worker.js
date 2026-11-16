// Classic Web Worker. Everything trains/evals here (off the main thread). Commands: embed | train | reload.
const log = (...a) => postMessage({ __log: a.join(' ') });
const now = () => performance.now();
const EP = 10, BS = 32;
// ---------- OPFS helpers ----------
async function opfsWrite(name, data) { const d = await navigator.storage.getDirectory(); const f = await d.getFileHandle(name, { create: true }); const w = await f.createWritable(); await w.write(data); await w.close(); }
async function opfsRead(name) { const d = await navigator.storage.getDirectory(); const f = await d.getFileHandle(name); return await (await f.getFile()).arrayBuffer(); }
const b64 = (u8) => { let s = ''; for (let i = 0; i < u8.length; i += 8192) s += String.fromCharCode.apply(null, u8.subarray(i, i + 8192)); return btoa(s); };
const unb64 = (s) => { const t = atob(s), u = new Uint8Array(t.length); for (let i = 0; i < t.length; i++) u[i] = t.charCodeAt(i); return u; };
// ---------- data ----------
const CLASSES = ['billing', 'tech_support', 'account_access', 'shipping', 'cancellation'];
async function fetchJsonl(u) { return (await (await fetch(u)).text()).trim().split('\n').map(JSON.parse); }
async function embed() {
  const t0 = now();
  const train = await fetchJsonl('data/train.jsonl'), test = await fetchJsonl('data/test.jsonl'), docs = await (await fetch('data/docs.json')).json();
  const labelNames = CLASSES.map((c) => c.replace('_', ' '));
  const docTexts = []; CLASSES.forEach((c) => docs[c].forEach((t) => docTexts.push(t)));
  const texts = [...train.map((r) => r.text), ...test.map((r) => r.text), ...labelNames, ...docTexts];
  const tf = await import('https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2');
  tf.env.allowLocalModels = false; tf.env.backends.onnx.wasm.numThreads = 1;
  const t1 = now();
  const pipe = await tf.pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', { quantized: true });
  const t2 = now();
  const D = 384, out = new Float32Array(texts.length * D);
  for (let i = 0; i < texts.length; i += 64) { const o = await pipe(texts.slice(i, i + 64), { pooling: 'mean', normalize: true }); out.set(o.data, i * D); }
  const t3 = now();
  const meta = { n_train: train.length, n_test: test.length, D, ytrain: train.map((r) => CLASSES.indexOf(r.label)), ytest: test.map((r) => CLASSES.indexOf(r.label)) };
  await opfsWrite('emb.bin', out.buffer); await opfsWrite('emb.json', JSON.stringify(meta));
  return { import_ms: t1 - t0, model_load_ms: t2 - t1, embed_ms: t3 - t2, n_texts: texts.length, per_text_ms: (t3 - t2) / texts.length, emb_bytes: out.byteLength };
}
async function loadData() {
  const meta = JSON.parse(new TextDecoder().decode(await opfsRead('emb.json'))), all = new Float32Array(await opfsRead('emb.bin')), D = meta.D;
  const nt = meta.n_train, ne = meta.n_test;
  const Xtr = all.subarray(0, nt * D), Xte = all.subarray(nt * D, (nt + ne) * D);
  const lab = all.subarray((nt + ne) * D, (nt + ne + 5) * D), docs = all.subarray((nt + ne + 5) * D, (nt + ne + 15) * D);
  return { D, nt, ne, Xtr, Xte, lab, docs, ytr: Int32Array.from(meta.ytrain), yte: Int32Array.from(meta.ytest) };
}
// pair features for reranker: [q*d, |q-d|]. Train positives/negatives use doc index 0 of each class; test candidates use doc index 1 (held out).
function pairFeat(q, d, D, out, o) { for (let i = 0; i < D; i++) { out[o + i] = q[i] * d[i]; out[o + D + i] = Math.abs(q[i] - d[i]); } }
function buildPairs(S, seed) {
  const { D, nt, Xtr, ytr, docs } = S; let s = seed; const rnd = () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296;
  const X = new Float32Array(nt * 2 * 2 * D), y = new Float32Array(nt * 2);
  for (let i = 0; i < nt; i++) {
    const q = Xtr.subarray(i * D, (i + 1) * D); let nc = Math.floor(rnd() * 4); if (nc >= ytr[i]) nc++;
    pairFeat(q, docs.subarray((ytr[i] * 2) * D, (ytr[i] * 2 + 1) * D), D, X, (2 * i) * 2 * D); y[2 * i] = 1;
    pairFeat(q, docs.subarray((nc * 2) * D, (nc * 2 + 1) * D), D, X, (2 * i + 1) * 2 * D); y[2 * i + 1] = 0;
  }
  return { X, y, n: nt * 2, d: 2 * D };
}
function testPairs(S) { // for each test query, 5 candidates (held-out doc index 1 per class)
  const { D, ne, Xte, docs } = S, X = new Float32Array(ne * 5 * 2 * D);
  for (let i = 0; i < ne; i++) for (let c = 0; c < 5; c++) pairFeat(Xte.subarray(i * D, (i + 1) * D), docs.subarray((c * 2 + 1) * D, (c * 2 + 2) * D), D, X, (i * 5 + c) * 2 * D);
  return X;
}
const argmax = (a, o, n) => { let b = 0; for (let i = 1; i < n; i++) if (a[o + i] > a[o + b]) b = i; return b; };
function baselines(S) {
  const { D, ne, Xte, lab, yte, ytr } = S; const cnt = [0, 0, 0, 0, 0]; ytr.forEach((y) => cnt[y]++); const maj = cnt.indexOf(Math.max(...cnt));
  let m = 0, z = 0, rz = 0;
  for (let i = 0; i < ne; i++) {
    if (yte[i] === maj) m++;
    let best = -2, bc = 0; for (let c = 0; c < 5; c++) { let s = 0; for (let k = 0; k < D; k++) s += Xte[i * D + k] * lab[c * D + k]; if (s > best) { best = s; bc = c; } }
    if (bc === yte[i]) z++;
  }
  return { majority_acc: m / ne, zero_shot_cosine_acc: z / ne };
}
// ---------- candidate A: hand-rolled typed-array JS ----------
function mulberry(a) { return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
class Net {
  constructor(dims, outAct, seed = 1) { this.dims = dims; this.outAct = outAct; const r = mulberry(seed), g = () => Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r());
    this.W = []; this.b = []; for (let l = 0; l < dims.length - 1; l++) { const w = new Float32Array(dims[l] * dims[l + 1]); const sc = Math.sqrt(2 / dims[l]); for (let i = 0; i < w.length; i++) w[i] = g() * sc * (l === dims.length - 2 ? 0.5 : 1); this.W.push(w); this.b.push(new Float32Array(dims[l + 1])); }
    this.m = this.W.concat(this.b).map((a) => new Float32Array(a.length)); this.v = this.W.concat(this.b).map((a) => new Float32Array(a.length)); this.t = 0; }
  forward(x, B) { const acts = [x]; let a = x; const L = this.dims.length - 1;
    for (let l = 0; l < L; l++) { const di = this.dims[l], dout = this.dims[l + 1], W = this.W[l], bb = this.b[l], z = new Float32Array(B * dout);
      for (let n = 0; n < B; n++) { const zo = n * dout; for (let j = 0; j < dout; j++) z[zo + j] = bb[j]; for (let i = 0; i < di; i++) { const xv = a[n * di + i]; if (xv === 0) continue; const wo = i * dout; for (let j = 0; j < dout; j++) z[zo + j] += xv * W[wo + j]; } }
      if (l < L - 1) { for (let i = 0; i < z.length; i++) if (z[i] < 0) z[i] = 0; }
      else if (this.outAct === 'softmax') { for (let n = 0; n < B; n++) { let mx = -1e9; for (let j = 0; j < dout; j++) mx = Math.max(mx, z[n * dout + j]); let s = 0; for (let j = 0; j < dout; j++) { z[n * dout + j] = Math.exp(z[n * dout + j] - mx); s += z[n * dout + j]; } for (let j = 0; j < dout; j++) z[n * dout + j] /= s; } }
      else for (let i = 0; i < z.length; i++) z[i] = 1 / (1 + Math.exp(-z[i]));
      acts.push(z); a = z; }
    return acts; }
  step(x, y, B, lr) { const acts = this.forward(x, B), L = this.dims.length - 1, out = acts[L], dout = this.dims[L]; let loss = 0;
    let dz = new Float32Array(B * dout);
    if (this.outAct === 'softmax') for (let n = 0; n < B; n++) { for (let j = 0; j < dout; j++) dz[n * dout + j] = (out[n * dout + j] - (y[n] === j ? 1 : 0)) / B; loss -= Math.log(out[n * dout + y[n]] + 1e-9) / B; }
    else for (let n = 0; n < B; n++) { const p = out[n]; dz[n] = (p - y[n]) / B; loss -= (y[n] * Math.log(p + 1e-9) + (1 - y[n]) * Math.log(1 - p + 1e-9)) / B; }
    const gW = [], gb = [];
    for (let l = L - 1; l >= 0; l--) { const di = this.dims[l], dO = this.dims[l + 1], a = acts[l], W = this.W[l], gw = new Float32Array(di * dO), g0 = new Float32Array(dO);
      for (let n = 0; n < B; n++) { for (let j = 0; j < dO; j++) g0[j] += dz[n * dO + j]; for (let i = 0; i < di; i++) { const av = a[n * di + i]; if (av === 0) continue; for (let j = 0; j < dO; j++) gw[i * dO + j] += av * dz[n * dO + j]; } }
      gW[l] = gw; gb[l] = g0;
      if (l > 0) { const nd = new Float32Array(B * di); for (let n = 0; n < B; n++) for (let i = 0; i < di; i++) { if (a[n * di + i] <= 0) continue; let s = 0; for (let j = 0; j < dO; j++) s += dz[n * dO + j] * W[i * dO + j]; nd[n * di + i] = s; } dz = nd; } }
    this.t++; const b1 = 0.9, b2 = 0.999, c1 = 1 - Math.pow(b1, this.t), c2 = 1 - Math.pow(b2, this.t); const P = this.W.concat(this.b), G = gW.concat(gb);
    for (let k = 0; k < P.length; k++) { const p = P[k], g = G[k], m = this.m[k], v = this.v[k]; for (let i = 0; i < p.length; i++) { m[i] = b1 * m[i] + (1 - b1) * g[i]; v[i] = b2 * v[i] + (1 - b2) * g[i] * g[i]; p[i] -= lr * (m[i] / c1) / (Math.sqrt(v[i] / c2) + 1e-8); } }
    return loss; }
  fit(X, Y, n, d, epochs, bs, lr, seed = 3) { const r = mulberry(seed), idx = Int32Array.from({ length: n }, (_, i) => i); const losses = [];
    for (let e = 0; e < epochs; e++) { for (let i = n - 1; i > 0; i--) { const j = Math.floor(r() * (i + 1)); const t = idx[i]; idx[i] = idx[j]; idx[j] = t; } let tot = 0, nb = 0;
      for (let s = 0; s < n; s += bs) { const B = Math.min(bs, n - s), xb = new Float32Array(B * d), yb = new (Y instanceof Float32Array ? Float32Array : Int32Array)(B); for (let k = 0; k < B; k++) { xb.set(X.subarray(idx[s + k] * d, (idx[s + k] + 1) * d), k * d); yb[k] = Y[idx[s + k]]; } tot += this.step(xb, yb, B, lr); nb++; }
      losses.push(tot / nb); }
    return losses; }
  predict(X, n) { const out = []; for (let s = 0; s < n; s += 256) { const B = Math.min(256, n - s); const o = this.forward(X.subarray(s * this.dims[0], (s + B) * this.dims[0]), B).pop(); for (let k = 0; k < B; k++) out.push(...o.subarray(k * this.dims[this.dims.length - 1], (k + 1) * this.dims[this.dims.length - 1])); } return Float32Array.from(out); }
  toJSON() { return { dims: this.dims, outAct: this.outAct, W: this.W.map((w) => b64(new Uint8Array(w.buffer))), b: this.b.map((w) => b64(new Uint8Array(w.buffer))) }; }
  static from(j) { const n = new Net(j.dims, j.outAct); n.W = j.W.map((s) => new Float32Array(unb64(s).buffer)); n.b = j.b.map((s) => new Float32Array(unb64(s).buffer)); return n; }
}
function accOf(P, y, k, n) { let c = 0; for (let i = 0; i < n; i++) if (argmax(P, i * k, k) === y[i]) c++; return c / n; }
function rerankAcc(scores, yte, ne) { let c = 0; for (let i = 0; i < ne; i++) if (argmax(scores, i * 5, 5) === yte[i]) c++; return c / ne; }
const LR = { logreg: 0.01, mlp: 0.003, rerank: 0.003 };
async function jsTrain(S) {
  const res = { train_ms: {}, acc: {}, loss_first_last: {} }; const nets = {}; const TP = testPairs(S), PP = buildPairs(S, 11);
  let t = now(); nets.logreg = new Net([S.D, 5], 'softmax'); let l = nets.logreg.fit(S.Xtr, S.ytr, S.nt, S.D, EP, BS, LR.logreg); res.train_ms.logreg = now() - t; res.loss_first_last.logreg = [l[0], l[EP - 1]];
  t = now(); nets.mlp = new Net([S.D, 64, 5], 'softmax'); l = nets.mlp.fit(S.Xtr, S.ytr, S.nt, S.D, EP, BS, LR.mlp); res.train_ms.mlp = now() - t; res.loss_first_last.mlp = [l[0], l[EP - 1]];
  t = now(); nets.rerank = new Net([PP.d, 1], 'sigmoid'); l = nets.rerank.fit(PP.X, PP.y, PP.n, PP.d, EP, BS, LR.rerank); res.train_ms.rerank = now() - t; res.loss_first_last.rerank = [l[0], l[EP - 1]];
  evalJs(nets, S, TP, res); res.total_train_ms = res.train_ms.logreg + res.train_ms.mlp + res.train_ms.rerank;
  const ck = JSON.stringify({ logreg: nets.logreg.toJSON(), mlp: nets.mlp.toJSON(), rerank: nets.rerank.toJSON() }); await opfsWrite('ckpt_js.json', ck); res.ckpt_bytes = ck.length; return res;
}
function evalJs(nets, S, TP, res) { res.acc.logreg = accOf(nets.logreg.predict(S.Xte, S.ne), S.yte, 5, S.ne); res.acc.mlp = accOf(nets.mlp.predict(S.Xte, S.ne), S.yte, 5, S.ne); res.acc.rerank_top1 = rerankAcc(nets.rerank.predict(TP, S.ne * 5), S.yte, S.ne); }
async function jsReload(S) { const t = now(); const j = JSON.parse(new TextDecoder().decode(await opfsRead('ckpt_js.json'))); const nets = { logreg: Net.from(j.logreg), mlp: Net.from(j.mlp), rerank: Net.from(j.rerank) }; const res = { acc: {} }; evalJs(nets, S, testPairs(S), res); res.reload_ms = now() - t; return res; }
// ---------- candidate B: TensorFlow.js (wasm or cpu backend) ----------
let TF = null;
async function tfLoad(backend) {
  const t = now(); importScripts('https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js');
  if (backend === 'wasm') { importScripts('https://cdn.jsdelivr.net/npm/@tensorflow/tfjs-backend-wasm@4.22.0/dist/tf-backend-wasm.min.js'); tf.wasm.setWasmPaths('https://cdn.jsdelivr.net/npm/@tensorflow/tfjs-backend-wasm@4.22.0/dist/'); }
  await tf.setBackend(backend); await tf.ready(); TF = tf; return now() - t;
}
function tfModel(kind, d) { const m = tf.sequential(); if (kind === 'logreg') m.add(tf.layers.dense({ units: 5, activation: 'softmax', inputShape: [d] })); else if (kind === 'mlp') { m.add(tf.layers.dense({ units: 64, activation: 'relu', inputShape: [d] })); m.add(tf.layers.dense({ units: 5, activation: 'softmax' })); } else m.add(tf.layers.dense({ units: 1, activation: 'sigmoid', inputShape: [d] }));
  m.compile({ optimizer: tf.train.adam(LR[kind]), loss: kind === 'rerank' ? 'binaryCrossentropy' : 'categoricalCrossentropy' }); return m; }
async function tfSave(kind, m) { let art; await m.save(tf.io.withSaveHandler(async (a) => { art = a; return { modelArtifactsInfo: { dateSaved: new Date(), modelTopologyType: 'JSON' } }; })); const j = { modelTopology: art.modelTopology, weightSpecs: art.weightSpecs, weightData: b64(new Uint8Array(art.weightData)) }; const s = JSON.stringify(j); await opfsWrite(`ckpt_tf_${kind}.json`, s); return s.length; }
async function tfRestore(kind) { const j = JSON.parse(new TextDecoder().decode(await opfsRead(`ckpt_tf_${kind}.json`))); return await tf.loadLayersModel(tf.io.fromMemory({ modelTopology: j.modelTopology, weightSpecs: j.weightSpecs, weightData: unb64(j.weightData).buffer })); }
const tfPred = (m, X, n, d) => tf.tidy(() => Float32Array.from(m.predict(tf.tensor2d(X, [n, d])).dataSync()));
async function tfTrain(S, backend) {
  const res = { train_ms: {}, acc: {}, loss_first_last: {}, ckpt_bytes: 0 }; res.lib_load_ms = await tfLoad(backend); res.backend = tf.getBackend();
  const TP = testPairs(S), PP = buildPairs(S, 11), oh = tf.oneHot(tf.tensor1d(Array.from(S.ytr), 'int32'), 5);
  for (const kind of ['logreg', 'mlp', 'rerank']) { const m = tfModel(kind, kind === 'rerank' ? PP.d : S.D); const t = now();
    const X = kind === 'rerank' ? tf.tensor2d(PP.X, [PP.n, PP.d]) : tf.tensor2d(S.Xtr, [S.nt, S.D]); const Y = kind === 'rerank' ? tf.tensor2d(PP.y, [PP.n, 1]) : oh;
    const h = await m.fit(X, Y, { epochs: EP, batchSize: BS, shuffle: true, verbose: 0 }); res.train_ms[kind] = now() - t; res.loss_first_last[kind] = [h.history.loss[0], h.history.loss[EP - 1]];
    if (kind === 'rerank') res.acc.rerank_top1 = rerankAcc(tfPred(m, TP, S.ne * 5, PP.d), S.yte, S.ne); else res.acc[kind] = accOf(tfPred(m, S.Xte, S.ne, S.D), S.yte, 5, S.ne);
    res.ckpt_bytes += await tfSave(kind, m); X.dispose(); if (kind !== 'rerank') {} m.dispose(); }
  res.total_train_ms = res.train_ms.logreg + res.train_ms.mlp + res.train_ms.rerank; return res;
}
async function tfReload(S, backend) { const res = { acc: {} }; const t0 = now(); await tfLoad(backend); const TP = testPairs(S);
  for (const kind of ['logreg', 'mlp', 'rerank']) { const m = await tfRestore(kind); if (kind === 'rerank') res.acc.rerank_top1 = rerankAcc(tfPred(m, TP, S.ne * 5, 2 * S.D), S.yte, S.ne); else res.acc[kind] = accOf(tfPred(m, S.Xte, S.ne, S.D), S.yte, 5, S.ne); }
  res.reload_ms = now() - t0; return res; }
// ---------- candidate C: scikit-learn in Pyodide ----------
let PY = null;
async function pyLoad() { const t = now(); importScripts('https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js'); PY = await loadPyodide(); const t1 = now(); await PY.loadPackage(['numpy', 'scikit-learn']); return { pyodide_boot_ms: t1 - t, packages_ms: now() - t1 }; }
async function pySetup(S) {
  PY.globals.set('emb_buf', new Uint8Array(await opfsRead('emb.bin'))); PY.globals.set('nt', S.nt); PY.globals.set('ne', S.ne); PY.globals.set('ytr_js', Array.from(S.ytr)); PY.globals.set('yte_js', Array.from(S.yte));
  await PY.runPythonAsync(`
import numpy as np, time, pickle
nt=int(nt); ne=int(ne); D=384
E=np.frombuffer(emb_buf.to_py(), dtype=np.float32).reshape(-1,D)
Xtr,Xte,LAB,DOCS=E[:nt],E[nt:nt+ne],E[nt+ne:nt+ne+5],E[nt+ne+5:nt+ne+15]
ytr=np.array(ytr_js.to_py()); yte=np.array(yte_js.to_py())
def pairfeat(q,d): return np.concatenate([q*d, np.abs(q-d)],axis=-1)
def build_pairs(seed=11):
    r=np.random.RandomState(seed); X=[];y=[]
    for i in range(nt):
        nc=r.randint(0,4); nc = nc+1 if nc>=ytr[i] else nc
        X.append(pairfeat(Xtr[i],DOCS[ytr[i]*2])); y.append(1); X.append(pairfeat(Xtr[i],DOCS[nc*2])); y.append(0)
    return np.array(X,dtype=np.float32), np.array(y)
def test_pairs():
    return np.array([[pairfeat(Xte[i],DOCS[c*2+1]) for c in range(5)] for i in range(ne)],dtype=np.float32)
def evaluate(m):
    TP=test_pairs()
    return {'logreg':float((m['logreg'].predict(Xte)==yte).mean()),'mlp':float((m['mlp'].predict(Xte)==yte).mean()),
            'rerank_top1':float((m['rerank'].decision_function(TP.reshape(-1,TP.shape[-1])).reshape(ne,5).argmax(1)==yte).mean())}
`);
}
async function pyTrain(S) {
  const res = await pyLoad(); await pySetup(S);
  const out = await PY.runPythonAsync(`
import warnings; warnings.filterwarnings('ignore')
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
T={}
t=time.perf_counter(); lr=LogisticRegression(max_iter=10).fit(Xtr,ytr); T['logreg']=(time.perf_counter()-t)*1000
t=time.perf_counter(); mlp=MLPClassifier(hidden_layer_sizes=(64,),solver='adam',batch_size=32,max_iter=10,learning_rate_init=0.003,random_state=3).fit(Xtr,ytr); T['mlp']=(time.perf_counter()-t)*1000
PX,Py=build_pairs(); t=time.perf_counter(); rr=LogisticRegression(max_iter=10).fit(PX,Py); T['rerank']=(time.perf_counter()-t)*1000
M={'logreg':lr,'mlp':mlp,'rerank':rr}
import json
blob=pickle.dumps(M)
json.dumps({'train_ms':T,'acc':evaluate(M),'ckpt_bytes':len(blob),'mlp_loss_first_last':[mlp.loss_curve_[0],mlp.loss_curve_[-1]]})
`);
  const o = JSON.parse(out); await opfsWrite('ckpt_sk.pkl', PY.runPython('pickle.dumps(M)').toJs());
  Object.assign(res, o); res.total_train_ms = o.train_ms.logreg + o.train_ms.mlp + o.train_ms.rerank; return res;
}
async function pyReload(S) { const res = await pyLoad(); await pySetup(S); PY.globals.set('ck', new Uint8Array(await opfsRead('ckpt_sk.pkl'))); const t = now();
  const out = await PY.runPythonAsync(`import json\nM=pickle.loads(ck.to_py().tobytes())\njson.dumps(evaluate(M))`); res.acc = JSON.parse(out); res.reload_ms = now() - t + res.pyodide_boot_ms + res.packages_ms; return res; }
// ---------- dispatch ----------
onmessage = async (e) => { const { cmd, cand } = e.data; try {
  if (cmd === 'embed') return postMessage({ ok: true, r: await embed() });
  const S = await loadData(); let r;
  if (cmd === 'baseline') r = baselines(S);
  else if (cmd === 'train') r = cand === 'js' ? await jsTrain(S) : cand === 'tfjs-wasm' ? await tfTrain(S, 'wasm') : cand === 'tfjs-cpu' ? await tfTrain(S, 'cpu') : await pyTrain(S);
  else if (cmd === 'reload') r = cand === 'js' ? await jsReload(S) : cand === 'tfjs-wasm' ? await tfReload(S, 'wasm') : cand === 'tfjs-cpu' ? await tfReload(S, 'cpu') : await pyReload(S);
  postMessage({ ok: true, r }); } catch (err) { postMessage({ ok: false, err: String(err && err.stack || err) }); } };
