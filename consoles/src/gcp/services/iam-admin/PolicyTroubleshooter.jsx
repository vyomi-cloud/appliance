/* Policy Troubleshooter — the native policytroubleshooter v3 `iam:troubleshoot` call: the same faithful engine that enforces requests
 * (hierarchy inheritance, IAM conditions evaluated against the named resource, deny policies, PAB). */
import { useState } from "react";
import { Alert, Button, FormControlLabel, IconButton, Radio, RadioGroup, Stack, TextField } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
import { getProject } from "../../project.js";
import { useIamApi } from "../../../common/iamEnforceHooks.js";
import { normalizeMember } from "./pickers.jsx";
import * as api from "./api.js";

/* `projects/_/buckets/b/...` -> //storage.googleapis.com/...; `projects/p` and other CRM resources -> //cloudresourcemanager.googleapis.com/...; `//host/...` as typed. */
const fullResourceName = (r) => {
  const t = r.trim();
  if (t.startsWith("//")) return t;
  return t.startsWith("projects/_/buckets/") || t.startsWith("buckets/") ? `//storage.googleapis.com/${t.replace(/^buckets\//, "projects/_/buckets/")}` : `//cloudresourcemanager.googleapis.com/${t}`;
};

export default function PolicyTroubleshooter() {
  const notify = useNotify();
  const iam = useIamApi("gcp");
  const [mode, setMode] = useState("manual");
  const [principal, setPrincipal] = useState("");
  const [pairs, setPairs] = useState([{ resource: `projects/${getProject()}`, permission: "" }]);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const setPair = (i, field, v) => setPairs(pairs.map((p, j) => j === i ? { ...p, [field]: v } : p));
  const ok = principal.trim() && pairs.every((p) => p.resource.trim() && p.permission.trim());

  const check = async () => {
    setBusy(true); setResult(null);
    try {
      const outcomes = await Promise.all(pairs.map(async (p) => {
        const member = normalizeMember(principal);
        const r = await api.troubleshoot(member, fullResourceName(p.resource), p.permission);
        return { ...p, granted: r.overallAccessState === "CAN_ACCESS", state: r.overallAccessState };
      }));
      setResult(outcomes);
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Policy Troubleshooter" />
      <Section title="Select a way to troubleshoot">
        <RadioGroup row value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Troubleshoot" sx={{ mb: 2 }}>
          <FormControlLabel value="manual" control={<Radio size="small" />} label="Manual" />
          <FormControlLabel value="error" control={<Radio size="small" />} label="Error ID" />
        </RadioGroup>
        {mode === "error" && <Alert severity="info" sx={{ mb: 2 }}>Looking up a stored error ID isn't modeled in Vyomi; use Manual to evaluate access directly.</Alert>}
        <TextField required fullWidth sx={{ mb: 2, maxWidth: 480 }} label="Principal" value={principal} onChange={(e) => setPrincipal(e.target.value.trim())}
          helperText="e.g. user:dev@example.com" />
        {pairs.map((p, i) => (
          <Stack key={i} direction="row" spacing={1} sx={{ mb: 2 }} alignItems="flex-start">
            <TextField label={`Resource ${i + 1}`} value={p.resource} onChange={(e) => setPair(i, "resource", e.target.value)} sx={{ flex: 1 }}
              helperText="e.g. projects/my-project, projects/_/buckets/my-bucket/objects/key or //storage.googleapis.com/..." />
            <TextField label={`Permission ${i + 1}`} value={p.permission} onChange={(e) => setPair(i, "permission", e.target.value)} sx={{ flex: 1 }}
              helperText="e.g. storage.objects.get" />
            {pairs.length > 1 && <IconButton aria-label={`Remove pair ${i + 1}`} onClick={() => setPairs(pairs.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>}
          </Stack>
        ))}
        <Stack direction="row" spacing={1} sx={{ mb: 3 }}>
          <Button startIcon={<AddIcon />} onClick={() => setPairs([...pairs, { resource: `projects/${getProject()}`, permission: "" }])}>Add another pair</Button>
          <Button onClick={() => { setPrincipal(""); setPairs([{ resource: `projects/${getProject()}`, permission: "" }]); setResult(null); }}>Clear form</Button>
        </Stack>
        <Button variant="contained" disabled={!ok || busy} onClick={check}>{busy ? "Checking…" : "Check access"}</Button>
      </Section>
      {result && (
        <Section title="Result" description={result.every((r) => r.granted) ? "Access is granted." : "Access is denied for at least one permission."}>
          <Stack spacing={1}>
            {result.map((r, i) => (
              <Alert key={i} severity={r.granted ? "success" : "error"}>
                {r.granted ? "Granted" : "Denied"}: <code>{r.permission}</code> on <code>{r.resource}</code>{r.state ? ` (${r.state})` : ""}
              </Alert>
            ))}
          </Stack>
        </Section>
      )}
    </>
  );
}
