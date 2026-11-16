/* Vertex AI Model Registry: import a chat model (LoRA adapter) and chat with it.
 * models:upload with model.artifactUri = gs://bucket/dir/ holding adapter.gguf + adapter_meta.json, label vyomi-import=chat-lora (core/gcp_vertex_core.py over
 * core/import_core.py); deployModel to an endpoint; endpoints/{id}:generateContent. Serving on Nano = wasm/wllama-bridge.js (base GGUF cached in OPFS + your adapter).
 * Honest: a small open base model plus your adapter, not a Gemini model. */
import { useEffect, useState } from "react";
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useNotify } from "../../../common/notify.jsx";
import { FRAMING, IMPORT_BASES, META_HELP, NANO_ONLY, TRAIN_HINT, checkAdapterFile, fmtBytes, isNanoSubstrate, randomSuffix, resolveMeta, servingState, useWllama } from "../../../common/importModel.js";
import { getProject } from "../../project.js";
import * as gcs from "../storage/api.js";
import * as api from "./api.js";

export const isImported = (m) => m?.labels?.["vyomi-imported"] === "true";

export function ServingBar() {
  const st = useWllama(), s = servingState(st);
  if (!isNanoSubstrate() && !st) return <Alert severity="info" data-testid="serving-nano-only">{NANO_ONLY}</Alert>;
  return (
    <Stack spacing={0.5} data-testid="serving-bar">
      <Typography variant="subtitle2">In-browser engine</Typography>
      <LinearProgress variant={s.pct == null ? (s.busy ? "indeterminate" : "determinate") : "determinate"} value={s.pct ?? 0} color={s.error ? "error" : s.done ? "success" : "primary"} />
      <Typography variant="caption" color="text.secondary">{s.label}</Typography>
      {st && s.done && <Typography variant="caption" color="text.secondary">{st.multiThread ? `${st.threads} threads` : "Single thread"}; {st.base || "base"} cached in this browser (OPFS).</Typography>}
    </Stack>
  );
}

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,62}$/;

export function ImportChatModelDialog({ open, onClose }) {
  const notify = useNotify();
  const [name, setName] = useState(`facilities-tuned-${randomSuffix()}`), [region, setRegion] = useState("us-central1");
  const [adapter, setAdapter] = useState(null), [metaFile, setMetaFile] = useState(null), [chk, setChk] = useState(null);
  const [base, setBase] = useState(IMPORT_BASES[0].id), [rank, setRank] = useState("8"), [alpha, setAlpha] = useState("16");
  const [step, setStep] = useState(""), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  useEffect(() => { checkAdapterFile(adapter).then((r) => setChk(adapter ? r : null)); }, [adapter]);
  const ready = NAME_RE.test(name) && chk?.ok && (metaFile || (rank && alpha));
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      const meta = await resolveMeta({ metaFile, base, rank, alpha });
      const bucket = `${getProject()}-vyomi-imports`, prefix = `uploads/${name.replace(/[^A-Za-z0-9-]/g, "-")}-${randomSuffix()}/`;
      setStep(`Uploading adapter to gs://${bucket}/${prefix}`);
      try { await gcs.insertBucket({ name: bucket }); } catch (e) { if (e.status !== 409) throw e; }
      await gcs.uploadObject(bucket, `${prefix}adapter.gguf`, await adapter.arrayBuffer(), "application/octet-stream");
      await gcs.uploadObject(bucket, `${prefix}adapter_meta.json`, meta, "application/json");
      setStep("Registering the model (models:upload)");
      await api.uploadModel({ model: { displayName: name, artifactUri: `gs://${bucket}/${prefix}`, labels: { "vyomi-import": "chat-lora" } } }, region);
      notify.success(`Imported model "${name}"`);
      onClose(true);
    } catch (e) { setErr(e); } finally { setBusy(false); setStep(""); }
  };
  return (
    <Dialog open={open} onClose={() => !busy && onClose(false)} fullWidth maxWidth="sm" aria-label="Import chat model">
      <DialogTitle>Import chat model (LoRA adapter)</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Alert severity="info" data-testid="import-framing">{FRAMING} {TRAIN_HINT}</Alert>
          {err && <Alert severity="error" data-testid="import-error">{err.message}</Alert>}
          <TextField size="small" label="Name" value={name} onChange={(e) => setName(e.target.value)} inputProps={{ "aria-label": "Name" }} />
          <TextField select size="small" label="Region" value={region} onChange={(e) => setRegion(e.target.value)} inputProps={{ "aria-label": "Region" }}>{api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}</TextField>
          <Box><Typography variant="body2" gutterBottom>Adapter file (adapter.gguf, up to 50 MB)</Typography><input type="file" accept=".gguf" aria-label="Adapter file" data-testid="adapter-input" onChange={(e) => setAdapter(e.target.files?.[0] || null)} /></Box>
          {adapter && chk && !chk.ok && <Alert severity="error" data-testid="adapter-error">{chk.error}</Alert>}
          {adapter && chk?.ok && <Alert severity="success" data-testid="adapter-ok">{adapter.name}, {fmtBytes(adapter.size)}. GGUF header looks right; the engine checks rank, hidden size and base on import.</Alert>}
          <Box><Typography variant="body2" gutterBottom>adapter_meta.json (optional)</Typography><input type="file" accept=".json" aria-label="Meta file" data-testid="meta-input" onChange={(e) => setMetaFile(e.target.files?.[0] || null)} /><Typography variant="caption" display="block" color="text.secondary">{META_HELP} Leave empty to use the fields below.</Typography></Box>
          {!metaFile && <Stack direction="row" spacing={1}>
            <TextField select size="small" label="Base model" value={base} onChange={(e) => setBase(e.target.value)} sx={{ flex: 2 }} inputProps={{ "aria-label": "Base model" }}>{IMPORT_BASES.map((b) => <MenuItem key={b.id} value={b.id}>{b.name}</MenuItem>)}</TextField>
            <TextField size="small" label="LoRA rank" value={rank} onChange={(e) => setRank(e.target.value)} sx={{ flex: 1 }} inputProps={{ "aria-label": "LoRA rank" }} />
            <TextField size="small" label="LoRA alpha" value={alpha} onChange={(e) => setAlpha(e.target.value)} sx={{ flex: 1 }} inputProps={{ "aria-label": "LoRA alpha" }} />
          </Stack>}
          {busy && <Box data-testid="import-progress"><LinearProgress /><Typography variant="caption">{step}</Typography></Box>}
        </Stack>
      </DialogContent>
      <DialogActions><Button disabled={busy} onClick={() => onClose(false)}>Cancel</Button><Button variant="contained" disabled={busy || !ready} onClick={go}>Import</Button></DialogActions>
    </Dialog>
  );
}

/** Endpoint (name) serving this imported model: an existing deployment, or a new endpoint with deployModel. */
export async function ensureEndpoint(model) {
  const loc = api.pname(model.name).location;
  const eps = await api.list("endpoints", { loc }).catch(() => []);
  const have = eps.find((e) => (e.deployedModels || []).some((d) => String(d.model || "").split("@")[0] === model.name));
  if (have) return have.name;
  const ep = await api.create("endpoints", { displayName: `${model.displayName}-endpoint` }, { loc });
  const epName = ep.response?.name || ep.name;
  await api.verb(epName, "deployModel", { deployedModel: { model: model.name, displayName: model.displayName }, trafficSplit: { 0: 100 } });
  return epName;
}

/** "Chat with imported model": deploy on demand, then endpoint :generateContent. */
export function ChatImportedDialog({ model, onClose }) {
  const [ep, setEp] = useState(""), [prep, setPrep] = useState(true), [msg, setMsg] = useState("Say hello in five words."), [hist, setHist] = useState([]), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
  useEffect(() => { ensureEndpoint(model).then(setEp).catch(setErr).finally(() => setPrep(false)); }, [model.name]);   // eslint-disable-line react-hooks/exhaustive-deps
  const send = async (text = msg, max = 128) => {
    const next = [...hist, { role: "user", text }];
    setBusy(true); setErr(null);
    try {
      const r = await api.chatEndpoint(ep, next, max);
      setHist([...next, { role: "model", text: (r.candidates?.[0]?.content?.parts || []).map((p) => p.text).join(""), meta: `${r.usageMetadata?.promptTokenCount} in / ${r.usageMetadata?.candidatesTokenCount} out` }]); setMsg("");
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={() => onClose(false)} fullWidth maxWidth="md" aria-label="Chat with imported model">
      <DialogTitle>Chat with {model.displayName} <Chip size="small" label="imported LoRA adapter" sx={{ ml: 1 }} /></DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Alert severity="info" data-testid="chat-framing">{FRAMING}</Alert>
          {prep && <Typography variant="body2">Preparing an endpoint for this model</Typography>}
          {ep && <Typography variant="caption" color="text.secondary" data-testid="chat-endpoint">Endpoint: {ep}</Typography>}
          <ServingBar />
          <Stack spacing={1} data-testid="chat-history">
            {hist.map((m, i) => <Alert key={i} severity={m.role === "user" ? "info" : "success"} icon={false}><Typography variant="caption" color="text.secondary">{m.role === "user" ? "You" : model.displayName}{m.meta ? ` (${m.meta} tokens)` : ""}</Typography><Typography sx={{ whiteSpace: "pre-wrap" }} data-testid={m.role === "model" ? "chat-answer" : undefined}>{m.text}</Typography></Alert>)}
          </Stack>
          {err && <Alert severity="error" data-testid="chat-error">{err.code === "UNAVAILABLE" ? "The model is not ready: " : ""}{err.message}</Alert>}
          <Stack direction="row" spacing={1}>
            <TextField size="small" fullWidth label="Message" value={msg} onChange={(e) => setMsg(e.target.value)} inputProps={{ "aria-label": "Message" }} onKeyDown={(e) => { if (e.key === "Enter" && msg.trim() && ep && !busy) send(); }} />
            <Button variant="contained" disabled={!msg.trim() || !ep || busy} onClick={() => send()}>Send</Button>
            <Button disabled={!ep || busy} onClick={() => send("Reply with OK.", 4)} data-testid="warm-up">Load into browser</Button>
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={() => onClose(false)}>Close</Button></DialogActions>
    </Dialog>
  );
}
