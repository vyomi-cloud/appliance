/* POST-RAG visualisation: query on the map, score waterfall, provenance overlay, evaluation dashboard. */
import { useMemo } from "react";
import { METRIC_LABELS } from "../../../../common/ragstudio/engine.js";
import { projectQuery } from "../../../../common/ragstudio/project.js";
import EmbeddingMap, { PALETTE } from "./EmbeddingMap.jsx";
import { RunMetrics } from "./Validate.jsx";
import { Alert, Bars, Card, Stack } from "./ui.jsx";

const STAGES = [["vector", "Vector", "vector_score", "vector_rank"], ["bm25", "Keyword", "bm25_score", "bm25_rank"], ["fused", "Fused (RRF)", null, "fused_rank"], ["rerank", "Semantic ranker", "rerank_score", "rerank_rank"]];

/** Rows for the waterfall: each candidate's rank at every stage plus what happened to it. */
export function waterfallRows(trace) {
  const pool = trace.results.filter((r) => r.fused_rank), byRr = [...pool].filter((r) => r.rerank_score !== null && r.rerank_score !== undefined).sort((a, b) => b.rerank_score - a.rerank_score);
  const rr = new Map(byRr.map((r, i) => [r.id, i + 1])), reranked = byRr.length > 0;
  return trace.results.map((r) => {
    const rerank_rank = rr.get(r.id) || null;
    let fate;
    if (r.filtered_out_reason) fate = { kind: "filtered", text: "Filtered out by $filter" };
    else if (r.final_rank) fate = reranked && rerank_rank < r.fused_rank ? { kind: "promoted", text: `Promoted by semantic ranker (#${r.fused_rank} -> #${rerank_rank})` } : reranked && rerank_rank > r.fused_rank ? { kind: "demoted", text: `Kept, demoted by semantic ranker (#${r.fused_rank} -> #${rerank_rank})` } : { kind: "kept", text: `Kept at #${r.final_rank}` };
    else fate = { kind: "dropped", text: reranked ? "Dropped: below the rerank top-N" : "Dropped: below the result limit" };
    return { ...r, rerank_rank, fate };
  });
}
const FATE = { promoted: "#107c10", kept: "#0f6cbd", demoted: "#b7791f", dropped: "#d13212", filtered: "#8d99a8" };

function Waterfall({ trace }) {
  const rows = waterfallRows(trace), rh = 26, W = 880, cw = 118, x0 = 190;
  const mx = { vector_score: Math.max(0.0001, ...rows.map((r) => r.vector_score || 0)), bm25_score: Math.max(0.0001, ...rows.map((r) => r.bm25_score || 0)), rerank_score: Math.max(0.0001, ...rows.map((r) => r.rerank_score || 0)) };
  return (
    <svg viewBox={`0 0 ${W} ${rows.length * rh + 34}`} style={{ width: "100%" }} data-testid="waterfall" role="img" aria-label="score waterfall by stage">
      {STAGES.map(([k, label], i) => <text key={k} x={x0 + i * cw + cw / 2 - 8} y={14} fontSize="11" fontWeight="700" textAnchor="middle" fill="currentColor">{label}</text>)}
      <text x={x0 + 4 * cw + 6} y={14} fontSize="11" fontWeight="700" fill="currentColor">Fate</text>
      {rows.map((r, ri) => { const y = 26 + ri * rh;
        return <g key={r.id} data-testid="wf-row" data-fate={r.fate.kind}>
          <text x={0} y={y + 14} fontSize="11" fill="currentColor">{String(r.uri).split("/").pop().replace(/\.txt$/, "").slice(0, 28)}</text>
          {STAGES.map(([k, , sc, rk], i) => { const val = sc ? r[sc] : null, rank = r[rk], w = val ? (val / mx[sc]) * (cw - 52) : 0;
            return <g key={k}><rect x={x0 + i * cw} y={y + 5} width={Math.max(0, w)} height={13} fill={PALETTE[i]} opacity={0.85} rx={2} /><text x={x0 + i * cw + Math.max(w, 0) + 4} y={y + 15} fontSize="10" fill="currentColor">{rank ? `#${rank}` : "-"}</text></g>; })}
          <text x={x0 + 4 * cw + 6} y={y + 15} fontSize="11" fill={FATE[r.fate.kind]} fontWeight="600">{r.fate.text}</text></g>; })}
    </svg>
  );
}

export default function PostRag({ test, data, proj, runs, thr }) {
  const rows = useMemo(() => (test ? waterfallRows(test.trace) : []), [test]);
  const q = useMemo(() => (test && proj ? projectQuery(proj, test.trace.queryEmbedding, test.trace.results.filter((r) => !r.filtered_out_reason)) : null), [test, proj]);
  if (!test) return <Alert type="info" title="Run a query first">Post-RAG views plot the last query from the Test tab: the map, the stage waterfall and the answer provenance.</Alert>;
  const retrieved = test.trace.results.filter((r) => !r.filtered_out_reason), last = runs[0];
  return (
    <Stack gap={16}>
      <Card title="Query on the embedding map" description={`"${test.query}": the query (Q) in the same map as the corpus; retrieved chunks are ringed and linked, numbered by final rank (dashed = candidate dropped by the semantic ranker or top-N).`}>
        {data && proj && q ? <EmbeddingMap points={proj.points} chunks={data.chunks} colorBy="document" query={q} retrieved={retrieved} /> : <Alert type="info">The map needs the inspect API (chunk positions).</Alert>}
        {q && <div style={{ fontSize: 12 }}>Query placed by {q.method}.</div>}
      </Card>
      <Card title="Score waterfall" description="Rank at each stage (bar = that stage's score). Green = promoted by the semantic ranker, red = dropped, grey = filtered out.">
        <Waterfall trace={test.trace} />
        <div style={{ fontSize: 12 }} data-testid="wf-summary">{rows.filter((r) => r.fate.kind === "promoted").length} promoted, {rows.filter((r) => r.fate.kind === "dropped").length} dropped, {rows.filter((r) => r.fate.kind === "filtered").length} filtered</div>
      </Card>
      <Card title="Citation and provenance overlay" description="Each answer sentence linked to its best supporting source sentence; red = not grounded in any retrieved chunk.">
        <div data-testid="provenance">{test.prov.length === 0 ? "No answer text." : test.prov.map((p, i) => (
          <div key={i} data-testid={p.grounded ? "sent-grounded" : "sent-ungrounded"} style={{ borderLeft: `4px solid ${p.grounded ? "#107c10" : "#d13212"}`, padding: "4px 10px", marginBottom: 8, background: p.grounded ? "rgba(16,124,16,.06)" : "rgba(209,50,18,.08)" }}>
            <div><b>{p.text}</b> {!p.grounded && <span style={{ color: "#d13212" }}>(ungrounded, coverage {(p.cover * 100).toFixed(0)}%)</span>}</div>
            {p.span && <div style={{ fontSize: 12, opacity: 0.85 }}>&rarr; <code>{String(p.uri || "").split("/").pop()}</code> / {p.chunkId} ({(p.cover * 100).toFixed(0)}% overlap): &ldquo;{p.span}&rdquo;</div>}</div>))}</div>
      </Card>
      <Card title="Evaluation dashboard" description="Latest evaluation run from the Validate tab.">
        {last ? <Stack gap={10}><div style={{ fontSize: 12 }}>{last.label}, {last.rows.length} questions</div><div data-testid="eval-dashboard"><Bars data={Object.keys(METRIC_LABELS).map((k) => [METRIC_LABELS[k], last.aggregate[k]])} max={1} fmt={(x) => (x * 100).toFixed(0) + "%"} /></div><RunMetrics run={last} thr={thr} /></Stack> : "Run an evaluation in the Validate tab to fill this dashboard."}
      </Card>
    </Stack>
  );
}
