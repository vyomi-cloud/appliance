/* Azure copy of aws/.../studio/EmbeddingMap.jsx (framework-free SVG). Embedding map: SVG scatter of the UMAP projection. Colour by any chunk attribute; optional query point, retrieved-chunk highlight and links. */
import { useMemo, useState } from "react";

export const PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#7f7f7f", "#1b9e77", "#d95f02"];
const W = 640, H = 420, P = 28;
export const colorKey = (c, by) => (by === "document" ? c.uri.split("/").pop().replace(/\.txt$/, "") : by === "language" ? c.lang || "en" : by === "pii" ? (c.pii?.length ? "has PII" : "clean") : String(c.metadata?.[by] ?? "(none)"));

export default function EmbeddingMap({ points, chunks, colorBy = "document", query = null, retrieved = [], height = H, onPick }) {
  const [hover, setHover] = useState(null);
  const byId = useMemo(() => new Map(chunks.map((c) => [c.id, c])), [chunks]);
  const keys = useMemo(() => [...new Set(points.map((p) => colorKey(byId.get(p.id) || { uri: "", metadata: {} }, colorBy)))].sort(), [points, byId, colorBy]);
  const sc = useMemo(() => {
    const xs = points.map((p) => p.x).concat(query ? [query.x] : []), ys = points.map((p) => p.y).concat(query ? [query.y] : []);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    return { x: (v) => P + ((v - x0) / (x1 - x0 || 1)) * (W - 2 * P), y: (v) => H - P - ((v - y0) / (y1 - y0 || 1)) * (H - 2 * P) };
  }, [points, query]);
  const hl = new Map(retrieved.map((r) => [r.id, r]));
  const hc = hover && byId.get(hover);
  return (
    <div data-testid="embedding-map">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height, background: "var(--colorNeutralBackground1, #fff)", border: "1px solid var(--colorNeutralStroke2, #d5dbdb)", borderRadius: 4 }} role="img" aria-label="2-D embedding map of chunks">
        {query && retrieved.map((r) => { const p = points.find((x) => x.id === r.id); return p ? <line key={"l" + r.id} data-testid="map-link" x1={sc.x(query.x)} y1={sc.y(query.y)} x2={sc.x(p.x)} y2={sc.y(p.y)} stroke="#d13212" strokeWidth={r.final_rank ? 1.6 : 0.6} strokeDasharray={r.final_rank ? "" : "3 3"} opacity={r.final_rank ? 0.8 : 0.4} /> : null; })}
        {points.map((p) => { const c = byId.get(p.id), h = hl.get(p.id), col = PALETTE[keys.indexOf(colorKey(c || { uri: "", metadata: {} }, colorBy)) % PALETTE.length];
          return <g key={p.id} onMouseEnter={() => setHover(p.id)} onMouseLeave={() => setHover(null)} onClick={() => onPick && onPick(p.id)} style={{ cursor: "pointer" }}>
            <circle data-testid={h?.final_rank ? "map-hit" : "map-pt"} cx={sc.x(p.x)} cy={sc.y(p.y)} r={h?.final_rank ? 8 : h ? 6 : 4.5} fill={col} stroke={h ? "#d13212" : "#fff"} strokeWidth={h ? 2.4 : 0.8} opacity={query && !h ? 0.35 : 0.95} />
            {h?.final_rank ? <text x={sc.x(p.x)} y={sc.y(p.y) + 3.5} textAnchor="middle" fontSize="9" fontWeight="700" fill="#fff" style={{ pointerEvents: "none" }}>{h.final_rank}</text> : null}</g>; })}
        {query && <g data-testid="map-query"><circle cx={sc.x(query.x)} cy={sc.y(query.y)} r={9} fill="#fff" stroke="#d13212" strokeWidth={3} /><text x={sc.x(query.x)} y={sc.y(query.y) + 4} textAnchor="middle" fontSize="12" fontWeight="700" fill="#d13212">Q</text></g>}
      </svg>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 14px", marginTop: 6, fontSize: 12 }}>
        {keys.map((k, i) => <span key={k}><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 5, background: PALETTE[i % PALETTE.length], marginRight: 4 }} />{k}</span>)}
      </div>
      <div style={{ minHeight: 38, fontSize: 12, marginTop: 6 }} data-testid="map-hover">{hc ? <><b>{hc.uri.split("/").pop()}</b> · {hc.tokens} tokens · {hc.text.slice(0, 160)}...</> : <span style={{ opacity: 0.6 }}>Hover a point to read the chunk.</span>}</div>
    </div>
  );
}
