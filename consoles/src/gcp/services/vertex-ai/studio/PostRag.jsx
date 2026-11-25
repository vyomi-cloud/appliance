/* POST-RAG visualisation: query on the map, score waterfall, provenance overlay, evaluation dashboard. */
import { useMemo } from "react";
import { Alert, Box, Typography } from "@mui/material";
import { METRIC_LABELS } from "../../../../common/ragstudio/engine.js";
import { projectQuery } from "../../../../common/ragstudio/project.js";
import EmbeddingMap, { PALETTE, fileOf } from "./EmbeddingMap.jsx";
import { RunMetrics } from "./Validate.jsx";
import { Bars, Card } from "./ui.jsx";

const STAGES = [["vector", "Dense", "vector_score", "vector_rank"], ["bm25", "BM25", "bm25_score", "bm25_rank"], ["fused", "Fused", null, "fused_rank"], ["rerank", "Rerank", "rerank_score", "rerank_rank"]];
const FATE = { promoted: "#188038", kept: "#1a73e8", demoted: "#b06000", dropped: "#d93025", filtered: "#80868b" };

/** Rows for the waterfall: each candidate's rank at every stage plus what happened to it. */
export function waterfallRows(trace) {
  const pool = trace.results.filter((r) => r.fused_rank), byRr = pool.filter((r) => r.rerank_score !== null).sort((a, b) => b.rerank_score - a.rerank_score);
  const rr = new Map(byRr.map((r, i) => [r.id, i + 1])), reranked = byRr.length > 0;
  return trace.results.map((r) => {
    const rerank_rank = rr.get(r.id) || null;
    let fate;
    if (r.filtered_out_reason) fate = { kind: "filtered", text: `Filtered: ${r.filtered_out_reason}` };
    else if (r.final_rank) fate = reranked && rerank_rank < r.fused_rank ? { kind: "promoted", text: `Promoted by rerank (#${r.fused_rank} -> #${rerank_rank})` } : reranked && rerank_rank > r.fused_rank ? { kind: "demoted", text: `Kept, demoted by rerank (#${r.fused_rank} -> #${rerank_rank})` } : { kind: "kept", text: `Kept at #${r.final_rank}` };
    else fate = { kind: "dropped", text: reranked ? "Dropped: below the rerank top-N" : "Dropped: below the result limit" };
    return { ...r, rerank_rank, fate };
  });
}

function Waterfall({ trace }) {
  const rows = waterfallRows(trace), rh = 26, W = 880, cw = 118, x0 = 190;
  const mx = { vector_score: Math.max(0.0001, ...rows.map((r) => r.vector_score || 0)), bm25_score: Math.max(0.0001, ...rows.map((r) => r.bm25_score || 0)), rerank_score: Math.max(0.0001, ...rows.map((r) => r.rerank_score || 0)) };
  return (
    <svg viewBox={`0 0 ${W} ${rows.length * rh + 34}`} style={{ width: "100%" }} data-testid="waterfall" role="img" aria-label="score waterfall by stage">
      {STAGES.map(([k, label], i) => <text key={k} x={x0 + i * cw + cw / 2 - 8} y={14} fontSize="11" fontWeight="700" textAnchor="middle" fill="currentColor">{label}</text>)}
      <text x={x0 + 4 * cw + 6} y={14} fontSize="11" fontWeight="700" fill="currentColor">Fate</text>
      {rows.map((r, ri) => { const y = 26 + ri * rh;
        return <g key={r.id} data-testid="wf-row" data-fate={r.fate.kind}>
          <text x={0} y={y + 14} fontSize="11" fill="currentColor">{fileOf(r.uri).slice(0, 28)}</text>
          {STAGES.map(([k, , sc, rk], i) => { const v = sc ? r[sc] : null, rank = r[rk], w = v ? (v / mx[sc]) * (cw - 52) : 0;
            return <g key={k}><rect x={x0 + i * cw} y={y + 5} width={Math.max(0, w)} height={13} fill={PALETTE[i]} opacity={0.85} rx={2} /><text x={x0 + i * cw + Math.max(w, 0) + 4} y={y + 15} fontSize="10" fill="currentColor">{rank ? `#${rank}` : "-"}</text></g>; })}
          <text x={x0 + 4 * cw + 6} y={y + 15} fontSize="11" fill={FATE[r.fate.kind]} fontWeight="600">{r.fate.text}</text></g>; })}
    </svg>
  );
}

export default function PostRag({ test, data, proj, runs, thr }) {
  const rows = useMemo(() => (test ? waterfallRows(test.trace) : []), [test]);
  const q = useMemo(() => (test && proj ? projectQuery(proj, test.trace.queryEmbedding, test.trace.results.filter((r) => !r.filtered_out_reason)) : null), [test, proj]);
  if (!test) return <Alert severity="info">Run a query first: query analysis plots the last query from the Test tab (the map, the stage waterfall and the answer provenance).</Alert>;
  const retrieved = test.trace.results.filter((r) => !r.filtered_out_reason), last = runs[0];
  return (
    <Box sx={{ display: "grid", gap: 2 }}>
      <Card title="Query on the embedding map" description={`"${test.query}": the query (Q) in the same map as the corpus; retrieved chunks are ringed and linked, numbered by final rank (dashed = dropped by rerank/top-N).`}>
        {data && proj && q ? <EmbeddingMap points={proj.points} chunks={data.chunks} colorBy="document" query={q} retrieved={retrieved} /> : <Alert severity="info">The map needs the inspect API (chunk positions).</Alert>}
        {q && <Typography variant="caption">Query projected by {q.method}.</Typography>}
      </Card>
      <Card title="Score waterfall" description="Rank at each stage (bar = that stage's score). Green = promoted by rerank, red = dropped, grey = filtered out.">
        <Waterfall trace={test.trace} />
        <Typography variant="caption" data-testid="wf-summary">{rows.filter((r) => r.fate.kind === "promoted").length} promoted, {rows.filter((r) => r.fate.kind === "dropped").length} dropped, {rows.filter((r) => r.fate.kind === "filtered").length} filtered</Typography>
      </Card>
      <Card title="Citation and provenance overlay" description="Each answer sentence linked to its best supporting source sentence; red = not grounded in any retrieved chunk.">
        <div data-testid="provenance">{test.prov.length === 0 ? <Typography variant="body2">No answer text.</Typography> : test.prov.map((p, i) => (
          <Box key={i} data-testid={p.grounded ? "sent-grounded" : "sent-ungrounded"} sx={{ borderLeft: `4px solid ${p.grounded ? "#188038" : "#d93025"}`, p: "4px 10px", mb: 1, bgcolor: p.grounded ? "rgba(24,128,56,.06)" : "rgba(217,48,37,.08)" }}>
            <div><b>{p.text}</b> {!p.grounded && <span style={{ color: "#d93025" }}>(ungrounded, coverage {(p.cover * 100).toFixed(0)}%)</span>}</div>
            {p.span && <Typography variant="caption" component="div">&rarr; <code>{fileOf(p.uri)}</code> / {p.chunkId} ({(p.cover * 100).toFixed(0)}% overlap): &ldquo;{p.span}&rdquo;</Typography>}</Box>))}</div>
      </Card>
      <Card title="Evaluation dashboard" description="Latest evaluation run from the Validate tab.">
        {last ? <Box data-testid="eval-dashboard"><Typography variant="caption">{last.label}, {last.rows.length} questions</Typography><Bars data={Object.fromEntries(Object.keys(METRIC_LABELS).map((k) => [METRIC_LABELS[k], Math.round(last.aggregate[k] * 100)]))} unit="%" /><RunMetrics run={last} thr={thr} /></Box> : <Typography variant="body2">Run an evaluation in Validate to fill this dashboard.</Typography>}
      </Card>
    </Box>
  );
}
