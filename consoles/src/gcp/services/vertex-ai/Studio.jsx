/* Vertex AI Studio: Gemini freeform prompt (generateContent + countTokens) and text embeddings, on the local model. */
import { useState } from "react";
import { Alert, Button, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

function ChatPanel() {
  const [model, setModel] = useState("gemini-2.0-flash");
  const [system, setSystem] = useState("");
  const [msg, setMsg] = useState("");
  const [hist, setHist] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [usage, setUsage] = useState(null);
  const send = async () => {
    const next = [...hist, { role: "user", text: msg }];
    setHist(next); setMsg(""); setBusy(true); setError(null);
    try {
      const r = await api.chat(model, next, system);
      setHist([...next, { role: "model", text: (r.candidates?.[0]?.content?.parts || []).map((p) => p.text).join("") }]);
      setUsage(r.usageMetadata);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Stack spacing={2} sx={{ maxWidth: 760 }}>
      <TextField select size="small" label="Model" value={model} onChange={(e) => setModel(e.target.value)}>{api.GEMINI.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}</TextField>
      <TextField size="small" label="System instructions" value={system} onChange={(e) => setSystem(e.target.value)} multiline minRows={2} />
      <Stack spacing={1} data-testid="chat-history">
        {hist.map((m, i) => (
          <Alert key={i} severity={m.role === "user" ? "info" : "success"} icon={false}>
            <Typography variant="caption" color="text.secondary">{m.role === "user" ? "You" : model}</Typography>
            <Typography sx={{ whiteSpace: "pre-wrap" }}>{m.text}</Typography>
          </Alert>
        ))}
        {!hist.length && <Typography variant="body2" color="text.secondary">Start a conversation. Earlier turns are sent with every message.</Typography>}
      </Stack>
      {error && <Alert severity="error">{error.code === "UNAVAILABLE" ? "The local model is not available: " : ""}{error.message}</Alert>}
      <Stack direction="row" spacing={1}>
        <TextField size="small" fullWidth label="Message" value={msg} onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && msg.trim() && !busy) send(); }} />
        <Button variant="contained" disabled={!msg.trim() || busy} onClick={send}>Send</Button>
        <Button disabled={!hist.length} onClick={() => { setHist([]); setUsage(null); }}>Clear</Button>
      </Stack>
      {usage && <Typography variant="caption" color="text.secondary">Last turn: {usage.promptTokenCount} input / {usage.candidatesTokenCount} output tokens</Typography>}
    </Stack>
  );
}

export default function Studio() {
  const [model, setModel] = useState("gemini-2.0-flash");
  const [system, setSystem] = useState("");
  const [prompt, setPrompt] = useState("Write a one-line greeting.");
  const [out, setOut] = useState(null);
  const [tokens, setTokens] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [embModel, setEmbModel] = useState("text-embedding-005");
  const [embText, setEmbText] = useState("hello world");
  const [emb, setEmb] = useState(null);
  const [embErr, setEmbErr] = useState(null);
  const run = async () => {
    setBusy(true); setError(null); setOut(null); setTokens(null);
    try { setOut(await api.generate(model, prompt, system)); setTokens((await api.countTokens(model, prompt)).totalTokens); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHeader title="Vertex AI Studio" />
      <Stack spacing={3}>
        <CapabilityContainer id="gcp.vertex-ai.gemini" title="Freeform prompt" description="generateContent against a Gemini publisher model. Every model id is served by the same small local model.">
          <Stack spacing={2} sx={{ maxWidth: 760 }}>
            <TextField select size="small" label="Model" value={model} onChange={(e) => setModel(e.target.value)}>{api.GEMINI.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}</TextField>
            <TextField size="small" label="System instructions" value={system} onChange={(e) => setSystem(e.target.value)} multiline minRows={2} />
            <TextField size="small" label="Prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} multiline minRows={3} />
            <div><Button variant="contained" disabled={!prompt || busy} onClick={run}>Submit</Button></div>
            {error && <Alert severity="error">{error.code === "UNAVAILABLE" ? "The local model is not available: " : ""}{error.message}</Alert>}
            {out && <Alert severity="success" icon={false}><Typography data-testid="gemini-output" sx={{ whiteSpace: "pre-wrap" }}>{out.candidates[0].content.parts.map((p) => p.text).join("")}</Typography>
              <Typography variant="caption" color="text.secondary">{out.usageMetadata.promptTokenCount} input / {out.usageMetadata.candidatesTokenCount} output tokens; countTokens: {tokens}; finish: {out.candidates[0].finishReason}</Typography></Alert>}
          </Stack>
        </CapabilityContainer>
        <CapabilityContainer id="gcp.vertex-ai.gemini" title="Chat" description="Multi-turn conversation: the full history is sent as role-tagged contents on every generateContent call.">
          <ChatPanel />
        </CapabilityContainer>
        <CapabilityContainer id="gcp.vertex-ai.embeddings" title="Text embeddings" description="embedContent on a text embedding model.">
          <Stack spacing={2} sx={{ maxWidth: 760 }}>
            <TextField select size="small" label="Embedding model" value={embModel} onChange={(e) => setEmbModel(e.target.value)}>{api.EMBED.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}</TextField>
            <TextField size="small" label="Text" value={embText} onChange={(e) => setEmbText(e.target.value)} />
            <div><Button variant="outlined" disabled={!embText} onClick={async () => { setEmbErr(null); setEmb(null); try { setEmb((await api.embed(embModel, embText)).embedding.values); } catch (e) { setEmbErr(e); } }}>Embed</Button></div>
            {embErr && <Alert severity="error">{embErr.message}</Alert>}
            {emb && <Alert severity="success" icon={false}><span data-testid="embedding-dim">{emb.length} dimensions</span>: [{emb.slice(0, 4).map((v) => v.toFixed(4)).join(", ")}, ...]</Alert>}
          </Stack>
        </CapabilityContainer>
      </Stack>
    </>
  );
}
