/* DESIGN: the pipeline as clickable stages (each edits one part of the design); Apply writes the chunk config, ingestion re-chunks; Export / Import the vyomi.rag-design/v1 document. */
import { useMemo, useRef, useState } from "react";
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Paper, Stack, Switch, TextField, Typography } from "@mui/material";
import { EMBED_MODELS, PRESETS, applyPreset, lintDesign } from "../../../../common/ragstudio/engine.js";
import { toDocument, fromDocument, validate } from "../../../../common/ragstudio/document.js";
import { designToApi, gcpLint } from "./gcpMap.js";

const STAGES = [
  ["source", "Source", (d) => `gs://${d.source.bucket}/${d.source.prefix}`],
  ["clean", "Clean / PII scan", (d) => [d.clean.piiScan && "PII scan", d.clean.stripHtml && "strip HTML", d.clean.dedupe && "dedupe"].filter(Boolean).join(", ") || "off"],
  ["chunk", "Chunk", (d) => d.chunk.strategy === "NONE" ? "whole docs" : `${d.chunk.strategy.toLowerCase()} ${d.chunk.maxTokens} tok / ${d.chunk.overlapPct}%`],
  ["embed", "Embed", (d) => d.embed.model],
  ["index", "Index", (d) => d.index.store],
  ["retrieve", "Retrieve", (d) => `${d.retrieve.searchType.toLowerCase()} top-${d.retrieve.topK}${d.retrieve.searchType === "HYBRID" ? ` alpha=${d.retrieve.hybridWeight}` : ""}${d.retrieve.filterKey ? ` | ${d.retrieve.filterKey}=${d.retrieve.filterValue}` : ""}`],
  ["rerank", "Rerank", (d) => (d.rerank.enabled ? `top-${d.rerank.topN}` : "off")],
  ["generate", "Generate", (d) => `${d.generate.model}, grounding >= ${d.generate.groundingThreshold}${d.generate.citations ? " + citations" : ""}`],
];
const SEV = { error: "error", warning: "warning", info: "info" };

export const download = (name, obj) => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); };

export default function Design({ design, setDesign, golden, setGolden, be, ctx, applied, onApply, onIngest, busy, jobMsg, onSeed }) {
  const [sel, setSel] = useState("chunk");
  const [imp, setImp] = useState(null), [impErr, setImpErr] = useState([]), [msg, setMsg] = useState(null);
  const file = useRef(null);
  const lint = useMemo(() => [...lintDesign(design, ctx), ...gcpLint(design)], [design, ctx]);
  const sevOf = (id) => lint.filter((l) => l.node === id).reduce((a, l) => (l.severity === "error" || a === "error" ? "error" : l.severity === "warning" || a === "warning" ? "warning" : "info"), null);
  const set = (sec, k, conv) => (e) => setDesign({ ...design, [sec]: { ...design[sec], [k]: conv ? conv(e.target) : e.target.value } });
  const num = (t) => (t.value === "" ? "" : Number(t.value)), chk = (t) => t.checked;
  const tf = (label, sec, k, p = {}) => <TextField size="small" label={label} value={design[sec][k]} onChange={set(sec, k, p.type === "number" ? num : undefined)} {...p} />;
  const sw = (label, sec, k) => <FormControlLabel control={<Switch checked={!!design[sec][k]} onChange={set(sec, k, chk)} />} label={label} />;
  const sl = (label, sec, k, opts) => <TextField select size="small" label={label} value={design[sec][k]} onChange={set(sec, k)}>{opts.map((o) => <MenuItem key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</MenuItem>)}</TextField>;
  const panel = {
    source: <>{tf("Cloud Storage bucket", "source", "bucket")}{tf("Object prefix", "source", "prefix")}</>,
    clean: <>{sw("PII scan (flag and exclude)", "clean", "piiScan")}{sw("Strip HTML", "clean", "stripHtml")}{sw("Drop near-duplicates", "clean", "dedupe")}</>,
    chunk: <>{sl("Strategy", "chunk", "strategy", ["FIXED_SIZE", "SEMANTIC", "HIERARCHICAL", "NONE"])}{tf("Max tokens per chunk", "chunk", "maxTokens", { type: "number" })}{tf("Overlap %", "chunk", "overlapPct", { type: "number" })}
      <Typography variant="caption" color="text.secondary">Sent as fixedLengthChunking chunkSize {designToApi(design).transformation.ragFileChunkingConfig.fixedLengthChunking.chunkSize} chars / chunkOverlap {designToApi(design).transformation.ragFileChunkingConfig.fixedLengthChunking.chunkOverlap}.</Typography></>,
    embed: <>{sl("Embedding model", "embed", "model", Object.entries(EMBED_MODELS).filter(([k]) => /embedding/.test(k)).map(([value, m]) => ({ value, label: m.label })))}<Typography variant="caption" color="text.secondary">The corpus embedding model (ragEmbeddingModelConfig) is fixed when the corpus is created.</Typography></>,
    index: sl("Vector store", "index", "store", ["rag-managed-db", "vertex-ai-vector-search", "pinecone"]),
    retrieve: <>{sl("Search type", "retrieve", "searchType", ["HYBRID", "SEMANTIC"])}{tf("Top-k candidates", "retrieve", "topK", { type: "number" })}{tf("Hybrid alpha (dense share, 0-1)", "retrieve", "hybridWeight", { type: "number", inputProps: { step: 0.05 } })}
      {tf("Filter key (file | source)", "retrieve", "filterKey")}{tf("Filter value", "retrieve", "filterValue")}</>,
    rerank: <>{sw("Rerank candidates (ranking.rankService)", "rerank", "enabled")}{tf("Return top N after rerank", "rerank", "topN", { type: "number" })}</>,
    generate: <>{tf("Generation model", "generate", "model")}{tf("Grounding threshold (0-1)", "generate", "groundingThreshold", { type: "number", inputProps: { step: 0.05 } })}{sw("Return citations", "generate", "citations")}</>,
  };
  const exportDoc = () => { const doc = toDocument(design, "gcp", { golden }); const bad = validate(doc); if (bad.length) { setMsg({ severity: "error", text: `Not exported: ${bad.join("; ")}` }); return; } download(`${design.name.replace(/\W+/g, "-")}.rag-design.json`, doc); setMsg({ severity: "success", text: `Exported vyomi.rag-design/v1 (cloud gcp, ${doc.golden.length} golden rows).` }); };
  const doImport = (text) => {
    let doc; try { doc = JSON.parse(text); } catch (e) { setImpErr([`JSON: ${e.message}`]); return; }
    const bad = validate(doc); if (bad.length) { setImpErr(bad); return; }
    const r = fromDocument(doc); setDesign({ ...r.design, embed: { model: /embedding/.test(r.design.embed.model) ? r.design.embed.model : design.embed.model } }); if (r.golden.length) setGolden(r.golden);
    setImp(null); setImpErr([]); setMsg({ severity: "success", text: `Imported "${doc.name}" (authored for ${doc.cloud}).${doc.cloud !== "gcp" ? " The embedding model was kept: it is cloud-specific." : ""}` });
  };
  const api = designToApi(design);
  return (
    <Stack spacing={2}>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack direction="row" spacing={1} alignItems="center" useFlexGap sx={{ flexWrap: "wrap", mb: 1.5 }}>
          <Typography variant="subtitle1" sx={{ flex: 1 }}>Pipeline stages <Typography component="span" variant="caption" color="text.secondary">click a stage to edit it; coloured outlines are lint findings (see Validate)</Typography></Typography>
          <TextField select size="small" label="Load preset" value="" onChange={(e) => setDesign(applyPreset(design, e.target.value))} sx={{ minWidth: 170 }}>{Object.entries(PRESETS).map(([k, p]) => <MenuItem key={k} value={k}>{p.label}</MenuItem>)}</TextField>
          <Button size="small" variant="outlined" onClick={exportDoc} data-testid="export-design">Export design</Button>
          <Button size="small" variant="outlined" onClick={() => { setImp(""); setImpErr([]); }} data-testid="import-design">Import design</Button>
        </Stack>
        {msg && <Alert severity={msg.severity} sx={{ mb: 1.5 }} onClose={() => setMsg(null)} data-testid="doc-msg">{msg.text}</Alert>}
        <Stack direction="row" useFlexGap spacing={1} sx={{ flexWrap: "wrap" }} data-testid="flow">
          {STAGES.map(([id, title, sum], i) => { const sev = sevOf(id);
            return <Paper key={id} data-testid={`node-${id}`} variant="outlined" onClick={() => setSel(id)} sx={{ cursor: "pointer", p: 1, width: 168, borderWidth: 2, borderColor: id === sel ? "primary.main" : sev ? `${SEV[sev]}.main` : "divider" }}>
              <Typography variant="body2" fontWeight={700}>{i + 1}. {title}{sev && <Chip size="small" color={SEV[sev]} label={sev} sx={{ ml: 0.5, height: 16, fontSize: 10 }} />}</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ wordBreak: "break-word" }}>{sum(design)}</Typography></Paper>; })}
        </Stack>
      </Paper>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
        <Paper variant="outlined" sx={{ p: 2, flex: 1 }}><Typography variant="subtitle1" sx={{ mb: 1.5 }}>{STAGES.find((s) => s[0] === sel)[1]} parameters</Typography><Stack spacing={1.5} data-testid="node-params">{panel[sel]}</Stack></Paper>
        <Paper variant="outlined" sx={{ p: 2, flex: 1 }}>
          <Typography variant="subtitle1">Apply to the RAG corpus</Typography>
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1 }}>The RAG Engine chunks per file, at upload or ragFiles:import. Apply stores the config; Apply and ingest re-chunks the corpus files with it.</Typography>
          <Stack spacing={1.25}>
            <Typography variant="body2">Target: <b data-testid="backend-label">{be.label}</b></Typography>
            <Stack direction="row" spacing={1}><Button variant="contained" disabled={busy !== ""} onClick={onApply}>{busy === "apply" ? "Applying..." : "Apply design"}</Button><Button variant="outlined" disabled={busy !== ""} onClick={onIngest}>{busy === "ingest" ? "Ingesting..." : "Apply and ingest"}</Button>
              {be.noCorpus && onSeed && <Button variant="outlined" disabled={busy !== ""} onClick={onSeed} data-testid="seed-demo">Seed demo corpus</Button>}</Stack>
            {jobMsg && <Alert severity={jobMsg.type} data-testid="job-msg">{jobMsg.text}</Alert>}
            {applied && <Alert severity="success" icon={false}>Applied chunking: {JSON.stringify(applied)}</Alert>}
            {api.notes.map((n) => <Alert key={n} severity="warning">{n}</Alert>)}
            <details><summary>Real API payload this design produces</summary><pre style={{ fontSize: 11, maxHeight: 220, overflow: "auto" }} data-testid="api-payload">{JSON.stringify({ importRagFilesConfig: api.importRagFilesConfig, ragRetrievalConfig: api.ragRetrievalConfig, ragEmbeddingModelConfig: api.ragEmbeddingModelConfig }, null, 2)}</pre></details>
          </Stack>
        </Paper>
      </Stack>
      <Dialog open={imp !== null} onClose={() => setImp(null)} fullWidth maxWidth="md">
        <DialogTitle>Import design (vyomi.rag-design/v1)</DialogTitle>
        <DialogContent>
          <Stack direction="row" spacing={1} sx={{ mb: 1 }}><Button size="small" onClick={() => file.current?.click()}>Choose file...</Button><input ref={file} type="file" accept="application/json,.json" hidden data-testid="import-file" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setImp(await f.text()); e.target.value = ""; }} /></Stack>
          <TextField multiline minRows={10} fullWidth value={imp || ""} onChange={(e) => setImp(e.target.value)} placeholder='{"schema": "vyomi.rag-design/v1", ...}' inputProps={{ "data-testid": "import-text" }} />
          {impErr.length > 0 && <Alert severity="error" sx={{ mt: 1 }} data-testid="import-errors">{impErr.map((e) => <div key={e}>{e}</div>)}</Alert>}
        </DialogContent>
        <DialogActions><Button onClick={() => setImp(null)}>Cancel</Button><Button variant="contained" disabled={!imp} onClick={() => doImport(imp)} data-testid="import-apply">Import</Button></DialogActions>
      </Dialog>
    </Stack>
  );
}
