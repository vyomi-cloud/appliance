/* POST-RAG visualisation: query on the map, score waterfall, provenance overlay, evaluation dashboard. */
import { useMemo } from "react";
import Alert from "@cloudscape-design/components/alert";
import BarChart from "@cloudscape-design/components/bar-chart";
import Box from "@cloudscape-design/components/box";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import EmbeddingMap from "./EmbeddingMap.jsx";
import { RunMetrics } from "./Validate.jsx";
import { METRIC_LABELS } from "./engine.js";
import { projectQuery } from "./project.js";
import { PALETTE } from "./EmbeddingMap.jsx";

const STAGES = [["vector", "Vector", "vector_score", "vector_rank"], ["bm25", "BM25", "bm25_score", "bm25_rank"], ["fused", "Fused", null, "fused_rank"], ["rerank", "Rerank", "rerank_score", "rerank_rank"]];

/** Rows for the waterfall: each candidate's rank at every stage plus what happened to it. */
export function waterfallRows(trace) {
  const pool = trace.results.filter((r) => r.fused_rank), byRr = [...pool].filter((r) => r.rerank_score !== null).sort((a, b) => b.rerank_score - a.rerank_score);
  const rr = new Map(byRr.map((r, i) => [r.id, i + 1])), reranked = byRr.length > 0;
  return trace.results.map((r) => {
    const rerank_rank = rr.get(r.id) || null;
    let fate;
    if (r.filtered_out_reason) fate = { kind: "filtered", text: "Filtered out by metadata filter" };
    else if (r.final_rank) fate = reranked && rerank_rank < r.fused_rank ? { kind: "promoted", text: `Promoted by rerank (#${r.fused_rank} -> #${rerank_rank})` } : reranked && rerank_rank > r.fused_rank ? { kind: "demoted", text: `Kept, demoted by rerank (#${r.fused_rank} -> #${rerank_rank})` } : { kind: "kept", text: `Kept at #${r.final_rank}` };
    else fate = { kind: "dropped", text: reranked ? "Dropped: below the rerank top-N" : "Dropped: below the result limit" };
    return { ...r, rerank_rank, fate };
  });
}
const FATE = { promoted: "#037f0c", kept: "#0972d3", demoted: "#b7791f", dropped: "#d13212", filtered: "#8d99a8" };

function Waterfall({ trace }) {
  const rows = waterfallRows(trace), rh = 26, W = 880, cw = 118, x0 = 190;
  const mx = { vector_score: Math.max(0.0001, ...rows.map((r) => r.vector_score || 0)), bm25_score: Math.max(0.0001, ...rows.map((r) => r.bm25_score || 0)), rerank_score: Math.max(0.0001, ...rows.map((r) => r.rerank_score || 0)) };
  return (
    <svg viewBox={`0 0 ${W} ${rows.length * rh + 34}`} style={{ width: "100%" }} data-testid="waterfall" role="img" aria-label="score waterfall by stage">
      {STAGES.map(([k, label], i) => <text key={k} x={x0 + i * cw + cw / 2 - 8} y={14} fontSize="11" fontWeight="700" textAnchor="middle" fill="currentColor">{label}</text>)}
      <text x={x0 + 4 * cw + 6} y={14} fontSize="11" fontWeight="700" fill="currentColor">Fate</text>
      {rows.map((r, ri) => { const y = 26 + ri * rh;
        return <g key={r.id} data-testid="wf-row" data-fate={r.fate.kind}>
          <text x={0} y={y + 14} fontSize="11" fill="currentColor">{r.uri.split("/").pop().slice(0, 26)} · {r.id}</text>
          {STAGES.map(([k, , sc, rk], i) => { const v = sc ? r[sc] : null, rank = r[rk], w = v ? (v / mx[sc]) * (cw - 52) : 0;
            return <g key={k}><rect x={x0 + i * cw} y={y + 5} width={Math.max(0, w)} height={13} fill={PALETTE[i]} opacity={0.85} rx={2} /><text x={x0 + i * cw + Math.max(w, 0) + 4} y={y + 15} fontSize="10" fill="currentColor">{rank ? `#${rank}` : "-"}</text></g>; })}
          <text x={x0 + 4 * cw + 6} y={y + 15} fontSize="11" fill={FATE[r.fate.kind]} fontWeight="600">{r.fate.text}</text></g>; })}
    </svg>
  );
}

export default function PostRag({ test, data, proj, runs, thr }) {
  const rows = useMemo(() => (test ? waterfallRows(test.trace) : []), [test]);
  const q = useMemo(() => (test && proj && test.trace.queryEmbedding ? projectQuery(proj, test.trace.queryEmbedding, test.trace.results.filter((r) => !r.filtered_out_reason)) : null), [test, proj]);
  if (!test) return <Alert type="info" header="Run a query first">Post-RAG views plot the last query from the Test tab: the map, the stage waterfall and the answer provenance.</Alert>;
  const retrieved = test.trace.results.filter((r) => !r.filtered_out_reason);
  const last = runs[0];
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" description={`"${test.query}": the query (Q) in the same map as the corpus; the retrieved chunks are ringed and linked, numbered by final rank (dashed = candidate dropped by rerank/top-N).`}>Query on the embedding map</Header>}>
        {data && proj && q ? <EmbeddingMap points={proj.points} chunks={data.chunks} colorBy="document" query={q} retrieved={retrieved} /> : <Alert type="info">The map needs the inspect API (chunk embeddings and the query embedding).</Alert>}
        {q && <Box variant="small">Query projected by {q.method}.</Box>}
      </Container>
      <Container header={<Header variant="h2" description="Rank at each stage (bar = that stage's score). Green = promoted by rerank, red = dropped, grey = filtered out.">Score waterfall</Header>}>
        <Waterfall trace={test.trace} />
        <Box variant="small" data-testid="wf-summary">{rows.filter((r) => r.fate.kind === "promoted").length} promoted, {rows.filter((r) => r.fate.kind === "dropped").length} dropped, {rows.filter((r) => r.fate.kind === "filtered").length} filtered</Box>
      </Container>
      <Container header={<Header variant="h2" description="Each answer sentence linked to its best supporting source sentence; red = not grounded in any retrieved chunk.">Citation and provenance overlay</Header>}>
        <div data-testid="provenance">{test.prov.length === 0 ? <Box>No answer text.</Box> : test.prov.map((p, i) => (
          <div key={i} data-testid={p.grounded ? "sent-grounded" : "sent-ungrounded"} style={{ borderLeft: `4px solid ${p.grounded ? "#037f0c" : "#d13212"}`, padding: "4px 10px", marginBottom: 8, background: p.grounded ? "rgba(3,127,12,.06)" : "rgba(209,50,18,.08)" }}>
            <div><b>{p.text}</b> {!p.grounded && <span style={{ color: "#d13212" }}>(ungrounded, coverage {(p.cover * 100).toFixed(0)}%)</span>}</div>
            {p.span && <div style={{ fontSize: 12, opacity: 0.85 }}>&rarr; <code>{p.uri?.split("/").pop()}</code> / {p.chunkId} ({(p.cover * 100).toFixed(0)}% overlap): &ldquo;{p.span}&rdquo;</div>}</div>))}</div>
      </Container>
      <Container header={<Header variant="h2" description="Latest evaluation run from the Validate tab.">Evaluation dashboard</Header>}>
        {last ? <SpaceBetween size="m"><Box variant="small">{last.label}, {last.rows.length} questions</Box><div data-testid="eval-dashboard"><BarChart height={200} hideFilter xScaleType="categorical" yDomain={[0, 1]} ariaLabel="evaluation metrics" series={[{ title: "Score", type: "bar", data: Object.keys(METRIC_LABELS).map((k) => ({ x: METRIC_LABELS[k], y: last.aggregate[k] })) }, { title: "Threshold", type: "threshold", y: 0.5, valueFormatter: () => "per-metric" }].slice(0, 1)} /></div><RunMetrics run={last} thr={thr} /></SpaceBetween> : <Box color="text-status-inactive">Run an evaluation in the Validate tab to fill this dashboard.</Box>}
      </Container>
    </SpaceBetween>
  );
}
