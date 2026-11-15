/* TEST: query playground. Retrieved chunks with per-stage scores, filters, cited answer, latency per stage, guardrail result. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { provenance } from "./engine.js";

const n = (v, d = 3) => (v === null || v === undefined ? "-" : Number(v).toFixed(d));
export const finalOf = (t) => (t?.results || []).filter((r) => r.final_rank).sort((a, b) => a.final_rank - b.final_rank);
export function Answer({ test }) {
  const prov = test.prov;
  return (
    <SpaceBetween size="s">
      {test.rag.guardrailAction === "INTERVENED" ? <Alert type="warning" header="Guardrail intervened" data-testid="guardrail">{test.rag.guardrail?.input || "blocked"}: {test.rag.output.text}</Alert>
        : <Alert type={test.rag.grounded === false ? "info" : "success"} header={test.rag.grounded === false ? "Refused: not grounded" : "Generated answer"}><span data-testid="rag-answer">{test.rag.output.text}</span></Alert>}
      <Box variant="small" data-testid="guardrail-status">Guardrail: <StatusIndicator type={test.rag.guardrailAction === "INTERVENED" ? "warning" : "success"}>{test.rag.guardrailAction || "NONE"}</StatusIndicator></Box>
      {(test.rag.citations || []).length > 0 && <Box variant="small" data-testid="citations">Citations: {(test.rag.citations || []).flatMap((c) => c.retrievedReferences.map((r) => r.location?.s3Location?.uri?.split("/").pop())).filter((x, i, a) => a.indexOf(x) === i).join(", ")}</Box>}
      {prov.length > 0 && test.rag.guardrailAction !== "INTERVENED" && <Box variant="small">{prov.filter((p) => p.grounded).length}/{prov.length} answer sentences grounded in retrieved chunks.</Box>}
    </SpaceBetween>
  );
}

export default function Test({ be, design, opts, test, setTest, goPost }) {
  const [q, setQ] = useState(test?.query || "How often must HVAC filters be replaced?");
  const [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const t0 = performance.now(), [trace, rag] = await Promise.all([be.trace(q, opts), be.rag(q, opts)]);
      const fin = finalOf(trace), prov = provenance(rag.output?.text || "", fin.length ? fin : trace.results.slice(0, 3));
      setTest({ query: q, trace, rag, prov, ms: performance.now() - t0 });
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const stages = test ? Object.entries(test.trace.latencyMs || {}).filter(([k]) => k !== "total") : [];
  const mx = Math.max(1, ...stages.map(([, v]) => v));
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" description={`Filters applied: ${opts.filter ? `${opts.filter.key} = ${opts.filter.value}` : "none"} | ${opts.searchType} top-${opts.numberOfResults}${opts.rerank ? ` -> rerank top-${opts.rerankTopN}` : ""} | grounding >= ${opts.threshold}`}>Query playground</Header>}>
        <SpaceBetween size="s"><FormField label="Question"><Input value={q} onChange={({ detail }) => setQ(detail.value)} onKeyDown={({ detail }) => detail.key === "Enter" && run()} ariaLabel="Question" /></FormField>
          <SpaceBetween direction="horizontal" size="xs"><Button variant="primary" loading={busy} disabled={!q} onClick={run}>Run query</Button>{test && <Button onClick={goPost}>Open post-RAG view</Button>}</SpaceBetween>
          {err && <Alert type="error" header={err.code || "Error"}>{err.message}</Alert>}</SpaceBetween>
      </Container>
      {test && <>
        <Container header={<Header variant="h2">Answer</Header>}><Answer test={test} /></Container>
        <ColumnLayout columns={2}>
          <Container header={<Header variant="h2" description={`Total ${n(test.trace.latencyMs?.total, 1)} ms`}>Latency per stage</Header>}>
            <div data-testid="latency">{stages.map(([k, v]) => <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}><span style={{ width: 70 }}>{k}</span><div style={{ flex: 1, background: "#e9ebed", height: 10, borderRadius: 5 }}><div style={{ width: `${(v / mx) * 100}%`, background: "#0972d3", height: 10, borderRadius: 5 }} /></div><span style={{ width: 70, textAlign: "right" }}>{n(v, 1)} ms</span></div>)}{!stages.length && <Box>Backend reports total latency only.</Box>}</div>
          </Container>
          <Container header={<Header variant="h2">Confidence</Header>}><Box variant="h1" data-testid="confidence">{n(test.trace.confidence, 2)}</Box><Box variant="small">Top-chunk grounding score against threshold {opts.threshold}</Box></Container>
        </ColumnLayout>
        <Container header={<Header variant="h2" counter={`(${test.trace.results.length})`} description="Every candidate with the score each stage gave it. Filtered rows were excluded before scoring.">Retrieved chunks</Header>}>
          <Table variant="embedded" data-testid="trace-table" items={test.trace.results} trackBy="id" columnDefinitions={[
            { id: "f", header: "Final", width: 70, cell: (r) => (r.final_rank ? <b>#{r.final_rank}</b> : "-") }, { id: "u", header: "Source", cell: (r) => r.uri.split("/").pop() },
            { id: "v", header: "Vector", cell: (r) => `${n(r.vector_score)}${r.vector_rank ? ` (#${r.vector_rank})` : ""}` }, { id: "b", header: "BM25", cell: (r) => `${n(r.bm25_score, 2)}${r.bm25_rank ? ` (#${r.bm25_rank})` : ""}` },
            { id: "x", header: "Fused rank", cell: (r) => r.fused_rank ?? "-" }, { id: "r", header: "Rerank", cell: (r) => n(r.rerank_score) },
            { id: "t", header: "Chunk / filter", cell: (r) => (r.filtered_out_reason ? <StatusIndicator type="stopped">{r.filtered_out_reason}</StatusIndicator> : r.text.slice(0, 120)) }]} />
        </Container></>}
    </SpaceBetween>
  );
}
