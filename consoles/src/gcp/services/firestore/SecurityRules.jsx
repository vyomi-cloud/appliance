/* Security rules — Rules editor (stored and returned verbatim) and a real Development &
 * test (Rules Playground) tab: Simulate really parses and evaluates the rules text (saved
 * or an unsaved draft) against one simulated request. See the capability badge for what
 * still always bypasses rules (the native wire's actual document reads/writes). */
import { useState } from "react";
import {
  Box, Button, Checkbox, Chip, FormControl, FormControlLabel, InputLabel, MenuItem, Paper,
  Select, Stack, Tab, Tabs, TextField, Typography,
} from "@mui/material";
import PlayArrowIcon from "@mui/icons-material/esm/PlayArrow.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const TABS = [["rules", "Rules"], ["test", "Development & test"]];

export default function SecurityRules({ params, query }) {
  const db = params.name;
  const tab = TABS.some(([t]) => t === query.tab) ? query.tab : "rules";
  const { data, loading, error, reload } = useAsync(() => api.getSecurityRules(db), [db]);
  const [draft, setDraft] = useState(null);
  const value = draft ?? data ?? "";

  return (
    <>
      <PageHeader title="Security rules" />
      <Tabs value={tab} onChange={(_, t) => { location.hash = `#/firestore/databases/${encodeURIComponent(db)}/rules${t === "rules" ? "" : "?tab=" + t}`; }}
        sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Security rules tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      {tab === "rules" ? (
        <RulesEditor db={db} value={value} loading={loading} error={error} onChange={setDraft} onPublished={reload} />
      ) : (
        <DevTest db={db} rules={value || api.DEFAULT_RULES} />
      )}
    </>
  );
}

function RulesEditor({ db, value, loading, error, onChange, onPublished }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);

  const publish = async () => {
    setBusy(true);
    try {
      await api.updateSecurityRules(db, value);
      notify.success(`Rules published.${saveNotice("gcp.firestore.security-rules")}`);
      onPublished();
    } catch (e) { notify.error(e); }
    finally { setBusy(false); }
  };

  return (
    <CapabilityContainer id="gcp.firestore.security-rules" title="Rules" actions={<Button variant="contained" disabled={busy || loading} onClick={publish}>{busy ? "Publishing…" : "Publish"}</Button>}>
      <ErrorAlert error={error} title="Failed to load rules" />
      <Box sx={{ mt: 1 }}>
        <TextField
          multiline fullWidth minRows={14} value={value} onChange={(e) => onChange(e.target.value)}
          inputProps={{ "aria-label": "Rules editor", style: { fontFamily: "monospace", fontSize: 13 } }}
          placeholder={api.DEFAULT_RULES}
        />
      </Box>
      <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
        <Button size="small" onClick={() => onChange(api.DEFAULT_RULES)}>Reset to restrictive default</Button>
      </Stack>
    </CapabilityContainer>
  );
}

const SIMULATION_TYPES = [
  ["get", "Get a document"],
  ["list", "List a collection"],
  ["create", "Create a document"],
  ["update", "Update a document"],
  ["delete", "Delete a document"],
];

function DevTest({ db, rules }) {
  const [op, setOp] = useState("get");
  const [path, setPath] = useState("users/alice");
  const [authed, setAuthed] = useState(false);
  const [uid, setUid] = useState("user123");
  const [resourceData, setResourceData] = useState("{}");
  const [requestData, setRequestData] = useState("{}");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const run = async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      let resourceJson = {}, requestJson = {};
      try { resourceJson = JSON.parse(resourceData || "{}"); } catch { throw new Error("Existing resource data must be valid JSON"); }
      try { requestJson = JSON.parse(requestData || "{}"); } catch { throw new Error("Request resource data must be valid JSON"); }
      const r = await api.testSecurityRules(db, {
        rules,
        request: {
          method: op, path, auth: authed ? { uid } : null,
          resourceData: op === "create" ? null : resourceJson,
          requestResourceData: (op === "create" || op === "update") ? requestJson : null,
        },
      });
      setResult(r);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <CapabilityContainer id="gcp.firestore.security-rules" title="Development & test">
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Simulate a request against the rules shown in the Rules tab, including unsaved edits.
      </Typography>
      <ErrorAlert error={error} title="Simulation failed" />
      <Stack spacing={2} sx={{ maxWidth: 480 }}>
        <FormControl><InputLabel id="dt-op">Simulation type</InputLabel>
          <Select labelId="dt-op" label="Simulation type" value={op} onChange={(e) => setOp(e.target.value)}>
            {SIMULATION_TYPES.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <TextField label="Location" value={path} onChange={(e) => setPath(e.target.value)}
          helperText="Path to the document, e.g. users/alice" inputProps={{ "aria-label": "Location" }} />
        <FormControlLabel control={<Checkbox checked={authed} onChange={(e) => setAuthed(e.target.checked)} />} label="Authenticated" />
        {authed && <TextField label="Firebase UID" value={uid} onChange={(e) => setUid(e.target.value)} />}
        {(op === "create" || op === "update") && (
          <TextField label="Request resource data (JSON)" multiline minRows={3} value={requestData} onChange={(e) => setRequestData(e.target.value)}
            inputProps={{ style: { fontFamily: "monospace", fontSize: 13 } }} />
        )}
        {op !== "create" && (
          <TextField label="Existing resource data (JSON)" multiline minRows={3} value={resourceData} onChange={(e) => setResourceData(e.target.value)}
            inputProps={{ style: { fontFamily: "monospace", fontSize: 13 } }} />
        )}
        <Box><Button variant="contained" startIcon={<PlayArrowIcon />} disabled={busy} onClick={run}>{busy ? "Running…" : "Run"}</Button></Box>
        {result && (
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Chip color={result.allow ? "success" : "error"} sx={{ mb: 1 }}
              label={result.allow ? "Simulated read/write allowed" : "Simulated read/write denied"} />
            {result.matchedPath && <Typography variant="body2" color="text.secondary">Matched rule: <code>{result.matchedPath}</code></Typography>}
            {result.error && <Typography variant="body2" color="error">{result.error}</Typography>}
          </Paper>
        )}
      </Stack>
    </CapabilityContainer>
  );
}
