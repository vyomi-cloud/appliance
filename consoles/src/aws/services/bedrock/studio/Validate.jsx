/* VALIDATE: static lint + golden-set evaluation (7 metrics, thresholds, run history, A/B). */
import { useMemo, useState } from "react";
import BarChart from "@cloudscape-design/components/bar-chart";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Textarea from "@cloudscape-design/components/textarea";
import { DEFAULT_THRESHOLDS, METRIC_LABELS, PRESETS, applyFix, compareRuns, lintDesign, verdicts } from "./engine.js";

const pct = (v) => (v * 100).toFixed(0) + "%";
const sevType = { error: "error", warning: "warning", info: "info" };

export function RunMetrics({ run, thr }) {
  const v = verdicts(run.aggregate, thr);
  return <Table variant="embedded" items={Object.keys(METRIC_LABELS).map((k) => ({ k, val: run.aggregate[k], pass: v[k], t: thr[k] }))} trackBy="k" columnDefinitions={[
    { id: "m", header: "Metric", cell: (r) => METRIC_LABELS[r.k] }, { id: "v", header: "Score", cell: (r) => <b data-testid={`metric-${r.k}`}>{pct(r.val)}</b> }, { id: "t", header: "Threshold", cell: (r) => pct(r.t) },
    { id: "p", header: "Result", cell: (r) => <StatusIndicator type={r.pass ? "success" : "error"}>{r.pass ? "Pass" : "Fail"}</StatusIndicator> }]} />;
}

export default function Validate({ design, setDesign, ctx, golden, setGolden, runs, onRun, running, thr, setThr }) {
  const lint = useMemo(() => lintDesign(design, ctx), [design, ctx]);
  const [runDesign, setRunDesign] = useState({ label: "Current design", value: "current" });
  const [a, setA] = useState(null), [b, setB] = useState(null);
  const [json, setJson] = useState(null);
  const upd = (i, k, v) => setGolden(golden.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const last = runs[0];
  const ra = runs.find((r) => r.id === a?.value), rb = runs.find((r) => r.id === b?.value);
  const cmp = ra && rb ? compareRuns(ra, rb) : null;
  const runOpts = runs.map((r) => ({ value: r.id, label: `${r.label} (${new Date(r.at).toLocaleTimeString()})`, description: `hit ${pct(r.aggregate.hitRate)} / faithfulness ${pct(r.aggregate.faithfulness)}` }));
  return (
    <SpaceBetween size="l">
      <Container header={<Header variant="h2" counter={`(${lint.length})`} description="Static checks of the design against the embedding model, the corpus and retrieval settings. No query is run.">Design lint</Header>}>
        <Table variant="embedded" data-testid="lint-table" items={lint} trackBy="message" empty={<StatusIndicator type="success">No findings: the design passes all lint rules.</StatusIndicator>} columnDefinitions={[
          { id: "s", header: "Severity", cell: (l) => <StatusIndicator type={sevType[l.severity]}>{l.severity}</StatusIndicator>, width: 120 }, { id: "n", header: "Stage", cell: (l) => l.node, width: 100 }, { id: "i", header: "Rule", cell: (l) => <code>{l.id}</code> },
          { id: "m", header: "Finding", cell: (l) => l.message }, { id: "f", header: "Fix", cell: (l) => (l.fix ? <Button onClick={() => setDesign(applyFix(design, l.fix))}>Apply fix ({l.fix.path} = {String(l.fix.value)})</Button> : "-") }]} />
      </Container>
      <Container header={<Header variant="h2" description="question / expected source (substring of the document URI) / expected answer. An empty expected source means the question is out of scope and must be refused."
        actions={<SpaceBetween direction="horizontal" size="xs"><Button onClick={() => setGolden([...golden, { question: "", expectedSources: [], expectedAnswer: "" }])}>Add row</Button><Button onClick={() => setJson(json === null ? JSON.stringify(golden, null, 2) : null)}>{json === null ? "Edit as JSON" : "Close JSON"}</Button></SpaceBetween>}>Golden set</Header>}>
        {json !== null ? <Textarea value={json} rows={12} ariaLabel="golden json" onChange={({ detail }) => { setJson(detail.value); try { setGolden(JSON.parse(detail.value)); } catch { /* typing */ } }} /> :
          <Table variant="embedded" data-testid="golden-table" items={golden.map((g, i) => ({ ...g, i }))} trackBy="i" columnDefinitions={[
            { id: "q", header: "Question", cell: (g) => <Input value={g.question} onChange={({ detail }) => upd(g.i, "question", detail.value)} ariaLabel={`question ${g.i + 1}`} /> },
            { id: "s", header: "Expected source(s)", width: 220, cell: (g) => <Input value={(g.expectedSources || []).join(", ")} onChange={({ detail }) => upd(g.i, "expectedSources", detail.value.split(",").map((x) => x.trim()).filter(Boolean))} ariaLabel={`sources ${g.i + 1}`} /> },
            { id: "a", header: "Expected answer", cell: (g) => <Input value={g.expectedAnswer} onChange={({ detail }) => upd(g.i, "expectedAnswer", detail.value)} ariaLabel={`answer ${g.i + 1}`} /> },
            { id: "x", header: "", width: 90, cell: (g) => <Button variant="inline-link" onClick={() => setGolden(golden.filter((_, j) => j !== g.i))}>Remove</Button> }]} />}
      </Container>
      <Container header={<Header variant="h2" description="Runs Retrieve (with per-stage trace) and RetrieveAndGenerate for every row; scores are deterministic (no LLM judge)."
        actions={<SpaceBetween direction="horizontal" size="xs"><Select selectedOption={runDesign} onChange={({ detail }) => setRunDesign(detail.selectedOption)} ariaLabel="design to evaluate" options={[{ label: "Current design", value: "current" }, ...Object.entries(PRESETS).map(([value, p]) => ({ label: `Preset: ${p.label}`, value }))]} /><Button variant="primary" loading={running} onClick={() => onRun(runDesign.value)}>Run evaluation</Button></SpaceBetween>}>Evaluation</Header>}>
        <SpaceBetween size="m">
          <ColumnLayout columns={4} variant="text-grid">{Object.keys(METRIC_LABELS).map((k) => <div key={k}><Box variant="awsui-key-label">{METRIC_LABELS[k]} threshold</Box><Input type="number" value={String(thr[k])} onChange={({ detail }) => setThr({ ...thr, [k]: Number(detail.value) })} ariaLabel={`${k} threshold`} /></div>)}</ColumnLayout>
          {last ? <><Box variant="h3">Latest run: {last.label} ({last.rows.length} questions, {last.ms.toFixed(0)} ms)</Box><div data-testid="eval-latest"><RunMetrics run={last} thr={thr} /></div>
            <Table variant="embedded" data-testid="eval-rows" items={last.rows} trackBy="question" columnDefinitions={[{ id: "q", header: "Question", cell: (r) => r.question }, ...["hitRate", "mrr", "contextPrecision", "contextRecall", "citationAccuracy", "faithfulness", "answerRelevance"].map((k) => ({ id: k, header: METRIC_LABELS[k], cell: (r) => pct(r.scores[k]) })), { id: "ans", header: "Answer", cell: (r) => r.answer.slice(0, 80) }]} /></> : <Box color="text-status-inactive">No evaluation yet. Run one to score the design.</Box>}
        </SpaceBetween>
      </Container>
      <Container header={<Header variant="h2" description="Pick two runs (different designs) to compare side by side.">Run history and A/B</Header>}>
        <SpaceBetween size="m">
          <Table variant="embedded" data-testid="run-history" items={runs} trackBy="id" empty={<Box>No runs yet.</Box>} columnDefinitions={[{ id: "l", header: "Design", cell: (r) => r.label }, { id: "t", header: "When", cell: (r) => new Date(r.at).toLocaleTimeString() }, { id: "c", header: "Chunking", cell: (r) => `${r.design.chunk.strategy} ${r.design.chunk.maxTokens}/${r.design.chunk.overlapPct}%` }, { id: "r", header: "Retrieval", cell: (r) => `${r.design.retrieve.searchType} k${r.design.retrieve.topK}${r.design.rerank.enabled ? " +rerank" : ""}` }, { id: "h", header: "Hit", cell: (r) => pct(r.aggregate.hitRate) }, { id: "m", header: "MRR", cell: (r) => pct(r.aggregate.mrr) }, { id: "f", header: "Faithful", cell: (r) => pct(r.aggregate.faithfulness) }]} />
          <ColumnLayout columns={2}><div><Box variant="awsui-key-label">Run A</Box><Select selectedOption={a} onChange={({ detail }) => setA(detail.selectedOption)} options={runOpts} placeholder="Choose run A" ariaLabel="run A" /></div><div><Box variant="awsui-key-label">Run B</Box><Select selectedOption={b} onChange={({ detail }) => setB(detail.selectedOption)} options={runOpts} placeholder="Choose run B" ariaLabel="run B" /></div></ColumnLayout>
          {cmp && <div data-testid="ab-compare"><BarChart height={220} hideFilter xScaleType="categorical" xTitle="Metric" yTitle="Score" ariaLabel="A/B comparison" yDomain={[0, 1]} series={[{ title: `A: ${ra.label}`, type: "bar", data: cmp.map((c) => ({ x: METRIC_LABELS[c.metric], y: c.a })) }, { title: `B: ${rb.label}`, type: "bar", data: cmp.map((c) => ({ x: METRIC_LABELS[c.metric], y: c.b })) }]} />
            <Table variant="embedded" items={cmp} trackBy="metric" columnDefinitions={[{ id: "m", header: "Metric", cell: (c) => METRIC_LABELS[c.metric] }, { id: "a", header: "A", cell: (c) => pct(c.a) }, { id: "b", header: "B", cell: (c) => pct(c.b) }, { id: "d", header: "Delta (B-A)", cell: (c) => `${c.delta >= 0 ? "+" : ""}${(c.delta * 100).toFixed(1)} pts` }, { id: "w", header: "Winner", cell: (c) => <StatusIndicator type={c.winner === "tie" ? "stopped" : "success"}>{c.winner}</StatusIndicator> }]} /></div>}
        </SpaceBetween>
      </Container>
    </SpaceBetween>
  );
}
