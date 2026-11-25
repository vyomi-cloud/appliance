/* 2-D projection of chunk embeddings for the map. umap-js (MIT, pure JS, runs in the browser/worker-free for <= ~1500 points).
 * Honest limits: above MAX_POINTS the map shows a deterministic sample; a backend-supplied `position` ([x,y]) is used as-is. */
import { UMAP } from "umap-js";
export const MAX_POINTS = 1500;
function rng(seed) { let s = seed >>> 0; return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296); }

export function projectChunks(chunks) {
  const sampled = chunks.length > MAX_POINTS, use = sampled ? chunks.filter((_, i) => i % Math.ceil(chunks.length / MAX_POINTS) === 0) : chunks;
  if (use.every((c) => Array.isArray(c.position))) return { points: use.map((c) => ({ id: c.id, x: c.position[0], y: c.position[1] })), sampled, project: null, method: "backend" };
  const n = use.length;
  if (n < 4) return { points: use.map((c, i) => ({ id: c.id, x: i, y: 0 })), sampled, project: null, method: "line" };
  const umap = new UMAP({ nComponents: 2, nNeighbors: Math.max(2, Math.min(12, n - 1)), minDist: 0.15, nEpochs: n > 600 ? 120 : 300, random: rng(7) });
  const emb = umap.fit(use.map((c) => c.embedding));
  const points = use.map((c, i) => ({ id: c.id, x: emb[i][0], y: emb[i][1] }));
  let project = null;
  try { project = (v) => { const r = umap.transform([v])[0]; return { x: r[0], y: r[1] }; }; } catch { /* old umap: fallback below */ }
  return { points, sampled, project, method: "umap" };
}
/** Query position: UMAP transform, else the score-weighted centroid of the retrieved chunks' positions. */
export function projectQuery(proj, queryEmbedding, retrieved) {
  try { if (proj.project && queryEmbedding) return { ...proj.project(queryEmbedding), method: "umap-transform" }; } catch { /* fall through */ }
  const pts = retrieved.map((r) => ({ p: proj.points.find((x) => x.id === r.id), w: Math.max(0.01, r.vector_score ?? 0.1) })).filter((x) => x.p);
  if (!pts.length) return null;
  const W = pts.reduce((a, x) => a + x.w, 0);
  return { x: pts.reduce((a, x) => a + x.p.x * x.w, 0) / W, y: pts.reduce((a, x) => a + x.p.y * x.w, 0) / W, method: "weighted-centroid" };
}
