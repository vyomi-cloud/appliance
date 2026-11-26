/* VALIDATE: static lint + golden-set evaluation (7 deterministic metrics, thresholds, run history, A/B). */
import { useMemo, useState } from "react";
import { Box, Button, Chip, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { METRIC_LABELS, PRESETS, applyFix, compareRuns, lintDesign, verdicts } from "../../../../common/ragstudio/engine.js";
import { gcpLint } from "./gcpMap.js";
import { Bars, Card, SevChip, Status, Tbl, pct } from "./ui.jsx";

export function RunMetrics({ run, thr }) {
  const v = verdicts(run.aggregate, thr);
  return <Tbl columns={[{ id: "m", header: "Metric", cell: (r) => METRIC_LABELS[r.k] }, { id: "v", header: "Score", cell: (r) => <b data-testid={`metric-${r.k}`}>{pct(r.val)}</b> }, { id: "t", header: "Threshold", cell: (r) => pct(r.t) },
    { id: "p", header: "Result", cell: (r) => <Status ok={r.pass}>{r.pass ? "Pass" : "Fail"}</Status> }]} rows={Object.keys(METRIC_LABELS).map((k) => ({ k, val: run.aggregate[k], pass: v[k], t: thr[k] }))} rowKey={(r) => r.k} />;
}

export default function Validate({ design, setDesign, ctx, golden, setGolden, runs, onRun, running, thr, setThr }) {
  const lint = useMemo(() => [...lintDesign(design, ctx), ...gcpLint(design)], [design, ctx]);
  const [runDesign, setRunDesign] = useState("current"), [a, setA] = useState(""), [b, setB] = useState(""), [json, setJson] = useState(null);
  const upd = (i, k, v) => setGolden(golden.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const last = runs[0], ra = runs.find((r) => r.id === a), rb = runs.find((r) => r.id === b), cmp = ra && rb ? compareRuns(ra, rb) : null;
  return (
    <Stack spacing={2}>
      <Card title={`Design lint (${lint.length})`} description="Static checks of the design against the embedding model, the corpus and the RAG Engine's limits. No query is run.">
        <Tbl data-testid="lint-table" rows={lint} empty="No findings: the design passes all lint rules." rowKey={(l) => l.message} columns={[
          { id: "s", header: "Severity", cell: (l) => <SevChip s={l.severity} /> }, { id: "n", header: "Stage", cell: (l) => l.node }, { id: "i", header: "Rule", cell: (l) => <code>{l.id}</code> },
          { id: "m", header: "Finding", cell: (l) => l.message }, { id: "f", header: "Fix", cell: (l) => (l.fix ? <Button size="small" onClick={() => setDesign(applyFix(design, l.fix))}>Apply fix ({l.fix.path} = {String(l.fix.value)})</Button> : "-") }]} />
      </Card>
      <Card title="Golden set" description="question / expected source (substring of the document URI or file name) / expected answer. An empty expected source means the question is out of scope and must be refused."
        actions={<Stack direction="row" spacing={1}><Button size="small" onClick={() => setGolden([...golden, { question: "", expectedSources: [], expectedAnswer: "" }])}>Add row</Button><Button size="small" onClick={() => setJson(json === null ? JSON.stringify(golden, null, 2) : null)}>{json === null ? "Edit as JSON" : "Close JSON"}</Button></Stack>}>
        {json !== null ? <TextField multiline minRows={10} fullWidth value={json} onChange={(e) => { setJson(e.target.value); try { setGolden(JSON.parse(e.target.value)); } catch { /* typing */ } }} />
          : <Tbl data-testid="golden-table" rows={golden.map((g, i) => ({ ...g, i }))} rowKey={(g) => g.i} columns={[
            { id: "q", header: "Question", cell: (g) => <TextField size="small" fullWidth value={g.question} onChange={(e) => upd(g.i, "question", e.target.value)} inputProps={{ "aria-label": `question ${g.i + 1}` }} /> },
            { id: "s", header: "Expected source(s)", width: 220, cell: (g) => <TextField size="small" value={(g.expectedSources || []).join(", ")} onChange={(e) => upd(g.i, "expectedSources", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} inputProps={{ "aria-label": `sources ${g.i + 1}` }} /> },
            { id: "a", header: "Expected answer", cell: (g) => <TextField size="small" fullWidth value={g.expectedAnswer} onChange={(e) => upd(g.i, "expectedAnswer", e.target.value)} inputProps={{ "aria-label": `answer ${g.i + 1}` }} /> },
            { id: "x", header: "", cell: (g) => <Button size="small" onClick={() => setGolden(golden.filter((_, j) => j !== g.i))}>Remove</Button> }]} />}
      </Card>
      <Card title="Evaluate" description="Runs :retrieveContexts (with the per-stage trace) and generateContent + the retrieval tool for every row; scores are deterministic (no LLM judge)."
        actions={<Stack direction="row" spacing={1}><TextField select size="small" value={runDesign} onChange={(e) => setRunDesign(e.target.value)} sx={{ minWidth: 220 }} inputProps={{ "aria-label": "design to evaluate" }}><MenuItem value="current">Current design</MenuItem>{Object.entries(PRESETS).map(([k, p]) => <MenuItem key={k} value={k}>Preset: {p.label}</MenuItem>)}</TextField>
          <Button variant="contained" disabled={running} onClick={() => onRun(runDesign)} data-testid="run-eval">{running ? "Running..." : "Run evaluation"}</Button></Stack>}>
        <Stack spacing={2}>
          <Stack direction="row" useFlexGap spacing={1.5} sx={{ flexWrap: "wrap" }}>{Object.keys(METRIC_LABELS).map((k) => <TextField key={k} size="small" type="number" label={`${METRIC_LABELS[k]} threshold`} value={thr[k]} onChange={(e) => setThr({ ...thr, [k]: Number(e.target.value) })} inputProps={{ step: 0.05, min: 0, max: 1, "aria-label": `${k} threshold` }} sx={{ width: 170 }} />)}</Stack>
          {last ? <><Typography variant="subtitle2">Latest run: {last.label} ({last.rows.length} questions, {last.ms.toFixed(0)} ms)</Typography><div data-testid="eval-latest"><RunMetrics run={last} thr={thr} /></div>
            <Tbl data-testid="eval-rows" rows={last.rows} rowKey={(r) => r.question} columns={[{ id: "q", header: "Question", cell: (r) => r.question }, ...Object.keys(METRIC_LABELS).map((k) => ({ id: k, header: METRIC_LABELS[k], cell: (r) => pct(r.scores[k]) }))]} /></> : <Typography variant="body2" color="text.secondary">No evaluation yet.</Typography>}
        </Stack>
      </Card>
      <Card title="Run history and A/B" description="Pick two runs (different designs) to compare side by side.">
        <Stack spacing={2}>
          <Tbl data-testid="run-history" rows={runs} empty="No runs yet." rowKey={(r) => r.id} columns={[{ id: "l", header: "Design", cell: (r) => r.label }, { id: "t", header: "When", cell: (r) => new Date(r.at).toLocaleTimeString() }, { id: "c", header: "Chunking", cell: (r) => `${r.design.chunk.strategy} ${r.design.chunk.maxTokens}/${r.design.chunk.overlapPct}%` }, { id: "h", header: "Hit rate", cell: (r) => pct(r.aggregate.hitRate) }, { id: "f", header: "Faithfulness", cell: (r) => pct(r.aggregate.faithfulness) }]} />
          <Stack direction="row" spacing={1.5}>{[["Run A", a, setA], ["Run B", b, setB]].map(([l, v, s]) => <TextField key={l} select size="small" label={l} value={v} onChange={(e) => s(e.target.value)} sx={{ minWidth: 260 }}>{runs.map((r) => <MenuItem key={r.id} value={r.id}>{r.label} ({new Date(r.at).toLocaleTimeString()})</MenuItem>)}</TextField>)}</Stack>
          {cmp && <Box data-testid="ab-compare"><Tbl rows={cmp} rowKey={(c) => c.metric} columns={[{ id: "m", header: "Metric", cell: (c) => METRIC_LABELS[c.metric] }, { id: "a", header: "A", cell: (c) => pct(c.a) }, { id: "b", header: "B", cell: (c) => pct(c.b) }, { id: "d", header: "Delta (B-A)", cell: (c) => `${c.delta >= 0 ? "+" : ""}${(c.delta * 100).toFixed(0)} pts` }, { id: "w", header: "Winner", cell: (c) => <Chip size="small" label={c.winner} /> }]} />
            <Bars data={Object.fromEntries(cmp.flatMap((c) => [[`A ${METRIC_LABELS[c.metric]}`, Math.round(c.a * 100)], [`B ${METRIC_LABELS[c.metric]}`, Math.round(c.b * 100)]]))} unit="%" /></Box>}
        </Stack>
      </Card>
    </Stack>
  );
}
