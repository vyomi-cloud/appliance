/* Azure AI services account resource blade: left resource menu + panels. Overview, Tags,
 * Keys and Endpoint, Model deployments, Quotas, Networking, Identity, Properties, Locks,
 * Activity log and Export template are backed by native ARM / Cognitive Services REST calls;
 * everything else in the menu is an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular, Eye16Regular, EyeOff16Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, downloadCsv, fmtDate } from "../../kit/common.jsx";
import ResourceIam from "../../kit/ResourceIam.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { remember, forget } from "../../kit/recent.js";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Resource Management", items: [
    { id: "keysendpoint", label: "Keys and Endpoint" }, { id: "deployments", label: "Model deployments" }, { id: "quotas", label: "Quotas" },
    { id: "networking", label: "Networking" }, { id: "identity", label: "Identity" }, { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" },
  ] },
  { group: "Monitoring", items: [{ id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" }, { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "logs", label: "Logs" }] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "resourcehealth", label: "Resource health" }, { id: "support", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const NS_NOTES = {
  diagnose: "Diagnose and solve problems",
  alerts: "Alert rules",
  metrics: "Resource metrics",
  diagnosticsettings: "Diagnostic settings",
  logs: "Log Analytics queries",
  tasks: "Tasks",
  resourcehealth: "Resource health",
  support: "Support + Troubleshooting",
};

export default function CognitiveServicesAccountBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const acct = useAsync(() => api.getAccount(rg, name), [rg, name]);
  const self = `#/cognitiveservices/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (acct.data) remember({ name, type: "Azure AI services", href: self }); }, [!!acct.data, self]);

  let body;
  if (acct.loading && !acct.data) body = <Loading />;
  else if (acct.error) body = <><ErrorBar error={acct.error} title="Failed to load the account" /><Link href="#/cognitiveservices">Back to Azure AI services</Link></>;
  else {
    const a = acct.data, reload = acct.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      keysendpoint: () => <KeysAndEndpoint a={a} />,
      deployments: () => <Deployments a={a} />,
      quotas: () => <Quotas a={a} />,
      networking: () => <Networking a={a} reload={reload} />,
      identity: () => <Identity a={a} reload={reload} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks a={a} />,
      activitylog: () => <ActivityLog a={a} />,
      exporttemplate: () => <ExportTemplate a={a} />,
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{LABEL[panel] || panel}</div>
        <NotSimulated feature={NS_NOTES[panel] || `The ${LABEL[panel] || panel} panel`} />
      </>
    );
  }

  return (
    <ResourceBlade
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Azure AI services" glyph={<Glyph id="cognitiveservices" />} closeHref="#/cognitiveservices"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self }) {
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const p = a.properties || {};
  const tags = Object.entries(a.tags || {});
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton disabled>Move</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton disabled>Open in mobile</ToolbarButton>
        <ToolbarButton disabled>Feedback</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Subscription", "Vyomi simulator (default directory)"],
          ["Subscription ID", "00000000-0000-0000-0000-cloudlearn01"],
          ["Endpoint", p.endpoint],
        ]}
        right={[
          ["Pricing tier", a.sku?.name],
          ["Kind", api.KIND_LABEL[a.kind] || a.kind],
          ["Provisioning state", p.provisioningState],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
      />
      <div style={{ marginTop: 12, fontSize: 13 }}>
        <p>Use <Link href={`${self}/keysendpoint`}>Keys and Endpoint</Link> to get the credentials your application calls this resource with, and <Link href={`${self}/deployments`}>Model deployments</Link> to deploy a model.</p>
      </div>

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="account" names={[a.name]}
        onConfirm={async () => {
          await api.deleteAccount(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Account '${a.name}' was deleted.`, "Delete succeeded");
          navigate("cognitiveservices");
        }} />
    </>
  );
}

// ── Access control (IAM) — shared real RBAC panel (core/azure_iam_core.py) ─────────────
const COGNITIVESERVICES_ACTIONS = ["Microsoft.CognitiveServices/accounts/read", "Microsoft.CognitiveServices/accounts/write", "Microsoft.CognitiveServices/accounts/delete", "Microsoft.CognitiveServices/accounts/listKeys/action", "Microsoft.CognitiveServices/accounts/deployments/write"];
function AccessControlIam({ a }) { return <ResourceIam a={a} capId="azure.cognitiveservices.iam" actions={COGNITIVESERVICES_ACTIONS} />; }

// ── Tags ───────────────────────────────────────────────────────────────────────────────
export function TagRows({ tags, onChange, resource }) {
  const upd = (i, k, v) => {
    const xs = tags.map((t, j) => (j === i ? { ...t, [k]: v } : t));
    if (xs[xs.length - 1].name || xs[xs.length - 1].value) xs.push({ name: "", value: "" });
    onChange(xs);
  };
  return (
    <Table size="small" aria-label="Tags" style={{ maxWidth: 760 }}>
      <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell>Resource</TableHeaderCell><TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
      <TableBody>
        {tags.map((t, i) => (
          <TableRow key={i}>
            <TableCell><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label={`Tag name ${i + 1}`} /></TableCell>
            <TableCell><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label={`Tag value ${i + 1}`} /></TableCell>
            <TableCell>{resource}</TableCell>
            <TableCell>{i < tags.length - 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete tag" onClick={() => onChange(tags.filter((_, j) => j !== i))} />}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Tags({ a, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(a.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const apply = async () => {
    setBusy(true);
    try {
      await api.updateAccount(a.resourceGroup, a.name, { tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
      notify.success(`Tags on '${a.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Tags</div>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={rows} onChange={setRows} resource={a.name} />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
        <Button appearance="secondary" disabled={busy || !rows.some((t) => t.name)} onClick={async () => { setRows([{ name: "", value: "" }]); await apply(); }}>Delete all</Button>
      </div>
    </>
  );
}

// ── Keys and Endpoint ──────────────────────────────────────────────────────────────────
function KeysAndEndpoint({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listKeys(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(null); // "key1" | "key2"
  const mask = (k) => (show ? k : (k || "").slice(0, 4) + "•".repeat(28));
  const regen = async (which) => {
    setBusy(which);
    try { await api.regenerateKey(a.resourceGroup, a.name, which === "key1" ? "Key1" : "Key2"); notify.success(`${which === "key1" ? "KEY 1" : "KEY 2"} was regenerated.`, "Regenerate succeeded"); reload(); }
    catch (e) { notify.error(e, "Regenerate failed"); }
    finally { setBusy(null); }
  };
  return (
    <>
      <div className="vy-panel-title">Keys and Endpoint</div>
      <ErrorBar error={error} />
      <section className="vy-form-section">
        <h3 style={{ display: "flex", alignItems: "center", gap: 8 }}>Keys
          <Button size="small" icon={show ? <EyeOff16Regular /> : <Eye16Regular />} onClick={() => setShow((v) => !v)}>{show ? "Hide Keys" : "Show Keys"}</Button>
        </h3>
        {loading ? <Spinner size="tiny" /> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 640 }}>
            <Field label="KEY 1">
              <div style={{ display: "flex", gap: 8 }}>
                <Input readOnly value={mask(data?.key1)} style={{ flex: 1, fontFamily: "monospace" }} aria-label="KEY 1" />
                <Button onClick={() => navigator.clipboard?.writeText(data?.key1 || "")}>Copy</Button>
                <Button disabled={busy === "key1"} onClick={() => regen("key1")}>{busy === "key1" ? "Regenerating..." : "Regenerate Key1"}</Button>
              </div>
            </Field>
            <Field label="KEY 2">
              <div style={{ display: "flex", gap: 8 }}>
                <Input readOnly value={mask(data?.key2)} style={{ flex: 1, fontFamily: "monospace" }} aria-label="KEY 2" />
                <Button onClick={() => navigator.clipboard?.writeText(data?.key2 || "")}>Copy</Button>
                <Button disabled={busy === "key2"} onClick={() => regen("key2")}>{busy === "key2" ? "Regenerating..." : "Regenerate Key2"}</Button>
              </div>
            </Field>
          </div>
        )}
      </section>
      <section className="vy-form-section">
        <h3>Endpoint</h3>
        <Field label="Endpoint">
          <div style={{ display: "flex", gap: 8, maxWidth: 640 }}>
            <Input readOnly value={a.properties?.endpoint || ""} style={{ flex: 1 }} aria-label="Endpoint" />
            <Button onClick={() => navigator.clipboard?.writeText(a.properties?.endpoint || "")}>Copy</Button>
          </div>
        </Field>
      </section>
    </>
  );
}

// ── Model deployments ──────────────────────────────────────────────────────────────────
function Deployments({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDeployments(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [create, setCreate] = useState(false);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Model deployments</div>
      {!api.MODEL_KINDS.includes(a.kind) && <NotSimulated feature="Model deployments" note={`Deployments are only supported on Azure OpenAI and Azure AI services accounts, not '${a.kind}'.`} />}
      <BrowseGrid
        resourceName="deployment" rowKey={(r) => r.name} filterPlaceholder="Search deployments"
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={api.MODEL_KINDS.includes(a.kind) ? <ToolbarButton icon={<Add20Regular />} onClick={() => setCreate(true)}>Create new deployment</ToolbarButton> : undefined}
        onDelete={async (sel) => { for (const r of sel) await api.deleteDeployment(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${sel.length} deployment${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        csvName="model-deployments.csv"
        columns={[
          { key: "name", label: "Deployment name" },
          { key: "model", label: "Model name", value: (r) => r.properties?.model?.name },
          { key: "version", label: "Model version", value: (r) => r.properties?.model?.version },
          { key: "type", label: "Deployment type", value: (r) => r.sku?.name },
          { key: "capacity", label: "Capacity", value: (r) => r.sku?.capacity },
          { key: "rate", label: "Rate limit (Tokens per minute)", value: (r) => (r.properties?.rateLimits || []).find((x) => x.key === "token")?.count },
          { key: "status", label: "Status", value: (r) => r.properties?.provisioningState },
        ]}
        emptyAction={api.MODEL_KINDS.includes(a.kind) ? <Link as="button" onClick={() => setCreate(true)}>Create new deployment</Link> : undefined}
      />
      <CreateDeploymentDialog open={create} onClose={() => setCreate(false)}
        onCreate={async (name, model, type, capacity) => {
          await api.putDeployment(a.resourceGroup, a.name, name, { sku: { name: type, capacity }, properties: { model } });
          notify.success(`Deployment '${name}' was created.`, "Deployment succeeded");
          reload();
        }} />
    </>
  );
}

const MODEL_NAMES = [...new Set(api.MODELS.map((m) => m[1]))];
const versionsFor = (name) => api.MODELS.filter((m) => m[1] === name).map((m) => m[2]);

function CreateDeploymentDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [modelName, setModelName] = useState(MODEL_NAMES[0]);
  const [modelVersion, setModelVersion] = useState(versionsFor(MODEL_NAMES[0])[0]);
  const [type, setType] = useState(api.DEPLOY_SKUS[0]);
  const [capacity, setCapacity] = useState(1);
  const [busy, setBusy] = useState(false);
  const pickModel = (_, d) => { setModelName(d.value); setModelVersion(versionsFor(d.value)[0]); };
  const go = async () => {
    const m = api.MODELS.find((x) => x[1] === modelName && x[2] === modelVersion);
    setBusy(true);
    try {
      await onCreate(name, { format: m[0], name: m[1], version: m[2] }, type, Number(capacity) || 1);
      setName(""); onClose();
    } catch (e) { notify.error(e, "Deployment failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Deploy model">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Deploy model</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Select a model" required>
                <Select value={modelName} onChange={pickModel} aria-label="Select a model">
                  {MODEL_NAMES.map((n) => <option key={n} value={n}>{n}</option>)}
                </Select>
              </Field>
              <Field label="Model version" required>
                <Select value={modelVersion} onChange={(_, d) => setModelVersion(d.value)} aria-label="Model version">
                  {versionsFor(modelName).map((v) => <option key={v} value={v}>{v}</option>)}
                </Select>
              </Field>
              <Field label="Deployment type" required>
                <Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Deployment type">
                  {api.DEPLOY_SKUS.map((s) => <option key={s} value={s}>{s}</option>)}
                </Select>
              </Field>
              <Field label="Deployment name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Deployment name" /></Field>
              <Field label="Tokens per minute rate limit (thousands)" required><Input type="number" min={1} value={String(capacity)} onChange={(_, d) => setCapacity(d.value)} aria-label="Tokens per minute rate limit (thousands)" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!name || busy} onClick={go}>{busy ? "Deploying..." : "Deploy"}</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Quotas ──────────────────────────────────────────────────────────────────────────────
function Quotas({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.listUsages(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Quotas</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Quotas commands"><ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton></div>
      <ErrorBar error={error} />
      <table className="vy-grid">
        <thead><tr><th>Name</th><th>Current usage</th><th>Limit</th><th>Renewal period</th></tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={4}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((r) => (
            <tr key={r.name?.value}>
              <td>{r.name?.localizedValue || r.name?.value}</td>
              <td>{r.currentValue}</td>
              <td>{r.limit}</td>
              <td>{r.quotaPeriod || "--"}</td>
            </tr>
          )) : <tr><td colSpan={4} className="vy-muted">No quota usage to display</td></tr>}
        </tbody>
      </table>
    </>
  );
}

// ── Networking ─────────────────────────────────────────────────────────────────────────
function Networking({ a, reload }) {
  const notify = useNotify();
  const [tab, setTab] = useState("firewalls");
  const p = a.properties || {};
  const net = p.publicNetworkAccess === "Disabled" ? "disabled" : p.networkAcls?.defaultAction === "Deny" ? "selected" : "all";
  const [value, setValue] = useState(net);
  const [busy, setBusy] = useState(false);
  useEffect(() => setValue(net), [net]);
  const save = async (v) => {
    setValue(v);
    setBusy(true);
    try {
      await api.updateAccount(a.resourceGroup, a.name, { properties: {
        publicNetworkAccess: v === "disabled" ? "Disabled" : "Enabled",
        networkAcls: { defaultAction: v === "selected" ? "Deny" : "Allow" },
      } });
      notify.success(`Networking for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving networking failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Networking</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Networking tabs">
        <Tab value="firewalls">Firewalls and virtual networks</Tab>
        <Tab value="private">Private endpoint connections</Tab>
      </TabList>
      {tab === "firewalls" && (
        <CapabilityContainer id="azure.cognitiveservices.networking" title="Firewalls and virtual networks">
          <RadioGroup disabled={busy} value={value} onChange={(_, d) => save(d.value)} aria-label="Allow access from">
            <Radio value="all" label="All networks" />
            <Radio value="selected" label="Selected networks" />
            <Radio value="disabled" label="Disabled" />
          </RadioGroup>
        </CapabilityContainer>
      )}
      {tab === "private" && <NotSimulatedContainer title="Private endpoint connections" feature="Private endpoint connections for Azure AI services accounts" />}
    </>
  );
}

// ── Identity ────────────────────────────────────────────────────────────────────────────
function Identity({ a, reload }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const on = a.identity?.type === "SystemAssigned" || a.identity?.type === "SystemAssigned, UserAssigned";
  const toggle = async (checked) => {
    setBusy(true);
    try {
      await api.updateAccount(a.resourceGroup, a.name, { identity: { type: checked ? "SystemAssigned" : "None" } });
      notify.success(`Identity for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving identity failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Identity</div>
      <section className="vy-form-section">
        <h3>System assigned managed identity</h3>
        <Checkbox label="Status" disabled={busy} checked={on} onChange={(_, d) => toggle(!!d.checked)} />
        {on && <div style={{ marginTop: 8 }}><KV label="Object (principal) ID" value={a.identity?.principalId} /><KV label="Tenant ID" value={a.identity?.tenantId} /></div>}
      </section>
      <NotSimulatedContainer title="User assigned managed identity" feature="Attaching a user-assigned managed identity (Microsoft.ManagedIdentity/userAssignedIdentities is not catalogued in Vyomi)" />
    </>
  );
}

// ── Properties ─────────────────────────────────────────────────────────────────────────
function Properties({ a }) {
  const p = a.properties || {};
  return (
    <>
      <div className="vy-panel-title">Properties</div>
      <div className="vy-props">
        <KV label="Resource ID" value={a.id} />
        <KV label="Account name" value={a.name} />
        <KV label="Kind" value={a.kind} />
        <KV label="Location" value={locationLabel(a.location)} />
        <KV label="Pricing tier" value={a.sku?.name} />
        <KV label="Endpoint" value={p.endpoint} />
        <KV label="Internal ID" value={p.internalId} />
        <KV label="Public network access" value={p.publicNetworkAccess} />
      </div>
    </>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this account) ─────────────────────
function Locks({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(a.resourceGroup, a.name), [a.resourceGroup, a.name]);
  const [add, setAdd] = useState(false);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <>
      <div className="vy-panel-title">Locks</div>
      <BrowseGrid
        resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Subscription")}>Subscription</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Resource group")}>Resource group</ToolbarButton>
          <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        </>}
        onDelete={async (sel) => { for (const r of sel) await api.deleteLock(a.resourceGroup, a.name, r.name); notify.success(`Deleted ${sel.length} lock${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
        csvName="locks.csv"
        columns={[
          { key: "name", label: "Lock name" },
          { key: "type", label: "Lock type", value: (r) => (r.properties?.level === "ReadOnly" ? "Read-only" : "Delete") },
          { key: "scope", label: "Scope", value: () => a.name },
          { key: "notes", label: "Notes", value: (r) => r.properties?.notes || "--" },
        ]}
      />
      <AddLockDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name, level, notes) => { await api.putLock(a.resourceGroup, a.name, name, { properties: { level, notes } }); reload(); }} />
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : `Locks scoped to the ${(gap || "").toLowerCase()}`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

function AddLockDialog({ open, onClose, onCreate }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [type, setType] = useState("Delete");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = /^[a-zA-Z0-9._-]{1,90}$/.test(name);
  const go = async () => {
    setBusy(true);
    try { await onCreate(name, type === "Read-only" ? "ReadOnly" : "CanNotDelete", notes); notify.success(`Lock '${name}' was added.`, "Lock added"); setName(""); setNotes(""); setType("Delete"); onClose(); }
    catch (e) { notify.error(e, "Failed to add lock"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add lock">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Add lock</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Lock name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Lock name" /></Field>
              <Field label="Lock type" required>
                <Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Lock type"><option>Read-only</option><option>Delete</option></Select>
              </Field>
              <Field label="Notes"><Textarea value={notes} onChange={(_, d) => setNotes(d.value)} aria-label="Notes" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>OK</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

const ACTIVITY_LOG_COLUMNS = [
  { key: "op", label: "Operation name", csv: (r) => r.operationName?.localizedValue || r.operationName?.value },
  { key: "status", label: "Status", csv: (r) => r.status?.localizedValue || r.status?.value },
  { key: "time", label: "Time", csv: (r) => fmtDate(r.eventTimestamp) },
  { key: "stamp", label: "Time stamp", csv: (r) => r.eventTimestamp },
  { key: "sub", label: "Subscription", csv: (r) => r.subscriptionId },
  { key: "by", label: "Event initiated by", csv: (r) => r.caller },
];

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this account) ──
const TIMESPANS = [["1h", "Last hour"], ["24h", "Last 24 hours"], ["7d", "Last 7 days"], ["30d", "Last 30 days"], ["90d", "Last 90 days"]];
const timespanSinceIso = (code) => new Date(Date.now() - ({ "1h": 36e5, "24h": 24 * 36e5, "7d": 7 * 24 * 36e5, "30d": 30 * 24 * 36e5, "90d": 90 * 24 * 36e5 }[code] || 90 * 24 * 36e5)).toISOString();

function ActivityLog({ a }) {
  const [timespan, setTimespan] = useState("90d");
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(a.resourceGroup, a.name, timespanSinceIso(timespan)), [a.id, timespan]);
  const [gap, setGap] = useState(null);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.cognitiveservices.activity_log" title={`${a.name} | Activity log`}
      actions={<>
        <ToolbarButton onClick={() => setGap("Edit columns")}>Edit columns</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Export Activity Logs")}>Export Activity Logs</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />} disabled={!rows.length} onClick={() => downloadCsv("activity-log.csv", ACTIVITY_LOG_COLUMNS, rows)}>Download as CSV</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Feedback")}>Feedback</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Pin current filters")}>Pin current filters</ToolbarButton>
        <ToolbarButton onClick={() => setGap("Reset filters")}>Reset filters</ToolbarButton>
      </>}>
      <ErrorBar error={error} />
      <Field label="Timespan" style={{ maxWidth: 220, marginBottom: 8 }}>
        <Select value={timespan} onChange={(_, d) => setTimespan(d.value)} aria-label="Timespan">{TIMESPANS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
      </Field>
      <table className="vy-grid">
        <thead><tr>{ACTIVITY_LOG_COLUMNS.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
        <tbody>
          {loading ? <tr><td colSpan={6}><Spinner size="tiny" /></td></tr> : rows.length ? rows.map((r) => (
            <tr key={r.id}>
              <td>{r.operationName?.localizedValue || r.operationName?.value}</td>
              <td>{r.status?.localizedValue || r.status?.value}</td>
              <td>{fmtDate(r.eventTimestamp)}</td>
              <td>{r.eventTimestamp}</td>
              <td>{r.subscriptionId}</td>
              <td>{r.caller}</td>
            </tr>
          )) : <tr><td colSpan={6} className="vy-muted">No events to display</td></tr>}
        </tbody>
      </table>
      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || "Not simulated"}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={gap === "Feedback" ? "Sending product feedback" : gap} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Export template ────────────────────────────────────────────────────────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { accountName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.CognitiveServices/accounts", apiVersion: api.API_VERSION, name: params ? "[parameters('accountName')]" : a.name, kind: a.kind, sku: a.sku, location: a.location, properties: a.properties }],
  };
  const text = JSON.stringify(template, null, 2);
  const download = () => {
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    el.download = `${a.name}.json`;
    document.body.appendChild(el); el.click(); el.remove();
  };
  return (
    <>
      <div className="vy-panel-title">Export template</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Export template commands">
        <ToolbarButton icon={<ArrowDownload20Regular />} onClick={download}>Download</ToolbarButton>
        <ToolbarButton disabled>Add to library (preview)</ToolbarButton>
        <ToolbarButton disabled>Deploy</ToolbarButton>
        <ToolbarButton disabled>Visualize template</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab>
        <Tab value="bicep">Bicep</Tab>
        <Tab value="terraform">Terraform</Tab>
      </TabList>
      <section className="vy-section" style={{ marginTop: 12 }}><h3>Template</h3>
        <Checkbox label="Include parameters" checked={params} onChange={(_, d) => setParams(!!d.checked)} />
        {tab === "arm" && <Textarea readOnly value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />}
        {tab !== "arm" && <NotSimulatedContainer feature={`${tab === "bicep" ? "Bicep" : "Terraform"} template export`} />}
      </section>
    </>
  );
}
