/* Effective access (Policy Troubleshooter style): principal + permission + resource -> POST /api/iam/gcp/evaluate ->
 * granted/denied, reason, and the matching allow/deny bindings. Sits beside the Policy Troubleshooter (testIamPermissions). */
import { useEffect, useState } from "react";
import { Alert, Button, Chip, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from "@mui/material";
import { reasonText } from "../../../common/iamEnforce.js";
import { useIamApi } from "../../../common/iamEnforceHooks.js";
import { PageHeader, Section } from "../../kit/common.jsx";
import { getProject } from "../../project.js";
import { PermissionAutocomplete, PrincipalPicker, ResourceAutocomplete } from "./pickers.jsx";
import { usePickerData } from "./usePickerData.js";
import * as iamApi from "./api.js";

export default function EffectiveAccess() {
  const api = useIamApi("gcp");
  const data = usePickerData({ withPrincipals: true });
  const [principals, setPrincipals] = useState([]);
  const principal = principals[0] || "";
  const [perm, setPerm] = useState("");
  const [resource, setResource] = useState(`//cloudresourcemanager.googleapis.com/projects/${getProject()}`);
  const [buckets, setBuckets] = useState([]);
  useEffect(() => { iamApi.searchAssets("", { assetTypes: "storage.googleapis.com/Bucket" }).then((r) => setBuckets(r.map((x) => x.name).filter(Boolean)), () => {}); }, []);
  const resourceOptions = [`//cloudresourcemanager.googleapis.com/projects/${getProject()}`, ...data.principals.filter((p) => p.member.startsWith("serviceAccount:")).map((p) => `//iam.googleapis.com/projects/${getProject()}/serviceAccounts/${p.member.slice(15)}`), ...buckets];
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setErr(null); setRes(null);
    try { const m = /^(user|serviceAccount|group|domain):/.test(principal) ? principal : `user:${principal}`; setRes(await api.evaluate({ principal: { member: m }, action: perm.trim(), resource: resource.trim() })); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <>
      <PageHeader title="Effective access" />
      <Stack spacing={2}>
        <Section title="Check a permission" description="Evaluated by the same engine that enforces requests: allow policies with inheritance, deny policies and conditions.">
          <Stack spacing={2} sx={{ maxWidth: 640 }}>
            <PrincipalPicker label="Principal" value={principals} onChange={(v) => setPrincipals(v.slice(-1))} options={data.principals} />
            <PermissionAutocomplete value={perm} onChange={setPerm} permissions={data.permissions} />
            <ResourceAutocomplete value={resource} onChange={setResource} options={resourceOptions} />
            <div><Button variant="contained" disabled={!principal || !perm || busy} onClick={run}>{busy ? "Checking…" : "Check access"}</Button></div>
          </Stack>
        </Section>
        {err && <Alert severity="error">Evaluation failed: {err.message}</Alert>}
        {res && (
          <Section title="Result"><div data-testid="iam-eval-result"><Stack spacing={1.5}>
            <Stack direction="row" spacing={1} alignItems="center"><Chip color={res.allowed ? "success" : "error"} label={res.allowed ? "Granted" : "Denied"} /><Typography variant="body2">{reasonText(res)}</Typography></Stack>
            {(res.matched || []).length === 0 ? <Typography variant="body2" color="text.secondary">No binding matched (implicit deny).</Typography> :
              <Table size="small"><TableHead><TableRow><TableCell>Policy type</TableCell><TableCell>Binding</TableCell><TableCell>Effect</TableCell><TableCell>Details</TableCell></TableRow></TableHead>
                <TableBody>{res.matched.map((m, i) => (
                  <TableRow key={i}><TableCell>{m.source}</TableCell><TableCell>{m.id}</TableCell><TableCell>{m.effect}</TableCell>
                    <TableCell sx={{ fontFamily: "monospace", wordBreak: "break-all" }}>{JSON.stringify(m.statement || {})}</TableCell></TableRow>))}</TableBody></Table>}
          </Stack></div></Section>
        )}
      </Stack>
    </>
  );
}
