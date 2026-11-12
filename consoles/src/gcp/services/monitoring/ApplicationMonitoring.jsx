/* Application monitoring over core/gcp_apphub_core (App Hub v1): applications, and the Cloud Run services / managed instance
 * groups the project actually has, registered into them. No APM telemetry backs it (see the capability text). */
import { useState } from "react";
import { Box, Button, Chip, Stack, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { restJson } from "../../../common/wire.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { getProject, useProject } from "../../project.js";
import { FormDialog } from "../compute/Ext.jsx";

const e = encodeURIComponent;
const hub = (loc) => `/v1/projects/${e(getProject())}/locations/${e(loc)}`;
const last = (v) => String(v || "").split("/").pop();
const locOf = (name) => name.split("/")[3];
const aid = (name) => name.split("/")[5];
export const listApplications = async () => (await restJson("GET", `${hub("-")}/applications`)).applications || [];
const createApplication = (loc, id, body) => restJson("POST", `${hub(loc)}/applications`, { query: { applicationId: id }, body });
const deleteApplication = (name) => restJson("DELETE", `/v1/${name}`);
const listChildren = async (app, kind) => (await restJson("GET", `/v1/${app}/${kind}`))[kind] || [];
const listDiscovered = async (loc, kind) => (await restJson("GET", `${hub(loc)}/discovered${kind === "services" ? "Services" : "Workloads"}`))[`discovered${kind === "services" ? "Services" : "Workloads"}`] || [];
const register = (app, kind, id, body) => restJson("POST", `/v1/${app}/${kind}`, { query: { [kind === "services" ? "serviceId" : "workloadId"]: id }, body });
const unregister = (name) => restJson("DELETE", `/v1/${name}`);

const REGIONS = ["us-central1", "us-east1", "europe-west1", "asia-southeast1"].map((r) => [r, r]);
const CRIT = ["MISSION_CRITICAL", "HIGH", "MEDIUM", "LOW"].map((c) => [c, c.replace("_", " ")]);
const ENV = ["PRODUCTION", "STAGING", "TEST", "DEVELOPMENT"].map((c) => [c, c[0] + c.slice(1).toLowerCase()]);

function Children({ app, kind }) {
  const notify = useNotify();
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState([]);
  const { data = [], loading, error, reload } = useAsync(() => listChildren(app.name, kind), [app.name, kind]);
  const { data: disc = [] } = useAsync(() => listDiscovered(locOf(app.name), kind), [app.name, kind, data.length]);
  const taken = new Set(data.map((c) => c.discoveredService || c.discoveredWorkload));
  const free = disc.filter((d) => !taken.has(d.name));
  const ref = (d) => d.serviceReference?.uri || d.workloadReference?.uri;
  return (
    <Section title={kind === "services" ? "Services" : "Workloads"}>
      <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
        <Button startIcon={<AddIcon />} disabled={!free.length} onClick={() => setOpen(true)}>{kind === "services" ? "Register service" : "Register workload"}</Button>
        <Button startIcon={<DeleteIcon />} disabled={!sel.length} onClick={async () => { for (const n of sel) await unregister(n); notify.success("Unregistered"); setSel([]); reload(); }}>Unregister</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </Stack>
      <ResourceTable resourceName={kind} items={data} loading={loading} error={error} onRetry={reload} selectable selected={sel} onSelectedChange={setSel} rowKey={(c) => c.name}
        columns={[
          { id: "n", header: "Name", cell: (c) => last(c.name) },
          { id: "r", header: "Resource", cell: (c) => ref(c) },
          { id: "l", header: "Location", cell: (c) => (c.serviceProperties || c.workloadProperties).location },
          { id: "e", header: "Environment", cell: (c) => c.attributes?.environment?.type || "—" },
        ]}
        empty={<Typography variant="body2" color="text.secondary">{free.length ? `Nothing registered. ${free.length} discovered ${kind} can be registered.` : `No ${kind} discovered in ${locOf(app.name)}. Deploy a ${kind === "services" ? "Cloud Run service" : "managed instance group"} in that region first.`}</Typography>} />
      <FormDialog open={open} title={kind === "services" ? "Register service" : "Register workload"} onClose={() => setOpen(false)}
        fields={[
          { key: "id", label: "Name", required: true, default: free[0] ? last(free[0].name).replace(/^(run|mig)-/, "") : "" },
          { key: "d", label: "Discovered resource", options: free.map((d) => [d.name, ref(d)]), default: free[0]?.name || "" },
          { key: "env", label: "Environment", options: [["", "None"], ...ENV], default: "" },
        ]}
        onSubmit={async (v) => { await register(app.name, kind, v.id, { [kind === "services" ? "discoveredService" : "discoveredWorkload"]: v.d, ...(v.env ? { attributes: { environment: { type: v.env } } } : {}) }); notify.success("Registered"); reload(); }} />
    </Section>
  );
}

export default function ApplicationMonitoring() {
  const notify = useNotify();
  const project = useProject();
  const [open, setOpen] = useState(false);
  const [cur, setCur] = useState(null);
  const { data = [], loading, error, reload } = useAsync(listApplications, [project]);
  const selected = data.find((a) => a.name === cur);
  return (
    <>
      <PageHeader title="Application monitoring" actions={<>
        <Button startIcon={<AddIcon />} onClick={() => setOpen(true)}>Create application</Button>
        <Button startIcon={<DeleteIcon />} disabled={!selected} onClick={async () => { try { await deleteApplication(selected.name); notify.success("Application deleted"); setCur(null); reload(); } catch (err) { notify.error?.(err.message); } }}>Delete</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <CapabilityContainer id="gcp.monitoring.application-monitoring" title="Applications">
        <ResourceTable resourceName="applications" items={data} loading={loading} error={error} onRetry={reload} rowKey={(a) => a.name}
          selectable selected={cur ? [cur] : []} onSelectedChange={(s) => setCur(s[s.length - 1] || null)}
          columns={[
            { id: "n", header: "Application", sortField: "displayName", cell: (a) => <Button size="small" onClick={() => setCur(a.name)}>{a.displayName || aid(a.name)}</Button> },
            { id: "l", header: "Location", cell: (a) => locOf(a.name) },
            { id: "c", header: "Criticality", cell: (a) => a.attributes?.criticality?.type || "—" },
            { id: "e", header: "Environment", cell: (a) => a.attributes?.environment?.type || "—" },
            { id: "s", header: "State", cell: (a) => <Chip size="small" color="success" label={a.state} /> },
          ]}
          empty={<Typography variant="body2" color="text.secondary">No applications. Create one to group the services and workloads of an app.</Typography>} />
        {selected && <Box sx={{ mt: 2 }}><Stack spacing={2}><Children app={selected} kind="services" /><Children app={selected} kind="workloads" /></Stack></Box>}
      </CapabilityContainer>
      <FormDialog open={open} title="Create application" onClose={() => setOpen(false)}
        fields={[
          { key: "id", label: "Application ID", required: true }, { key: "dn", label: "Display name" },
          { key: "loc", label: "Region", options: REGIONS, default: "us-central1" },
          { key: "crit", label: "Criticality", options: [["", "Not set"], ...CRIT], default: "" },
          { key: "env", label: "Environment", options: [["", "Not set"], ...ENV], default: "" },
        ]}
        onSubmit={async (v) => { await createApplication(v.loc, v.id, { displayName: v.dn || undefined, scope: { type: "REGIONAL" },
          attributes: { ...(v.crit ? { criticality: { type: v.crit } } : {}), ...(v.env ? { environment: { type: v.env } } : {}) } }); notify.success(`Created application "${v.id}"`); reload(); }} />
    </>
  );
}
