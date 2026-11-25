/* VALIDATE: static lint + golden-set evaluation (7 deterministic metrics, thresholds, run history, A/B). */
import { useMemo, useState } from "react";
import { Input, Select, Textarea } from "@fluentui/react-components";
import { METRIC_LABELS, PRESETS, applyFix, compareRuns, lintDesign, verdicts } from "../../../../common/ragstudio/engine.js";
import { Bars, Btn, Card, Grid, Stack, Status, Tbl } from "./ui.jsx";

const pct = (x) => (x * 100).toFixed(0) + "%";
const sevType = { error: "error", warning: "warning", info: "info" };

export function RunMetrics({ run, thr }) {
  const vd = verdicts(run.aggregate, thr);
  return <Tbl items={Object.keys(METRIC_LABELS).map((k) => ({ k, val: run.aggregate[k], pass: vd[k], t: thr[k] }))} trackBy="k" columns={[
    { id: "m", header: "Metric", cell: (r) => METRIC_LABELS[r.k] }, { id: "v", header: "Score", cell: (r) => <b data-testid={`metric-${r.k}`}>{pct(r.val)}</b> }, { id: "t", header: "Threshold", cell: (r) => pct(r.t) },
    { id: "p", header: "Result", cell: (r) => <Status type={r.pass ? "success" : "error"}>{r.pass ? "Pass" : "Fail"}</Status> }]} />;
}

export default function Validate({ design, setDesign, ctx, golden, setGolden, runs, onRun, running, thr, setThr }) {
  const lint = useMemo(() => lintDesign(design, ctx), [design, ctx]);
  const [which, setWhich] = useState("current"), [a, setA] = useState(""), [b, setB] = useState(""), [json, setJson] = useState(null);
  const upd = (i, k, val) => setGolden(golden.map((r, j) => (j === i ? { ...r, [k]: val } : r)));
  const last = runs[0], ra = runs.find((r) => r.id === a), rb = runs.find((r) => r.id === b), cmp = ra && rb ? compareRuns(ra, rb) : null;
  return (
    <Stack gap={16}>
      <Card title={`Design lint (${lint.length})`} description="Static checks of the design against the embedding model, the corpus and retrieval settings. No query is run.">
        <Tbl testid="lint-table" items={lint} trackBy="message" empty="No findings: the design passes all lint rules." columns={[
          { id: "s", header: "Severity", width: 100, cell: (l) => <Status type={sevType[l.severity]}>{l.severity}</Status> }, { id: "n", header: "Stage", width: 90, cell: (l) => l.node }, { id: "i", header: "Rule", cell: (l) => <code>{l.id}</code> },
          { id: "m", header: "Finding", cell: (l) => l.message }, { id: "f", header: "Fix", cell: (l) => (l.fix ? <Btn size="small" onClick={() => setDesign(applyFix(design, l.fix))}>Apply fix ({l.fix.path} = {String(l.fix.value)})</Btn> : "-") }]} />
      </Card>
      <Card title="Golden question set" description="question / expected source (substring of the chunk's document name) / expected answer. An empty expected source means the question is out of scope and must be refused."
        actions={<><Btn onClick={() => setGolden([...golden, { question: "", expectedSources: [], expectedAnswer: "" }])}>Add row</Btn><Btn onClick={() => setJson(json === null ? JSON.stringify(golden, null, 2) : null)}>{json === null ? "Edit as JSON" : "Close JSON"}</Btn></>}>
        {json !== null ? <Textarea value={json} rows={12} aria-label="golden json" style={{ width: "100%" }} onChange={(_, d) => { setJson(d.value); try { setGolden(JSON.parse(d.value)); } catch { /* typing */ } }} /> :
          <Tbl testid="golden-table" items={golden.map((g, i) => ({ ...g, i }))} trackBy="i" columns={[
            { id: "q", header: "Question", cell: (g) => <Input value={g.question} onChange={(_, d) => upd(g.i, "question", d.value)} aria-label={`question ${g.i + 1}`} style={{ width: "100%" }} /> },
            { id: "s", header: "Expected source(s)", width: 220, cell: (g) => <Input value={(g.expectedSources || []).join(", ")} onChange={(_, d) => upd(g.i, "expectedSources", d.value.split(",").map((x) => x.trim()).filter(Boolean))} aria-label={`sources ${g.i + 1}`} /> },
            { id: "a", header: "Expected answer", cell: (g) => <Input value={g.expectedAnswer} onChange={(_, d) => upd(g.i, "expectedAnswer", d.value)} aria-label={`answer ${g.i + 1}`} style={{ width: "100%" }} /> },
            { id: "x", header: "", width: 80, cell: (g) => <Btn size="small" onClick={() => setGolden(golden.filter((_, j) => j !== g.i))}>Remove</Btn> }]} />}
      </Card>
      <Card title="Evaluation" description="Runs the retrieve trace and chat on your data for every row; scores are deterministic (no LLM judge)."
        actions={<><Select aria-label="design to evaluate" value={which} onChange={(_, d) => setWhich(d.value)}><option value="current">Current design</option>{Object.entries(PRESETS).map(([k, p]) => <option key={k} value={k}>Preset: {p.label}</option>)}</Select>
          <Btn primary disabled={running} onClick={() => onRun(which)}>{running ? "Running..." : "Run evaluation"}</Btn></>}>
        <Stack gap={12}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 10 }}>{Object.keys(METRIC_LABELS).map((k) => <label key={k} style={{ fontSize: 12 }}>{METRIC_LABELS[k]} threshold<Input type="number" value={String(thr[k])} onChange={(_, d) => setThr({ ...thr, [k]: Number(d.value) })} aria-label={`${k} threshold`} /></label>)}</div>
          {last ? <><b>Latest run: {last.label} ({last.rows.length} questions, {last.ms.toFixed(0)} ms)</b><div data-testid="eval-latest"><RunMetrics run={last} thr={thr} /></div>
            <Tbl testid="eval-rows" items={last.rows} trackBy="question" columns={[{ id: "q", header: "Question", cell: (r) => r.question }, ...["hitRate", "mrr", "contextPrecision", "contextRecall", "citationAccuracy", "faithfulness", "answerRelevance"].map((k) => ({ id: k, header: METRIC_LABELS[k], cell: (r) => pct(r.scores[k]) }))]} /></> : <span style={{ opacity: 0.7 }}>No runs yet.</span>}
        </Stack>
      </Card>
      <Card title="Run history and A/B" description="Pick two runs (different designs) to compare side by side.">
        <Stack gap={12}>
          <Tbl testid="run-history" items={runs} trackBy="id" empty="No runs yet." columns={[{ id: "l", header: "Design", cell: (r) => r.label }, { id: "t", header: "When", cell: (r) => new Date(r.at).toLocaleTimeString() }, { id: "c", header: "Chunking", cell: (r) => `${r.design.chunk.strategy} ${r.design.chunk.maxTokens}/${r.design.chunk.overlapPct}%` }, { id: "h", header: "Hit rate", cell: (r) => pct(r.aggregate.hitRate) }, { id: "f", header: "Faithfulness", cell: (r) => pct(r.aggregate.faithfulness) }]} />
          <Grid cols={2}>{[["Run A", a, setA, "run A"], ["Run B", b, setB, "run B"]].map(([l, val, set, al]) => <label key={l} style={{ fontSize: 12 }}>{l}<Select aria-label={al} value={val} onChange={(_, d) => set(d.value)}><option value="">Choose {al}</option>{runs.map((r) => <option key={r.id} value={r.id}>{r.label} ({new Date(r.at).toLocaleTimeString()})</option>)}</Select></label>)}</Grid>
          {cmp && <div data-testid="ab-compare"><Bars data={cmp.flatMap((c) => [[`A ${METRIC_LABELS[c.metric]}`, c.a], [`B ${METRIC_LABELS[c.metric]}`, c.b]])} max={1} fmt={pct} />
            <Tbl items={cmp} trackBy="metric" columns={[{ id: "m", header: "Metric", cell: (c) => METRIC_LABELS[c.metric] }, { id: "a", header: "A", cell: (c) => pct(c.a) }, { id: "b", header: "B", cell: (c) => pct(c.b) }, { id: "d", header: "Delta (B-A)", cell: (c) => `${c.delta >= 0 ? "+" : ""}${(c.delta * 100).toFixed(0)} pts` }]} /></div>}
        </Stack>
      </Card>
    </Stack>
  );
}
