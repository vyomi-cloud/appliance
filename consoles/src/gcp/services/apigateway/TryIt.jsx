/* "Try it": pick a route, add an API key / bearer token, and send a REAL request through the gateway (the simulator's gateway data plane);
 * shows the status, headers and body the gateway answered. Also shows the invoke URLs and a copyable curl. */
import { useMemo, useState } from "react";
import { Alert, Box, Button, Chip, IconButton, MenuItem, Stack, TextField, Tooltip, Typography } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import SendIcon from "@mui/icons-material/esm/Send.js";
import { Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const copy = (t) => navigator.clipboard?.writeText(t).catch(() => {});
const Copyable = ({ label, value }) => (
  <TextField size="small" fullWidth label={label} value={value} inputProps={{ readOnly: true, "aria-label": label }}
    InputProps={{ endAdornment: <Tooltip title="Copy"><IconButton size="small" aria-label={`Copy ${label}`} onClick={() => copy(value)}><ContentCopyIcon fontSize="small" /></IconButton></Tooltip> }} />
);
const sample = (p) => p.replace(/\{[^}]+\}/g, "1");

export default function TryIt({ gateway, gid, routes, policy }) {
  const key = (policy?.securityDefinitions || []).find((s) => s.type === "apiKey");
  const jwt = (policy?.securityDefinitions || []).some((s) => s.type === "oauth2");
  const first = routes[0];
  const [sel, setSel] = useState(first ? first.operationId : "");
  const route = routes.find((r) => r.operationId === sel) || first;
  const [path, setPath] = useState(first ? sample(first.path) : "/");
  const [method, setMethod] = useState(first ? first.method : "GET");
  const [apiKey, setApiKey] = useState("");
  const [bearer, setBearer] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const base = api.invokeBase(gid);
  const pick = (id) => { setSel(id); const r = routes.find((x) => x.operationId === id); if (r) { setPath(sample(r.path)); setMethod(r.method); } };
  const req = useMemo(() => {
    const query = {}, headers = {};
    if (apiKey) { if (key?.in === "header") headers[key.keyName] = apiKey; else query[key?.keyName || "key"] = apiKey; }
    if (bearer) headers.authorization = `Bearer ${bearer}`;
    return { query, headers };
  }, [apiKey, bearer, key?.in, key?.keyName]);
  const url = base + (path.startsWith("/") ? path : "/" + path);
  const send = async () => {
    setBusy(true); setRes(null);
    try { setRes(await api.invoke(gid, method, path, { ...req, body: body || undefined })); }
    catch (e) { setRes({ error: String(e.message || e) }); } finally { setBusy(false); }
  };
  return (
    <>
      <Section title="Invoke URLs" description="Call the gateway like a client would.">
        <Stack spacing={1.5} sx={{ py: 1 }}>
          <Copyable label="Host-style URL (the real hostname; not resolvable on this machine)" value={api.hostBase(gateway.defaultHostname)} />
          <Copyable label="Path-style URL (works here, through the simulator's gateway)" value={base} />
          <Copyable label="curl" value={api.curlFor(url, method, { ...req, body })} />
        </Stack>
      </Section>
      <Section title="Try it" description="Sends a real request through the gateway: route match, API key / JWT checks, quota, then the backend.">
        {!routes.length ? <Typography variant="body2" color="text.secondary">This config defines no routes.</Typography> : (
          <Stack spacing={2} sx={{ py: 1, maxWidth: 820 }}>
            <Stack direction="row" spacing={1}>
              <TextField select size="small" label="Route" value={sel} onChange={(e) => pick(e.target.value)} sx={{ minWidth: 260 }} inputProps={{ "aria-label": "Route" }}>
                {routes.map((r) => <MenuItem key={r.operationId} value={r.operationId}>{r.method} {r.path}</MenuItem>)}</TextField>
              <TextField select size="small" label="Method" value={method} onChange={(e) => setMethod(e.target.value)} sx={{ width: 120 }} inputProps={{ "aria-label": "Method" }}>
                {["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}</TextField>
              <TextField size="small" label="Path" value={path} onChange={(e) => setPath(e.target.value)} fullWidth inputProps={{ "aria-label": "Path" }} />
            </Stack>
            <Stack direction="row" spacing={1}>
              <TextField size="small" label="API key" value={apiKey} onChange={(e) => setApiKey(e.target.value.trim())} fullWidth inputProps={{ "aria-label": "API key" }}
                helperText={key ? `Sent as ${key.in} "${key.keyName}"` : "Sent as the key query parameter"} />
              <TextField size="small" label="Bearer token" value={bearer} onChange={(e) => setBearer(e.target.value.trim())} fullWidth inputProps={{ "aria-label": "Bearer token" }}
                helperText={jwt ? "For oauth2 / JWT security" : "Optional"} />
            </Stack>
            {!["GET", "HEAD"].includes(method) && <TextField size="small" label="Request body" value={body} onChange={(e) => setBody(e.target.value)} multiline minRows={2} inputProps={{ "aria-label": "Request body" }} />}
            <Box><Button variant="contained" startIcon={<SendIcon />} disabled={busy} onClick={send}>{busy ? "Sending…" : "Send request"}</Button>
              {route && <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>Backend: {route.backend}</Typography>}</Box>
            {res?.error && <Alert severity="error">{res.error}</Alert>}
            {res && !res.error && (
              <Box data-testid="tryit-response">
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                  <Chip data-testid="tryit-status" size="small" color={res.status < 300 ? "success" : res.status < 500 ? "warning" : "error"} label={`HTTP ${res.status}`} />
                  <Typography variant="caption" color="text.secondary">{res.ms} ms</Typography></Stack>
                <Typography variant="subtitle2">Response headers</Typography>
                <Box component="pre" sx={{ m: 0, mb: 1, p: 1, bgcolor: "action.hover", borderRadius: 1, fontSize: 12, overflow: "auto" }}>{Object.entries(res.headers).map(([k, v]) => `${k}: ${v}`).join("\n")}</Box>
                <Typography variant="subtitle2">Response body</Typography>
                <Box component="pre" data-testid="tryit-body" sx={{ m: 0, p: 1, bgcolor: "action.hover", borderRadius: 1, fontSize: 12, overflow: "auto", maxHeight: 320 }}>{res.text || "(empty)"}</Box>
              </Box>)}
          </Stack>)}
      </Section>
    </>
  );
}
