/* TEST: query playground. Retrieved chunks with per-stage scores, filters, cited answer (chat on your data), latency per stage. */
import { useState } from "react";
import { Input } from "@fluentui/react-components";
import { provenance } from "../../../../common/ragstudio/engine.js";
import { Alert, Bars, Btn, Card, Grid, Label, Stack, Status, Tbl, Tile } from "./ui.jsx";

const n = (v, d = 3) => (v === null || v === undefined ? "-" : Number(v).toFixed(d));
export const finalOf = (t) => (t?.results || []).filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank);
const base = (u) => String(u || "").split("/").pop();

export function Answer({ test }) {
  const rag = test.rag;
  return (
    <Stack gap={8}>
      {rag.error && <Alert type="error" title={`Generation failed: ${rag.error.code || "error"}`} data-testid="gen-error">{rag.error.message} Retrieval and stage scores below are still valid.</Alert>}
      {!rag.error && (rag.guardrailAction === "INTERVENED" ? <Alert type="warning" title="Content filter intervened" data-testid="guardrail">{rag.output.text}</Alert>
        : <Alert type={rag.grounded === false ? "info" : "success"} title={rag.grounded === false ? "Refused: not grounded" : "Generated answer"}><span data-testid="rag-answer">{rag.output.text}</span></Alert>)}
      {(rag.citations || []).length > 0 && <div style={{ fontSize: 12 }} data-testid="citations">Citations: {[...new Set(rag.citations.map((c) => base(c.title || c.uri)))].join(", ")}</div>}
      {test.prov.length > 0 && rag.guardrailAction !== "INTERVENED" && <div style={{ fontSize: 12 }}>{test.prov.filter((p) => p.grounded).length}/{test.prov.length} answer sentences grounded in retrieved chunks.</div>}
    </Stack>
  );
}

export default function Test({ be, opts, test, setTest, goPost }) {
  const [q, setQ] = useState(test?.query || "How often must HVAC filters be replaced?"), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const t0 = performance.now(), [trace, rag] = await Promise.all([be.trace(q, opts), be.rag(q, opts).catch((e) => ({ output: { text: "" }, citations: [], error: e }))]);
      const fin = finalOf(trace), prov = provenance(rag.output?.text || "", fin.length ? fin : trace.results.slice(0, 3));
      setTest({ query: q, trace, rag, prov, ms: performance.now() - t0 });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const stages = test ? Object.entries(test.trace.latencyMs || {}).filter(([k]) => k !== "total") : [];
  return (
    <Stack gap={16}>
      <Card title="Query playground" description={`Filter: ${opts.filter ? `${opts.filter.key} = ${opts.filter.value}` : "none"} | ${opts.searchType} top-${opts.numberOfResults}${opts.rerank ? ` -> semantic ranker top-${opts.rerankTopN}` : ""} | grounding >= ${opts.threshold}`}>
        <Stack gap={10}><Label label="Question"><Input value={q} onChange={(_, d) => setQ(d.value)} onKeyDown={(e) => e.key === "Enter" && q && run()} aria-label="Question" /></Label>
          <Stack row><Btn primary disabled={busy || !q} onClick={run}>{busy ? "Running..." : "Run query"}</Btn>{test && <Btn onClick={goPost}>Open post-RAG view</Btn>}</Stack>
          {err && <Alert type="error" title={err.code || "Error"}>{err.message}</Alert>}</Stack>
      </Card>
      {test && <>
        <Card title="Answer"><Answer test={test} /></Card>
        <Grid cols={2}>
          <Card title="Latency per stage" description={`Total ${n(test.trace.latencyMs?.total, 1)} ms`}><div data-testid="latency">{stages.length ? <Bars data={stages} fmt={(x) => `${x} ms`} /> : <span style={{ opacity: 0.7 }}>Only the total is measured on this backend.</span>}</div></Card>
          <Card title="Confidence"><Tile id="confidence" label={`Top-chunk grounding score against threshold ${opts.threshold}`} value={n(test.trace.confidence, 2)} /></Card>
        </Grid>
        <Card title={`Retrieved chunks (${test.trace.results.length})`} description="Every candidate with the score each stage gave it. Filtered rows were excluded before scoring.">
          <Tbl testid="trace-table" items={test.trace.results} trackBy="id" columns={[
            { id: "f", header: "Final", width: 60, cell: (r) => (r.final_rank ? <b>#{r.final_rank}</b> : "-") }, { id: "u", header: "Source", cell: (r) => base(r.uri) },
            { id: "v", header: "Vector", cell: (r) => `${n(r.vector_score)}${r.vector_rank ? ` (#${r.vector_rank})` : ""}` }, { id: "b", header: "BM25", cell: (r) => `${n(r.bm25_score, 2)}${r.bm25_rank ? ` (#${r.bm25_rank})` : ""}` },
            { id: "x", header: "Fused rank", cell: (r) => r.fused_rank ?? "-" }, { id: "r", header: "Semantic ranker", cell: (r) => n(r.rerank_score) },
            { id: "t", header: "Chunk / filter", cell: (r) => (r.filtered_out_reason ? <Status type="stopped">{r.filtered_out_reason}</Status> : r.text.slice(0, 120)) }]} />
        </Card></>}
    </Stack>
  );
}
