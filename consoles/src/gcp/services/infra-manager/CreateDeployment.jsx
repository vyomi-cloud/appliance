/* Create deployment / Update deployment (same form): name, region, service account, Terraform source, input variables, labels.
 * Source = this project's Vyomi export, pasted or uploaded Terraform, or an object in the simulator's Cloud Storage.
 * "Preview" runs a preview and shows the plan; "Create"/"Update" applies it. */
import { useEffect, useState } from "react";
import { Alert, Box, Button, IconButton, MenuItem, Radio, RadioGroup, FormControlLabel, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { getProject, useProject } from "../../project.js";
import * as iam from "../iam-admin/api.js";
import * as api from "./api.js";
import { exportProject } from "./tfgcp.js";
import { PlanBody } from "./PlanView.jsx";

const DEP_ID = /^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$/;

function KvRows({ rows, setRows, kLabel, vLabel }) {
  return (
    <Stack spacing={1}>
      {rows.map((r, i) => (
        <Stack direction="row" spacing={1} key={i}>
          <TextField size="small" label={kLabel} value={r.k} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))} />
          <TextField size="small" label={vLabel} value={r.v} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))} sx={{ flex: 1 }} />
          <IconButton aria-label="Remove" onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon /></IconButton>
        </Stack>
      ))}
      <Box><Button size="small" startIcon={<AddIcon />} onClick={() => setRows([...rows, { k: "", v: "" }])}>Add</Button></Box>
    </Stack>
  );
}

export default function CreateDeployment({ params }) {
  const editing = !!params?.name;
  const region0 = params?.region, name0 = params?.name;
  const notify = useNotify();
  const project = useProject();
  const sas = useAsync(() => iam.listServiceAccounts().catch(() => []), [project]);
  const dep = useAsync(() => (editing ? api.getDeployment(region0, name0) : Promise.resolve(null)), [region0, name0]);
  const [name, setName] = useState(name0 || ""), [region, setRegion] = useState(region0 || "us-central1");
  const [sa, setSa] = useState(""), [kind, setKind] = useState("vyomi"), [gcs, setGcs] = useState("");
  const [files, setFiles] = useState(null), [pasted, setPasted] = useState(""), [vars, setVars] = useState([]), [labels, setLabels] = useState([]);
  const [busy, setBusy] = useState(false), [err, setErr] = useState(null), [touched, setTouched] = useState(false), [preview, setPreview] = useState(null), [genNote, setGenNote] = useState("");

  useEffect(() => { const h = api.handoff.take(); if (h) { setFiles(h); setKind("vyomi"); setGenNote(`${Object.keys(h).length} files from the project export`); } }, []);
  useEffect(() => { if (dep.data) { setSa((dep.data.serviceAccount || "").split("/").pop()); setLabels(Object.entries(dep.data.labels || {}).map(([k, v]) => ({ k, v }))); } }, [dep.data]);

  const generate = async () => { setBusy(true); setErr(null); try { const r = await exportProject(getProject()); setFiles(r.files); setGenNote(`${r.count} resources, ${Object.keys(r.files).length} files generated from this project`); } catch (e) { setErr(e); } finally { setBusy(false); } };
  const upload = async (ev) => { const f = ev.target.files?.[0]; if (f) setPasted(await f.text()); };
  const source = () => (kind === "gcs" ? { kind: "gcs", gcs } : kind === "paste" ? { kind: "files", files: { "main.tf": pasted } } : { kind: "files", files });
  const sourceErr = kind === "gcs" ? (/^gs:\/\/[^/]+\/.+/.test(gcs) ? "" : "Enter gs://bucket/path/main.tf") : kind === "paste" ? (pasted.trim() ? "" : "Paste or upload Terraform") : (files ? "" : "Generate the export first");
  const nameErr = editing ? "" : !DEP_ID.test(name) ? "Lowercase letters, digits and hyphens; must start with a letter" : "";
  const saErr = sa.trim() ? "" : "Required: Terraform runs as this service account";
  const saFull = () => (sa.includes("/") ? sa : `projects/${getProject()}/serviceAccounts/${sa.includes("@") ? sa : `${sa}@${getProject()}.iam.gserviceaccount.com`}`);
  const bad = nameErr || saErr || sourceErr;
  const labelObj = Object.fromEntries(labels.filter((l) => l.k).map((l) => [l.k, l.v]));

  const doPreview = async () => {
    setTouched(true); if (bad) return;
    setBusy(true); setErr(null); setPreview(null);
    try {
      const r = await api.createPreview(region, `pv-${(name || "x").slice(0, 20)}-${Date.now().toString(36)}`.replace(/[^a-z0-9-]/g, "-"),
        { serviceAccount: saFull(), terraformBlueprint: api.blueprint(source(), vars), ...(editing ? { deployment: `projects/${getProject()}/locations/${region}/deployments/${name}` } : {}) });
      setPreview(r);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const submit = async () => {
    setTouched(true); if (bad) return;
    setBusy(true); setErr(null);
    try {
      if (editing) { await api.updateDeployment(region, name, { terraformBlueprint: api.blueprint(source(), vars), labels: labelObj, serviceAccount: saFull() }, "terraformBlueprint,labels,serviceAccount"); notify.success(`Deployment ${name} updated`); }
      else { await api.createDeployment(region, name, { serviceAccount: saFull(), labels: labelObj, terraformBlueprint: api.blueprint(source(), vars) }); notify.success(`Deployment ${name} created`); }
      location.hash = `#/infra-manager/deployments/${region}/${name}`;
    } catch (e) { setErr(e); setBusy(false); }
  };

  return (
    <>
      <PageHeader title={editing ? `Update ${name0}` : "Create deployment"} back={<IconButton aria-label="Back" href={editing ? `#/infra-manager/deployments/${region0}/${name0}` : "#/infra-manager"}><ArrowBackIcon /></IconButton>} />
      <Stack spacing={3} sx={{ maxWidth: 820 }}>
        {err && <ErrorAlert error={err} title="Request failed" />}
        <Section title="Deployment details">
          <Stack spacing={2.5} sx={{ p: 2 }}>
            <TextField label="Deployment name" required disabled={editing} value={name} onChange={(e) => setName(e.target.value)} error={touched && !!nameErr} helperText={touched && nameErr ? nameErr : "Permanent. Used in the deployment's resource name."} />
            <TextField select label="Region" disabled={editing} value={region} onChange={(e) => setRegion(e.target.value)}>{api.REGIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}</TextField>
            <TextField label="Service account" required value={sa} onChange={(e) => setSa(e.target.value)} error={touched && !!saErr}
              helperText={touched && saErr ? saErr : "Infrastructure Manager runs Terraform as this service account (name or email)."}
              inputProps={{ list: "im-sas" }} />
            <datalist id="im-sas">{(sas.data || []).map((s) => <option key={s.email} value={s.email} />)}</datalist>
          </Stack>
        </Section>
        <Section title="Terraform configuration">
          <Stack spacing={2} sx={{ p: 2 }}>
            <RadioGroup value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Terraform source">
              <FormControlLabel value="vyomi" control={<Radio />} label="Export of this project (Vyomi)" />
              <FormControlLabel value="paste" control={<Radio />} label="Paste or upload a Terraform file" />
              <FormControlLabel value="gcs" control={<Radio />} label="Cloud Storage object" />
            </RadioGroup>
            {kind === "vyomi" && (
              <Stack spacing={1}>
                <Box><Button variant="outlined" onClick={generate} disabled={busy}>{files ? "Regenerate from this project" : "Generate from this project"}</Button></Box>
                {genNote && <Typography variant="body2" color="text.secondary" data-testid="gen-note">{genNote}</Typography>}
              </Stack>
            )}
            {kind === "paste" && (
              <Stack spacing={1}>
                <Box><Button component="label" size="small" variant="outlined">Upload .tf file<input hidden type="file" accept=".tf,text/plain" onChange={upload} /></Button></Box>
                <TextField multiline minRows={10} maxRows={22} label="main.tf" value={pasted} onChange={(e) => setPasted(e.target.value)} inputProps={{ "data-testid": "tf-paste", style: { fontFamily: "monospace", fontSize: 12 } }} />
              </Stack>
            )}
            {kind === "gcs" && <TextField label="Cloud Storage path" placeholder="gs://my-bucket/main.tf" value={gcs} onChange={(e) => setGcs(e.target.value)} helperText="Read from this simulator's own Cloud Storage. Git repositories are not fetched (no network access)." />}
            {touched && sourceErr && <Alert severity="error">{sourceErr}</Alert>}
          </Stack>
        </Section>
        <Section title="Input variables"><Box sx={{ p: 2 }}><KvRows rows={vars} setRows={setVars} kLabel="Variable" vLabel="Value" /></Box></Section>
        <Section title="Labels"><Box sx={{ p: 2 }}><KvRows rows={labels} setRows={setLabels} kLabel="Key" vLabel="Value" /></Box></Section>
        {preview && <Section title={`Preview ${preview.name.split("/").pop()}`}><Box sx={{ p: 2 }}><PlanBody preview={preview} /></Box></Section>}
        <Stack direction="row" spacing={1}>
          <Button variant="contained" onClick={submit} disabled={busy} data-testid="im-submit">{editing ? "Update" : "Create"}</Button>
          <Button variant="outlined" onClick={doPreview} disabled={busy} data-testid="im-preview">Preview</Button>
          <Button href={editing ? `#/infra-manager/deployments/${region0}/${name0}` : "#/infra-manager"}>Cancel</Button>
        </Stack>
      </Stack>
    </>
  );
}
