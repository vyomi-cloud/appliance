/* Container Apps Environment resource blade: left resource menu + panels. Overview, Activity
 * log, Access control (IAM), Tags, Dapr components, Certificates, Workload profiles, Networking,
 * Diagnostic settings, Export template and Locks are backed by native ARM calls
 * (core/azure_app_core.py); everything else renders its honest capability level. */
import { useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, Loading, NotSimulatedContainer } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { AccessControlIam, ActivityLog, DiagnosticSettings, ExportTemplate, Locks, MiniTable, Tags } from "./Shared.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Settings", items: [
    { id: "daprcomponents", label: "Dapr components" },
    { id: "certificates", label: "Certificates" },
    { id: "workloadprofiles", label: "Workload profiles" },
    { id: "networking", label: "Networking" },
    { id: "logs", label: "Logs" },
    { id: "locks", label: "Locks" },
  ] },
  { group: "Monitoring", items: [{ id: "diagnosticsettings", label: "Diagnostic settings" }] },
  { group: "Automation", items: [{ id: "exporttemplate", label: "Export template" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const CAP_ID = "azure.containerapps.environment.tools";

export default function EnvironmentBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const env = useAsync(() => api.getEnvironment(rg, name), [rg, name, panel]);
  const self = `#/containerapps/environments/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  const resPath = env.data ? api.ENVIRONMENTS.path(rg, name) : null;
  useEffect(() => { if (env.data) remember({ name, type: "Container Apps Environment", href: self }); }, [!!env.data, self]);

  let body;
  if (env.loading && !env.data) body = <Loading />;
  else if (env.error) body = <><ErrorBar error={env.error} title="Failed to load the environment" /><Link href="#/containerapps/environments">Back to Container Apps Environments</Link></>;
  else {
    const a = env.data, reload = env.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      activitylog: () => <ActivityLog resPath={resPath} name={a.name} />,
      iam: () => <AccessControlIam resPath={resPath} name={a.name} capId="azure.containerapps.iam" />,
      tags: () => <Tags a={a} name={a.name} reload={reload} save={(tags) => api.updateEnvironmentTags(rg, a.name, tags, a)} />,
      daprcomponents: () => <DaprComponents rg={rg} name={a.name} />,
      certificates: () => <Certificates rg={rg} name={a.name} />,
      workloadprofiles: () => <WorkloadProfiles a={a} rg={rg} name={a.name} reload={reload} />,
      networking: () => <Networking a={a} />,
      locks: () => <Locks resPath={resPath} name={a.name} />,
      diagnosticsettings: () => <DiagnosticSettings resPath={resPath} name={a.name} />,
      exporttemplate: () => <ExportTemplate a={a} name={a.name} type="Microsoft.App/managedEnvironments" />,
    }[panel];
    body = P ? P() : <CapabilityContainer id={CAP_ID} title={`${a.name} | ${LABEL[panel] || panel}`} />;
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Container Apps Environment"
      glyph={<Glyph id="containerapps" />} closeHref="#/containerapps/environments"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

function useAppRows(rg, envId) {
  return useAsync(async () => (await api.listApps()).filter((x) => x.resourceGroup === rg && (x.properties?.managedEnvironmentId || "").toLowerCase() === envId.toLowerCase()), [rg, envId]);
}
function useJobRows(rg, envId) {
  return useAsync(async () => (await api.listJobs()).filter((x) => x.resourceGroup === rg && (x.properties?.environmentId || "").toLowerCase() === envId.toLowerCase()), [rg, envId]);
}

function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [del, setDel] = useState(false);
  const apps = useAppRows(a.resourceGroup, a.id);
  const jobs = useJobRows(a.resourceGroup, a.id);
  const p = a.properties || {};
  const tags = Object.entries(a.tags || {});
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { reload(); apps.reload(); jobs.reload(); }}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
          ["Provisioning state", p.provisioningState],
        ]}
        right={[
          ["Default domain", p.defaultDomain],
          ["Static IP", p.staticIp],
          ["Zone redundant", p.zoneRedundant ? "Yes" : "No"],
          ["Infrastructure resource group", p.infrastructureResourceGroup],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <section className="vy-section" style={{ marginTop: 12 }}><h3>Container Apps</h3>
        <MiniTable columns={["Name", "Status", "Location"]} empty="No container apps in this environment"
          rows={(apps.data || []).map((r) => (
            <tr key={r.name}>
              <td><Link href={`#/containerapps/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link></td>
              <td>{r.properties?.runningStatus}</td>
              <td>{locationLabel(r.location)}</td>
            </tr>
          ))} />
      </section>
      <section className="vy-section"><h3>Container Apps Jobs</h3>
        <MiniTable columns={["Name", "Trigger type", "Location"]} empty="No container apps jobs in this environment"
          rows={(jobs.data || []).map((r) => (
            <tr key={r.name}>
              <td><Link href={`#/containerapps/jobs/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link></td>
              <td>{r.properties?.configuration?.triggerType}</td>
              <td>{locationLabel(r.location)}</td>
            </tr>
          ))} />
      </section>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="container apps environment" names={[a.name]}
        onConfirm={async () => {
          await api.deleteEnvironment(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Environment '${a.name}' was deleted.`, "Delete succeeded");
          navigate("containerapps", "environments");
        }} />
    </>
  );
}

function DaprComponents({ rg, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDaprComponents(rg, name), [rg, name]);
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", componentType: "state.redis" });
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try { await api.putDaprComponent(rg, name, f.name, { properties: { componentType: f.componentType } }); notify.success(`Dapr component '${f.name}' was created.`, "Save succeeded"); setAdding(false); setF({ name: "", componentType: "state.redis" }); reload(); }
    catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Dapr components</div>
      <BrowseGrid
        resourceName="Dapr component" items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => setAdding(true)}
        onDelete={async (rows) => { for (const r of rows) await api.deleteDaprComponent(rg, name, r.name); notify.success("Dapr component(s) deleted.", "Delete succeeded"); reload(); }}
        columns={[{ key: "name", label: "Component name" }, { key: "type", label: "Component type", value: (r) => r.properties?.componentType }, { key: "version", label: "Version", value: (r) => r.properties?.version }]}
      />
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Create Dapr component">
          <DialogBody>
            <DialogTitle>Create Dapr component</DialogTitle>
            <DialogContent>
              <Field label="Component name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} /></Field>
              <Field label="Component type" required>
                <Select value={f.componentType} onChange={(_, d) => setF((x) => ({ ...x, componentType: d.value }))} aria-label="Component type">
                  <option value="state.redis">state.redis</option><option value="pubsub.redis">pubsub.redis</option>
                  <option value="secretstores.azure.keyvault">secretstores.azure.keyvault</option><option value="bindings.http">bindings.http</option>
                </Select>
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!f.name || busy} onClick={create}>{busy ? "Creating..." : "Create"}</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function Certificates({ rg, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listCertificates(rg, name), [rg, name]);
  const [adding, setAdding] = useState(false);
  const [certName, setCertName] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try { await api.putCertificate(rg, name, certName, { properties: {} }); notify.success(`Certificate '${certName}' was uploaded.`, "Upload succeeded"); setAdding(false); setCertName(""); reload(); }
    catch (e) { notify.error(e, "Upload failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Certificates</div>
      <BrowseGrid
        resourceName="certificate" items={data || []} loading={loading} error={error} onRefresh={reload}
        onCreate={() => setAdding(true)}
        onDelete={async (rows) => { for (const r of rows) await api.deleteCertificate(rg, name, r.name); notify.success("Certificate(s) deleted.", "Delete succeeded"); reload(); }}
        columns={[{ key: "name", label: "Name" }, { key: "subject", label: "Subject name", value: (r) => r.properties?.subjectName }, { key: "thumbprint", label: "Thumbprint", value: (r) => r.properties?.thumbprint }, { key: "state", label: "Provisioning state", value: (r) => r.properties?.provisioningState }]}
      />
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Upload certificate">
          <DialogBody>
            <DialogTitle>Upload certificate</DialogTitle>
            <DialogContent><Field label="Certificate name" required><Input value={certName} onChange={(_, d) => setCertName(d.value)} /></Field></DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!certName || busy} onClick={create}>{busy ? "Uploading..." : "Upload"}</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function WorkloadProfiles({ a, rg, name, reload }) {
  const notify = useNotify();
  const states = useAsync(() => api.listWorkloadProfileStates(rg, name), [rg, name]);
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", workloadProfileType: "D4" });
  const [busy, setBusy] = useState(false);
  const profiles = a.properties?.workloadProfiles || [];
  const add = async () => {
    setBusy(true);
    try {
      await api.updateWorkloadProfiles(rg, name, a, [...profiles, { name: f.name, workloadProfileType: f.workloadProfileType }]);
      notify.success(`Workload profile '${f.name}' was added.`, "Save succeeded");
      setAdding(false); setF({ name: "", workloadProfileType: "D4" }); reload(); states.reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Workload profiles</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Workload profiles commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdding(true)}>Add</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => states.reload()}>Refresh</ToolbarButton>
      </div>
      <MiniTable columns={["Name", "Workload profile type", "Minimum count", "Maximum count", "Current count"]} empty="No workload profiles"
        rows={profiles.map((p) => {
          const st = (states.data || []).find((s) => s.name === p.name)?.properties || {};
          return <tr key={p.name}><td>{p.name}</td><td>{p.workloadProfileType}</td><td>{st.minimumCount ?? 0}</td><td>{st.maximumCount ?? 0}</td><td>{st.currentCount ?? 0}</td></tr>;
        })} />
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Add workload profile">
          <DialogBody>
            <DialogTitle>Add workload profile</DialogTitle>
            <DialogContent>
              <Field label="Name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} /></Field>
              <Field label="Workload profile type" required>
                <Select value={f.workloadProfileType} onChange={(_, d) => setF((x) => ({ ...x, workloadProfileType: d.value }))} aria-label="Workload profile type">
                  <option value="D4">Dedicated-D4 (General purpose)</option><option value="D8">Dedicated-D8 (General purpose)</option>
                  <option value="E4">Dedicated-E4 (Memory optimized)</option>
                </Select>
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!f.name || busy} onClick={add}>{busy ? "Adding..." : "Add"}</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function Networking({ a }) {
  const p = a.properties || {};
  const vnet = p.vnetConfiguration;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Networking</div>
      <Essentials
        left={[["Virtual network", vnet?.infrastructureSubnetId ? vnet.infrastructureSubnetId.split("/").pop() : "Not configured (Vyomi-managed)"], ["Internal load balancer", vnet?.internal ? "Enabled" : "Disabled"]]}
        right={[["Static IP", p.staticIp], ["Outbound IP addresses", p.staticIp]]}
      />
      <NotSimulatedContainer title="Custom VNet integration" feature="Bringing an existing virtual network/subnet"
        note="Vyomi always provisions the environment's own virtual network; private endpoints and NAT gateway integration are not simulated." />
    </>
  );
}
