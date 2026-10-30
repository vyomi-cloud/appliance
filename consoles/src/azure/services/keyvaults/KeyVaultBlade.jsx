/* Key vault resource blade: left resource menu + panels. Overview, Tags, Access policies,
 * Keys, Secrets, Access configuration, Networking (Firewalls tab), Properties and Export
 * template are backed by native ARM / Key Vault REST calls; everything else in the menu is
 * an honest NotSimulated panel. */
import { useEffect, useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Tab, TabList, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, ArrowDownload20Regular, Delete20Regular, Dismiss20Regular, Eye16Regular, EyeOff16Regular, Save20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, KV, Loading, NotSimulated, NotSimulatedContainer, fmtDate } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { vy } from "../../../common/VyomiMark.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "accesspolicies", label: "Access policies" },
  { id: "events", label: "Events" },
  { group: "Objects", items: [{ id: "keys", label: "Keys" }, { id: "secrets", label: "Secrets" }, { id: "certificates", label: "Certificates" }] },
  { group: "Settings", items: [{ id: "accessconfiguration", label: "Access configuration" }, { id: "networking", label: "Networking" }, { id: "defender", label: "Microsoft Defender for Cloud" }, { id: "properties", label: "Properties" }, { id: "locks", label: "Locks" }] },
  { group: "Monitoring", items: [{ id: "alerts", label: "Alerts" }, { id: "metrics", label: "Metrics" }, { id: "diagnosticsettings", label: "Diagnostic settings" }, { id: "logs", label: "Logs" }, { id: "insights", label: "Insights" }, { id: "workbooks", label: "Workbooks" }] },
  { group: "Automation", items: [{ id: "tasks", label: "Tasks" }, { id: "exporttemplate", label: "Export template" }] },
  { group: "Help", items: [{ id: "resourcehealth", label: "Resource health" }, { id: "support", label: "Support + Troubleshooting" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const NS_NOTES = {
  diagnose: "Diagnose and solve problems",
  events: "Event Grid subscriptions on key vault events",
  defender: "Microsoft Defender for Cloud",
  alerts: "Alert rules",
  metrics: "Key vault metrics",
  diagnosticsettings: "Diagnostic settings",
  logs: "Log Analytics queries",
  insights: "Key vault insights",
  workbooks: "Workbooks",
  tasks: "Tasks",
  resourcehealth: "Resource health",
  support: "Support + Troubleshooting",
};

export default function KeyVaultBlade({ params, query }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const vault = useAsync(() => api.getVault(rg, name), [rg, name]);
  const self = `#/keyvaults/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (vault.data) remember({ name, type: "Key vault", href: self }); }, [!!vault.data, self]);

  let body;
  if (vault.loading && !vault.data) body = <Loading />;
  else if (vault.error) body = <><ErrorBar error={vault.error} title="Failed to load the key vault" /><Link href="#/keyvaults">Back to Key vaults</Link></>;
  else {
    const a = vault.data, reload = vault.reload;
    const P = {
      overview: () => <Overview a={a} reload={reload} self={self} />,
      iam: () => <AccessControlIam a={a} />,
      tags: () => <Tags a={a} reload={reload} />,
      accesspolicies: () => <AccessPolicies a={a} reload={reload} />,
      keys: () => <Keys />,
      secrets: () => <Secrets self={self} query={query} />,
      certificates: () => <Certificates />,
      accessconfiguration: () => <AccessConfiguration a={a} reload={reload} />,
      networking: () => <Networking a={a} reload={reload} />,
      properties: () => <Properties a={a} />,
      locks: () => <Locks />,
      activitylog: () => <ActivityLog />,
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
      title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Key vault" glyph={<Glyph id="keyvaults" />} closeHref="#/keyvaults"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── Overview ───────────────────────────────────────────────────────────────────────────
function Overview({ a, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [tab, setTab] = useState("getstarted");
  const [del, setDel] = useState(false);
  const p = a.properties || {};
  const tags = Object.entries(a.tags || {});
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{a.resourceGroup}</Link>],
          ["Location", locationLabel(a.location)],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
          ["Vault URI", api.vaultUri(a.name)],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
        right={[
          ["Sku (Pricing tier)", api.skuLabel(p.sku)],
          ["Directory ID", p.tenantId],
          ["Directory Name", vy("Vyomi simulator (default directory)")],
          ["Soft-delete", p.enableSoftDelete ? "Enabled" : "Disabled"],
          ["Purge protection", p.enablePurgeProtection ? "Enabled" : "Disabled"],
        ]}
      />
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Overview tabs">
        <Tab value="getstarted">Get started</Tab>
        <Tab value="monitoring">Monitoring</Tab>
        <Tab value="properties">Properties</Tab>
        <Tab value="capabilities">Capabilities</Tab>
        <Tab value="recommendations">Recommendations</Tab>
        <Tab value="tutorials">Tutorials</Tab>
      </TabList>
      {tab === "getstarted" && (
        <div style={{ marginTop: 12 }}>
          <p style={{ fontSize: 13 }}>Use Objects (Keys, Secrets, Certificates) to store and manage cryptographic material in this vault.</p>
          <Link href={`${self}/keys`}>Keys</Link>{" · "}<Link href={`${self}/secrets`}>Secrets</Link>
        </div>
      )}
      {tab === "monitoring" && <NotSimulatedContainer feature="Key vault monitoring (requests, latency and saturation charts)" />}
      {tab === "properties" && <PropertyList a={a} />}
      {tab === "capabilities" && <NotSimulatedContainer feature="The capabilities overview" />}
      {tab === "recommendations" && <NotSimulatedContainer feature="Advisor recommendations" />}
      {tab === "tutorials" && <NotSimulatedContainer feature="Tutorials" />}

      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="key vault" names={[a.name]}
        onConfirm={async () => {
          await api.deleteVault(a.resourceGroup, a.name);
          forget(self);
          notify.success(`Key vault '${a.name}' was deleted.`, "Delete succeeded");
          navigate("keyvaults");
        }} />
    </>
  );
}

function PropertyList({ a }) {
  const p = a.properties || {};
  return (
    <div className="vy-props" style={{ marginTop: 12 }}>
      <KV label="Vault name" value={a.name} />
      <KV label="Resource ID" value={a.id} />
      <KV label="Sku (Pricing tier)" value={api.skuLabel(p.sku)} />
      <KV label="Soft-delete" value={p.enableSoftDelete ? "Enabled" : "Disabled"} />
      <KV label="Days to retain deleted vaults" value={p.softDeleteRetentionInDays} />
      <KV label="Purge protection" value={p.enablePurgeProtection ? "Enabled" : "Disabled"} />
    </div>
  );
}

// ── Access control (IAM) ──────────────────────────────────────────────────────────────
function AccessControlIam({ a }) {
  const [tab, setTab] = useState("check");
  const [dlg, setDlg] = useState(null);
  return (
    <>
      <div className="vy-panel-title">Access control (IAM)</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Access control (IAM) tabs">
        <Tab value="check">Check access</Tab>
        <Tab value="assignments">Role assignments</Tab>
        <Tab value="roles">Roles</Tab>
        <Tab value="deny">Deny assignments</Tab>
        <Tab value="classic">Classic administrators</Tab>
      </TabList>
      {tab === "check" && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 16 }}>
          <section className="vy-section"><h3>My access</h3>
            <Button onClick={() => setDlg("mine")}>View my access</Button>
          </section>
          <section className="vy-section"><h3>Check access</h3>
            <Button onClick={() => setDlg("check")}>Check access</Button>
          </section>
        </div>
      )}
      {tab === "assignments" && (
        <div style={{ marginTop: 12 }}>
          <div className="vy-panel-title">Role assignments</div>
          <NotSimulatedContainer feature="Role assignments scoped to this key vault (Microsoft.Authorization/roleAssignments is simulated at subscription scope only)" />
        </div>
      )}
      {tab === "roles" && (
        <div style={{ marginTop: 12 }}>
          <div className="vy-panel-title">Roles</div>
          <NotSimulatedContainer feature="The built-in and custom role catalog" />
        </div>
      )}
      {tab === "deny" && (
        <div style={{ marginTop: 12 }}>
          <div className="vy-panel-title">Deny assignments</div>
          <NotSimulatedContainer feature="Deny assignments" />
        </div>
      )}
      {tab === "classic" && <div style={{ marginTop: 12 }}><NotSimulatedContainer title="Classic administrators" feature="Classic administrators (co-administrators)" /></div>}
      <Dialog open={!!dlg} onOpenChange={(_, d) => !d.open && setDlg(null)}>
        <DialogSurface aria-label="Access check">
          <DialogBody>
            <DialogTitle>{dlg === "mine" ? "My access" : "Check access"}</DialogTitle>
            <DialogContent><NotSimulated feature="Per-identity role-assignment resolution for this resource" note={`The vault's resource id is ${a.id}.`} /></DialogContent>
            <DialogActions><Button onClick={() => setDlg(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

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
      // ARM PUT replaces the resource's tag set exactly (a PATCH would merge and keep removed keys).
      const { id, name, type, resourceGroup, ...rest } = a;
      await api.createVault(a.resourceGroup, a.name, { ...rest, tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
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

// ── Access policies ────────────────────────────────────────────────────────────────────
const PERMS = ["Get", "List", "Create", "Delete"];

function AccessPolicies({ a, reload }) {
  const notify = useNotify();
  const policies = a.properties?.accessPolicies || [];
  const [edit, setEdit] = useState(null); // {index} | "new"
  const save = async (list) => {
    try {
      await api.updateVault(a.resourceGroup, a.name, { properties: { accessPolicies: list } });
      notify.success(`Access policies on '${a.name}' were updated.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving access policies failed"); }
  };
  return (
    <>
      <div className="vy-panel-title">Access policies</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Access policies commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setEdit("new")}>Create</ToolbarButton>
        <ToolbarButton disabled={!policies.length} onClick={() => setEdit({ index: 0 })}>Edit</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} disabled={!policies.length} onClick={() => save(policies.slice(1))}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <Table size="small" aria-label="Access policies" style={{ maxWidth: 900, marginTop: 8 }}>
        <TableHeader><TableRow>
          <TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Email</TableHeaderCell>
          <TableHeaderCell>Key Permissions</TableHeaderCell><TableHeaderCell>Secret Permissions</TableHeaderCell><TableHeaderCell>Certificate Permissions</TableHeaderCell>
        </TableRow></TableHeader>
        <TableBody>
          {policies.map((p, i) => (
            <TableRow key={i}>
              <TableCell>{p.objectId}</TableCell><TableCell>--</TableCell>
              <TableCell>{(p.permissions?.keys || []).join(", ") || "--"}</TableCell>
              <TableCell>{(p.permissions?.secrets || []).join(", ") || "--"}</TableCell>
              <TableCell>{(p.permissions?.certificates || []).join(", ") || "--"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!policies.length && <p className="vy-muted" style={{ fontSize: 13 }}>No access policies.</p>}
      <PolicyDialog open={!!edit} policy={edit && edit !== "new" ? policies[edit.index] : null}
        onClose={() => setEdit(null)}
        onSave={async (p) => { await save(edit === "new" ? [...policies, p] : policies.map((x, i) => (i === edit.index ? p : x))); setEdit(null); }} />
    </>
  );
}

function PolicyDialog({ open, policy, onClose, onSave }) {
  const [objectId, setObjectId] = useState(policy?.objectId || "");
  const [keys, setKeys] = useState(new Set(policy?.permissions?.keys || []));
  const [secrets, setSecrets] = useState(new Set(policy?.permissions?.secrets || []));
  const [certs, setCerts] = useState(new Set(policy?.permissions?.certificates || []));
  useEffect(() => { setObjectId(policy?.objectId || ""); setKeys(new Set(policy?.permissions?.keys || [])); setSecrets(new Set(policy?.permissions?.secrets || [])); setCerts(new Set(policy?.permissions?.certificates || [])); }, [policy, open]);
  const toggle = (set, setSet, v) => setSet((s) => { const n = new Set(s); n.has(v) ? n.delete(v) : n.add(v); return n; });
  const go = () => onSave({ tenantId: "00000000-0000-0000-0000-000000000000", objectId, permissions: { keys: [...keys], secrets: [...secrets], certificates: [...certs] } });
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Access policy">
        <DialogBody>
          <DialogTitle>{policy ? "Edit access policy" : "Create an access policy"}</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Object ID" required><Input value={objectId} onChange={(_, d) => setObjectId(d.value)} aria-label="Object ID" /></Field>
              <Field label="Key Permissions">{PERMS.map((p) => <Checkbox key={p} label={p} checked={keys.has(p)} onChange={() => toggle(keys, setKeys, p)} />)}</Field>
              <Field label="Secret Permissions">{PERMS.map((p) => <Checkbox key={p} label={p} checked={secrets.has(p)} onChange={() => toggle(secrets, setSecrets, p)} />)}</Field>
              <Field label="Certificate Permissions">{PERMS.map((p) => <Checkbox key={p} label={p} checked={certs.has(p)} onChange={() => toggle(certs, setCerts, p)} />)}</Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!objectId} onClick={go}>{policy ? "Save" : "Add"}</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Keys ───────────────────────────────────────────────────────────────────────────────
function Keys() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listKeys(), []);
  const [create, setCreate] = useState(false);
  const rows = (data || []).map((k) => ({ ...api.parseKid(k.kid), raw: k }));
  return (
    <>
      <div className="vy-panel-title">Keys</div>
      <BrowseGrid
        resourceName="key" rowKey={(r) => r.name} filterPlaceholder="Filter by name..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton onClick={() => setCreate(true)}>Generate/Import</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteKey(r.name);
          notify.success(`Deleted ${sel.length} key${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="keys.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "status", label: "Status", value: (r) => (r.raw.attributes?.enabled ? "Enabled" : "Disabled") },
          { key: "expiration", label: "Expiration date", value: (r) => (r.raw.attributes?.exp ? fmtDate(r.raw.attributes.exp * 1000) : "--") },
        ]}
      />
      <NotSimulatedContainer feature="Restore Backup and Manage deleted keys" />
      <CreateKeyDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
    </>
  );
}

const EC_CURVES = [["P-256", "P-256"], ["P-384", "P-384"], ["P-521", "P-521"], ["P-256K", "P-256K"]];

function CreateKeyDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [kty, setKty] = useState("RSA");
  const [size, setSize] = useState("2048");
  const [curve, setCurve] = useState("P-256");
  const [exportable, setExportable] = useState(false);
  const [busy, setBusy] = useState(false);
  const valid = /^[a-zA-Z0-9-]{1,127}$/.test(name);
  const go = async () => {
    setBusy(true);
    try {
      await api.createKey(name, kty === "EC" ? { kty: "EC", crv: curve, exportable } : { kty: "RSA", key_size: Number(size), exportable });
      notify.success(`Successfully created key '${name}'.`, "Key created");
      setName(""); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create key"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create a key">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Create a key</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Options"><Select value="Generate" aria-label="Options"><option>Generate</option></Select></Field>
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field>
              <Field label="Key type"><RadioGroup layout="horizontal" value={kty} onChange={(_, d) => setKty(d.value)} aria-label="Key type"><Radio value="RSA" label="RSA" /><Radio value="EC" label="EC" /></RadioGroup></Field>
              <Field label="RSA key size"><RadioGroup disabled={kty !== "RSA"} layout="horizontal" value={size} onChange={(_, d) => setSize(d.value)} aria-label="RSA key size"><Radio value="2048" label="2048" /><Radio value="3072" label="3072" /><Radio value="4096" label="4096" /></RadioGroup></Field>
              <Field label="Elliptic curve name"><RadioGroup disabled={kty !== "EC"} layout="horizontal" value={curve} onChange={(_, d) => setCurve(d.value)} aria-label="Elliptic curve name">{EC_CURVES.map(([v, l]) => <Radio key={v} value={v} label={l} />)}</RadioGroup></Field>
              <Checkbox label="Set activation date" disabled />
              <Checkbox label="Set expiration date" disabled />
              <Field label="Enabled"><RadioGroup layout="horizontal" value="Yes" aria-label="Enabled"><Radio value="Yes" label="Yes" /><Radio value="No" label="No" disabled /></RadioGroup></Field>
              <div>Tags <span className="vy-muted">0 tags</span></div>
              <div>Enable rotation policy <span className="vy-muted">Not configured</span></div>
              <Field label="Exportable"><RadioGroup layout="horizontal" value={exportable ? "Yes" : "No"} onChange={(_, d) => setExportable(d.value === "Yes")} aria-label="Exportable"><Radio value="Yes" label="Yes" /><Radio value="No" label="No" /></RadioGroup></Field>
              <NotSimulated feature="Activation/expiration dates and tags on a new key" />
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Secrets ────────────────────────────────────────────────────────────────────────────
function Secrets({ self, query }) {
  if (query.secret && query.version) return <SecretVersionDetail self={self} name={query.secret} version={query.version} />;
  if (query.secret) return <SecretDetail self={self} name={query.secret} />;
  return <SecretsList self={self} />;
}

function SecretsList({ self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listSecrets(), []);
  const [create, setCreate] = useState(false);
  const rows = (data || []).map((s) => ({ ...api.parseSecretId(s.id), raw: s }));
  return (
    <>
      <div className="vy-panel-title">Secrets</div>
      <BrowseGrid
        resourceName="secret" rowKey={(r) => r.name} filterPlaceholder="Filter by name..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton onClick={() => setCreate(true)}>Generate/Import</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteSecret(r.name);
          notify.success(`Deleted ${sel.length} secret${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="secrets.csv"
        columns={[
          { key: "name", label: "Name", render: (r) => <Link href={`${self}/secrets?secret=${encodeURIComponent(r.name)}`}>{r.name}</Link> },
          { key: "type", label: "Type", value: () => "Manual" },
          { key: "status", label: "Status", value: (r) => (r.raw.attributes?.enabled ? "Enabled" : "Disabled") },
          { key: "expiration", label: "Expiration date", value: (r) => (r.raw.attributes?.exp ? fmtDate(r.raw.attributes.exp * 1000) : "--") },
        ]}
      />
      <NotSimulatedContainer feature="Restore Backup, View sample code and Manage deleted secrets" />
      <CreateSecretDialog open={create} onClose={() => setCreate(false)} onCreated={reload} />
    </>
  );
}

function CreateSecretDialog({ open, onClose, onCreated }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [contentType, setContentType] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const valid = /^[a-zA-Z0-9-]{1,127}$/.test(name) && value.length > 0;
  const go = async () => {
    setBusy(true);
    try {
      await api.setSecret(name, { value, contentType: contentType || undefined, attributes: { enabled } });
      notify.success(`Successfully created secret '${name}'.`, "Secret created");
      setName(""); setValue(""); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create secret"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create a secret">
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>Create a secret</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Upload options"><Select value="Manual" aria-label="Upload options"><option>Manual</option><option>Certificate</option></Select></Field>
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field>
              <Field label="Secret value" required><Textarea value={value} onChange={(_, d) => setValue(d.value)} aria-label="Secret value" /></Field>
              <Field label="Content type (optional)"><Input value={contentType} onChange={(_, d) => setContentType(d.value)} aria-label="Content type (optional)" /></Field>
              <Checkbox label="Set activation date" disabled />
              <Checkbox label="Set expiration date" disabled />
              <Field label="Enabled"><RadioGroup layout="horizontal" value={enabled ? "Yes" : "No"} onChange={(_, d) => setEnabled(d.value === "Yes")} aria-label="Enabled"><Radio value="Yes" label="Yes" /><Radio value="No" label="No" /></RadioGroup></Field>
              <div>Tags <span className="vy-muted">0 tags</span></div>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function SecretDetail({ self, name }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listSecretVersions(name), [name]);
  const [del, setDel] = useState(false);
  const [newVer, setNewVer] = useState(false);
  const backToList = () => navigate("keyvaults", self.split("/")[2], self.split("/")[3], "secrets");
  const versions = (data || []).map((v) => ({ ...api.parseSecretId(v.id), raw: v })).reverse();
  return (
    <>
      <div style={{ fontSize: 13, marginTop: 12 }}><Link href={`${self}/secrets`}>Secrets</Link> <span className="vy-muted">&gt;</span> {name}</div>
      <div className="vy-panel-title">{name}</div>
      {loading && <Loading />}
      <ErrorBar error={error} />
      <div className="vy-cmdbar" role="toolbar" aria-label="Secret commands">
        <ToolbarButton onClick={() => setNewVer(true)}>New Version</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowDownload20Regular />}>Download Backup</ToolbarButton>
      </div>
      <Table size="small" aria-label="Versions" style={{ marginTop: 8 }}>
        <TableHeader><TableRow><TableHeaderCell>Version</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Activation date</TableHeaderCell><TableHeaderCell>Expiration date</TableHeaderCell></TableRow></TableHeader>
        <TableBody>
          {versions.map((v, i) => (
            <TableRow key={v.version}>
              <TableCell><Link href={`${self}/secrets?secret=${encodeURIComponent(name)}&version=${encodeURIComponent(v.version)}`}>{v.version}</Link>{i === 0 && <span className="vy-muted"> CURRENT VERSION</span>}</TableCell>
              <TableCell>{v.raw.attributes?.enabled ? "Enabled" : "Disabled"}</TableCell>
              <TableCell>{v.raw.attributes?.nbf ? fmtDate(v.raw.attributes.nbf * 1000) : "--"}</TableCell>
              <TableCell>{v.raw.attributes?.exp ? fmtDate(v.raw.attributes.exp * 1000) : "--"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="secret" names={[name]}
        onConfirm={async () => { await api.deleteSecret(name); notify.success(`Secret '${name}' was deleted.`, "Delete succeeded"); backToList(); }} />
      <NewVersionDialog open={newVer} name={name} onClose={() => setNewVer(false)} onCreated={reload} />
    </>
  );
}

function NewVersionDialog({ open, name, onClose, onCreated }) {
  const notify = useNotify();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await api.setSecret(name, { value, attributes: { enabled: true } });
      notify.success(`A new version of '${name}' was created.`, "Version created");
      setValue(""); onClose(); onCreated();
    } catch (e) { notify.error(e, "Failed to create a new version"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="New version">
        <DialogBody>
          <DialogTitle>New version</DialogTitle>
          <DialogContent>
            <Field label="Secret value" required><Textarea value={value} onChange={(_, d) => setValue(d.value)} aria-label="Secret value" /></Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!value || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function SecretVersionDetail({ self, name, version }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getSecret(name, version), [name, version]);
  const [show, setShow] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [contentType, setContentType] = useState("");
  useEffect(() => { if (data) { setEnabled(data.attributes?.enabled !== false); setContentType(data.contentType || ""); } }, [data]);
  if (loading) return <Loading />;
  if (error) return <ErrorBar error={error} title="Failed to load the secret version" />;
  const attrs = data.attributes || {};
  const save = async () => {
    try {
      await api.setSecret(name, { value: data.value, contentType: contentType || undefined, attributes: { enabled } });
      notify.success(`Secret version for '${name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving secret version failed"); }
  };
  return (
    <>
      <div style={{ fontSize: 13, marginTop: 12 }}><Link href={`${self}/secrets`}>Secrets</Link> <span className="vy-muted">&gt;</span> <Link href={`${self}/secrets?secret=${encodeURIComponent(name)}`}>{name}</Link> <span className="vy-muted">&gt;</span> {version}</div>
      <div className="vy-panel-title">{version}</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Secret version commands">
        <ToolbarButton icon={<Save20Regular />} onClick={save}>Save</ToolbarButton>
        <ToolbarButton onClick={reload}>Discard changes</ToolbarButton>
      </div>
      <section className="vy-section" style={{ maxWidth: 760, display: "flex", flexDirection: "column", gap: 12 }}>
        <h3>Properties</h3>
        <Field label="Secret Identifier"><Input readOnly value={data.id} /></Field>
        <Checkbox label="Set activation date" checked={!!attrs.nbf} disabled />
        <Checkbox label="Set expiration date" checked={!!attrs.exp} disabled />
        <Field label="Enabled"><RadioGroup layout="horizontal" value={enabled ? "Yes" : "No"} onChange={(_, d) => setEnabled(d.value === "Yes")} aria-label="Enabled"><Radio value="Yes" label="Yes" /><Radio value="No" label="No" /></RadioGroup></Field>
        <div>Tags {Object.keys(data.tags || {}).length ? Object.entries(data.tags).map(([k, v]) => `${k}=${v}`).join(", ") : "--"}</div>
        <Field label="Content type (optional)"><Input value={contentType} onChange={(_, d) => setContentType(d.value)} aria-label="Content type (optional)" /></Field>
        <Field label="Secret value">
          <div style={{ display: "flex", gap: 4 }}>
            <Input readOnly type={show ? "text" : "password"} value={data.value} style={{ flex: 1 }} aria-label="Secret value" />
            <Button icon={show ? <EyeOff16Regular /> : <Eye16Regular />} onClick={() => setShow((v) => !v)}>{show ? "Hide" : "Show Secret Value"}</Button>
          </div>
        </Field>
      </section>
    </>
  );
}

// ── Certificates (no backing core) ────────────────────────────────────────────────────
function Certificates() {
  return (
    <>
      <div className="vy-panel-title">Certificates</div>
      <NotSimulated feature="Certificates (Name, Thumbprint, Status and Expiration date)"
        note={'Generate/Import, Restore Backup, Manage deleted certificates, Certificate Contacts and Certificate Authorities are not available, nor is the "Filter by name..." filter.'} />
    </>
  );
}

// ── Access configuration ──────────────────────────────────────────────────────────────
function AccessConfiguration({ a, reload }) {
  const notify = useNotify();
  const p = a.properties || {};
  const init = () => ({ rbac: !!p.enableRbacAuthorization, vm: !!p.enabledForDeployment, arm: !!p.enabledForTemplateDeployment, disk: !!p.enabledForDiskEncryption });
  const [f, setF] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(init()), [a]);
  const dirty = JSON.stringify(f) !== JSON.stringify(init());
  const save = async () => {
    setBusy(true);
    try {
      await api.updateVault(a.resourceGroup, a.name, { properties: { enableRbacAuthorization: f.rbac, enabledForDeployment: f.vm, enabledForTemplateDeployment: f.arm, enabledForDiskEncryption: f.disk } });
      notify.success(`Access configuration for '${a.name}' was saved.`, "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving access configuration failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Access configuration</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Access configuration commands">
        <ToolbarButton icon={<Save20Regular />} disabled={!dirty || busy} onClick={save}>Apply</ToolbarButton>
        <ToolbarButton disabled={!dirty} onClick={() => setF(init())}>Discard changes</ToolbarButton>
      </div>
      <section className="vy-section"><h3>Permission model</h3>
        <RadioGroup value={f.rbac ? "rbac" : "policy"} onChange={(_, d) => setF((x) => ({ ...x, rbac: d.value === "rbac" }))} aria-label="Permission model">
          <Radio value="rbac" label="Azure role-based access control (recommended)" />
          <Radio value="policy" label="Vault access policy" />
        </RadioGroup>
      </section>
      <section className="vy-section"><h3>Resource access</h3>
        <Checkbox label="Azure Virtual Machines for deployment" checked={f.vm} onChange={(_, d) => setF((x) => ({ ...x, vm: !!d.checked }))} />
        <Checkbox label="Azure Resource Manager for template deployment" checked={f.arm} onChange={(_, d) => setF((x) => ({ ...x, arm: !!d.checked }))} />
        <Checkbox label="Azure Disk Encryption for volume encryption" checked={f.disk} onChange={(_, d) => setF((x) => ({ ...x, disk: !!d.checked }))} />
      </section>
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
      await api.updateVault(a.resourceGroup, a.name, { properties: {
        publicNetworkAccess: v === "disabled" ? "Disabled" : "Enabled",
        networkAcls: { defaultAction: v === "selected" ? "Deny" : "Allow", bypass: "AzureServices" },
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
        <section className="vy-section" style={{ marginTop: 12 }}><h3>Firewalls and virtual networks</h3>
          <RadioGroup disabled={busy} value={value} onChange={(_, d) => save(d.value)} aria-label="Allow access from">
            <Radio value="all" label="Allow public access from all networks" />
            <Radio value="selected" label="Allow public access from specific virtual networks and IP addresses" />
            <Radio value="disabled" label="Disable public access" />
          </RadioGroup>
        </section>
      )}
      {tab === "private" && <NotSimulatedContainer title="Private endpoint connections" feature="Private endpoint connections for key vaults" />}
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
        <KV label="Name" value={a.name} />
        <KV label="Sku (Pricing tier)" value={api.skuLabel(p.sku)} />
        <KV label="Location" value={locationLabel(a.location)} />
        <KV label="Vault URI" value={api.vaultUri(a.name)} />
        <KV label="Resource ID" value={a.id} />
        <KV label="Directory ID" value={p.tenantId} />
        <KV label="Soft-delete" value={p.enableSoftDelete ? "Enabled" : "Disabled"} />
        <KV label="Days to retain deleted vaults" value={p.softDeleteRetentionInDays} />
        <KV label="Purge protection" value={p.enablePurgeProtection ? "Enabled" : "Disabled"} />
      </div>
    </>
  );
}

// ── Locks (no backing resource type) ──────────────────────────────────────────────────
function Locks() {
  return (
    <>
      <div className="vy-panel-title">Locks</div>
      <NotSimulated feature="Resource locks"
        note={'The Lock name, Lock type, Scope and Notes columns, "Add lock" (Lock name, Lock type and Notes fields), and the Add, Subscription, Resource group and Feedback commands are not available, nor is the "Search to filter items..." filter.'} />
    </>
  );
}

// ── Activity log (no backing core) ────────────────────────────────────────────────────
function ActivityLog() {
  return (
    <>
      <div className="vy-panel-title">Activity log</div>
      <NotSimulated feature="The activity log"
        note={"Its Operation name, Status, Time, Time stamp, Subscription and Event initiated by columns aren't backed by a Vyomi backend, and neither are the Activity, Edit columns, Export Activity Logs, Download as CSV, Insights, Feedback, Pin current filters or Reset filters commands."} />
    </>
  );
}

// ── Export template ────────────────────────────────────────────────────────────────────
function ExportTemplate({ a }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { vaultName: { type: "string", defaultValue: a.name } } } : {}),
    resources: [{ type: "Microsoft.KeyVault/vaults", apiVersion: api.ARM.apiVersion, name: params ? "[parameters('vaultName')]" : a.name, location: a.location, properties: a.properties }],
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
