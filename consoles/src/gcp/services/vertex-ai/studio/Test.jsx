/* TEST: query playground. Retrieved chunks with per-stage scores, filters, cited answer, latency per stage. */
import { useState } from "react";
import { Alert, Box, Button, Chip, Stack, TextField, Typography } from "@mui/material";
import { provenance } from "../../../../common/ragstudio/engine.js";
import { fileOf } from "./EmbeddingMap.jsx";
import { Card, Tbl, n } from "./ui.jsx";

export const finalOf = (t) => (t?.results || []).filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank);
export const citedUris = (rag) => (rag.citations || []).flatMap((c) => (c.retrievedReferences || []).map((r) => r.location?.uri)).filter(Boolean);

export function Answer({ test }) {
  const { rag, prov } = test, cites = [...new Set(citedUris(rag).map(fileOf))];
  return (
    <Stack spacing={1}>
      {rag.error ? <Alert severity="error" data-testid="gen-error">Generation failed: {rag.error.code || "error"}: {rag.error.message} Retrieval and stage scores below are still valid.</Alert>
        : rag.guardrailAction === "INTERVENED" ? <Alert severity="warning" data-testid="guardrail">Blocked by safety filters: {rag.output.text}</Alert>
          : <Alert severity={rag.grounded === false ? "info" : "success"}><b>{rag.grounded === false ? "Refused or not grounded: " : "Generated answer: "}</b><span data-testid="rag-answer">{rag.output.text}</span></Alert>}
      {cites.length > 0 && <Typography variant="caption" data-testid="citations">Citations (groundingMetadata): {cites.join(", ")}</Typography>}
      {prov.length > 0 && !rag.error && <Typography variant="caption">{prov.filter((p) => p.grounded).length}/{prov.length} answer sentences grounded in retrieved chunks.</Typography>}
    </Stack>
  );
}

export default function Test({ be, design, opts, test, setTest, goPost }) {
  const [q, setQ] = useState(test?.query || "How often must HVAC filters be replaced?"), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const t0 = performance.now(), [trace, rag] = await Promise.all([be.trace(q, opts), be.rag(q, { ...opts, model: design.generate.model, citations: design.generate.citations }).catch((e) => ({ output: { text: "" }, citations: [], error: e }))]);
      const fin = finalOf(trace);
      setTest({ query: q, trace, rag, prov: provenance(rag.output?.text || "", fin.length ? fin : trace.results.slice(0, 3)), ms: performance.now() - t0 });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const stages = test ? Object.entries(test.trace.latencyMs || {}).filter(([k]) => k !== "total") : [], mx = Math.max(1, ...stages.map(([, v]) => v));
  return (
    <Stack spacing={2}>
      <Card title="Query playground" description={`Filters applied: ${opts.filter ? `${opts.filter.key} = ${opts.filter.value}` : "none"} | ${opts.searchType} top-${opts.numberOfResults}${opts.rerank ? ` -> rerank top-${opts.rerankTopN}` : ""} | grounding >= ${opts.threshold}`}>
        <Stack spacing={1.5}>
          <TextField size="small" fullWidth label="Question" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !busy && q && run()} />
          <Stack direction="row" spacing={1}><Button variant="contained" disabled={busy || !q} onClick={run} data-testid="run-query">{busy ? "Running..." : "Run query"}</Button>{test && <Button onClick={goPost}>Open query analysis</Button>}</Stack>
          {err && <Alert severity="error">{err.code || "Error"}: {err.message}</Alert>}
        </Stack>
      </Card>
      {test && <>
        <Card title="Answer"><Answer test={test} /></Card>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
          <Card title="Latency per stage" description={`Total ${n(test.trace.latencyMs?.total, 1)} ms`} sx={{ flex: 1 }} data-testid="latency">
            {stages.map(([k, v]) => <Stack key={k} direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}><Typography variant="caption" sx={{ width: 70 }}>{k}</Typography><Box sx={{ flex: 1, bgcolor: "action.hover", height: 10, borderRadius: 5 }}><Box sx={{ width: `${(v / mx) * 100}%`, bgcolor: "primary.main", height: 10, borderRadius: 5 }} /></Box><Typography variant="caption" sx={{ width: 60 }}>{n(v, 1)} ms</Typography></Stack>)}
          </Card>
          <Card title="Confidence" description={`Top-chunk score against grounding threshold ${opts.threshold}`} sx={{ flex: 1 }}><Typography variant="h4" data-testid="confidence">{n(test.trace.confidence, 2)}</Typography></Card>
        </Stack>
        <Card title={`Retrieved chunks (${test.trace.results.length})`} description="Every candidate with the score each stage gave it. Filtered rows were excluded before or after scoring, with the reason.">
          <Tbl data-testid="trace-table" rows={test.trace.results} rowKey={(r) => r.id} columns={[
            { id: "f", header: "Final", cell: (r) => (r.final_rank ? <b>#{r.final_rank}</b> : "-") }, { id: "u", header: "Source", cell: (r) => fileOf(r.uri) },
            { id: "v", header: "Dense", cell: (r) => `${n(r.vector_score)}${r.vector_rank ? ` (#${r.vector_rank})` : ""}` }, { id: "b", header: "BM25", cell: (r) => `${n(r.bm25_score, 2)}${r.bm25_rank ? ` (#${r.bm25_rank})` : ""}` },
            { id: "x", header: "Fused rank", cell: (r) => r.fused_rank ?? "-" }, { id: "r", header: "Rerank", cell: (r) => n(r.rerank_score) },
            { id: "t", header: "Chunk / filter", cell: (r) => (r.filtered_out_reason ? <Chip size="small" label={r.filtered_out_reason} /> : r.text.slice(0, 120)) }]} />
        </Card></>}
    </Stack>
  );
}
