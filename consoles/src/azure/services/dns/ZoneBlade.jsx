/* DNS zone resource blade: left resource menu + panels. Overview (record sets), Tags,
 * Virtual network links and Locks are backed by native ARM calls; Activity log is a real
 * (limited) read; everything else in the menu is an honest NotSimulated/CapabilityContainer
 * panel driven by core/capabilities/azure/dns.json. */
import { useEffect, useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link,
  Radio, RadioGroup, Select, Spinner, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular, Dismiss20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, fmtDate, Glyph, InfoBar, Loading, NotSimulatedContainer } from "../../kit/common.jsx";
import { remember, forget } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";
import { TagRows } from "./TagRows.jsx";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "activitylog", label: "Activity log" },
  { id: "iam", label: "Access control (IAM)" },
  { id: "tags", label: "Tags" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Settings", items: [{ id: "vnetlinks", label: "Virtual network links" }, { id: "locks", label: "Locks" }] },
  { group: "Automation", items: [{ id: "exporttemplate", label: "Export template" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));

export default function ZoneBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const zone = useAsync(() => api.getZone(rg, name), [rg, name]);
  const self = `#/dns/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (zone.data) remember({ name, type: "DNS zone", href: self }); }, [!!zone.data, self]);

  let body;
  if (zone.loading && !zone.data) body = <Loading />;
  else if (zone.error) body = <><ErrorBar error={zone.error} title="Failed to load the DNS zone" /><Link href="#/dns">Back to DNS zones</Link></>;
  else {
    const z = zone.data, reload = zone.reload;
    const P = {
      overview: () => <Overview z={z} rg={rg} reload={reload} self={self} />,
      tags: () => <Tags z={z} rg={rg} reload={reload} />,
      vnetlinks: () => <VnetLinks z={z} rg={rg} reload={reload} />,
      locks: () => <Locks z={z} rg={rg} />,
      activitylog: () => <ActivityLog z={z} rg={rg} />,
      iam: () => <Iam z={z} />,
      exporttemplate: () => <NotSimulatedContainer title={`${z.name} | Export template`} feature="ARM/Bicep/Terraform template export for a DNS zone" />,
      diagnose: () => <NotSimulatedContainer title={`${z.name} | Diagnose and solve problems`} feature="The guided DNS diagnostic tiles" />,
    }[panel];
    body = P ? P() : <NotSimulatedContainer title={`${z.name} | ${LABEL[panel] || panel}`} feature={`The ${LABEL[panel] || panel} panel`} />;
  }

  return (
    <ResourceBlade
      title={name} subtitle={`${zone.data?.properties?.zoneType === "Private" ? "Private " : ""}DNS zone`} glyph={<Glyph id="dns" />} closeHref="#/dns"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}
    >
      {body}
    </ResourceBlade>
  );
}

// ── Overview: Essentials + record sets ──────────────────────────────────────────────────
function Overview({ z, rg, reload, self }) {
  const notify = useNotify();
  const sub = useSubscription();
  const [del, setDel] = useState(false);
  const [edit, setEdit] = useState(null); // null | {} (new) | record set (edit)
  const p = z.properties || {};
  const tags = Object.entries(z.tags || {});
  const rs = useAsync(() => api.listRecordSets(rg, z.name), [rg, z.name, z.properties?.numberOfRecordSets]);
  const isPrivate = p.zoneType === "Private";
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { reload(); rs.reload(); }}>Refresh</ToolbarButton>
      </div>
      <Essentials
        left={[
          ["Resource group", <Link href="#/resourcegroups">{rg}</Link>],
          ["Location", "global"],
          ["Subscription", sub.displayName || sub.id],
          ["Subscription ID", sub.id],
          ["Zone type", p.zoneType || "Public"],
          ["Tags", <span>{tags.length ? tags.map(([k, v]) => `${k} : ${v}`).join(", ") : ""} <Link href={`${self}/tags`}>{tags.length ? "Edit" : "Add tags"}</Link></span>],
        ]}
        right={[
          ["Name servers", isPrivate ? "--" : (p.nameServers || []).join(", ")],
          ["Record set count", `${p.numberOfRecordSets ?? 0} of ${p.maxNumberOfRecordSets ?? "--"}`],
          ["Max records per record set", p.maxNumberOfRecordsPerRecordSet],
        ]}
      />
      <ErrorBar error={rs.error} />
      <BrowseGrid
        resourceName="record set" rowKey={(r) => r.id} filterPlaceholder="Search record sets"
        items={rs.data || []} loading={rs.loading} onRefresh={rs.reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setEdit({})}>Record set</ToolbarButton>}
        onDelete={async (sel) => {
          let failed = 0;
          for (const r of sel) {
            try { await api.deleteRecordSet(rg, z.name, api.recordSetType(r), r.name); }
            catch { failed++; }
          }
          if (failed) notify.error(new Error(`${failed} record set(s) couldn't be deleted (the SOA and apex NS record sets are managed by Azure DNS).`), "Delete failed");
          else notify.success(`Deleted ${sel.length} record set${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          rs.reload(); reload();
        }}
        csvName={`${z.name}-recordsets.csv`}
        columns={[
          { key: "name", label: "Name", render: (r) => <Link as="button" onClick={() => setEdit(r)}>{r.name}</Link> },
          { key: "type", label: "Type", value: (r) => api.recordSetType(r) },
          { key: "ttl", label: "TTL (seconds)", value: (r) => r.properties?.TTL },
          { key: "value", label: "Value", value: (r) => api.recordSetValue(r) },
        ]}
      />
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="DNS zone" names={[z.name]}
        onConfirm={async () => {
          await api.deleteZone(rg, z.name);
          forget(self);
          notify.success(`DNS zone '${z.name}' was deleted.`, "Delete succeeded");
          navigate("dns");
        }} />
      {edit !== null && (
        <RecordSetDialog zone={z} rg={rg} record={edit.name ? edit : null}
          onClose={() => setEdit(null)}
          onSaved={() => { setEdit(null); rs.reload(); reload(); }} />
      )}
    </>
  );
}

const nf = (v, lo, hi) => { const n = Number(v); return Number.isFinite(n) && n >= lo && n <= hi; };

function RecordSetDialog({ zone, rg, record, onClose, onSaved }) {
  const notify = useNotify();
  const editing = !!record;
  const existingType = record ? api.recordSetType(record) : null;
  const [name, setName] = useState(record?.name || "");
  const [type, setType] = useState(existingType || "A");
  const [ttl, setTtl] = useState(String(record?.properties?.TTL ?? 3600));
  const [alias, setAlias] = useState(!!record?.properties?.targetResource?.id);
  const [targetId, setTargetId] = useState(record?.properties?.targetResource?.id || "");
  const [rows, setRows] = useState(() => (record ? (api.recordSetRows(record).length ? api.recordSetRows(record) : [{}]) : [{}]));
  const [busy, setBusy] = useState(false);
  const spec = api.RECORD_FIELDS[type];
  const canAlias = api.ALIASABLE.includes(type);
  const addRow = () => setRows((r) => [...r, {}]);
  const setCell = (i, k, v) => setRows((r) => r.map((row, j) => (j === i ? { ...row, [k]: v } : row)));
  const delRow = (i) => setRows((r) => r.filter((_, j) => j !== i));

  const nameValid = name === "@" || /^[a-zA-Z0-9_*]([a-zA-Z0-9_-]*[a-zA-Z0-9_])?$/.test(name);
  const ttlValid = nf(ttl, 0, 2147483647);
  const rowsValid = alias ? !!targetId.trim() : rows.length > 0 && rows.every((row) => spec.fields.every((f) => (f.type === "number" ? nf(row[f.key], 0, 65535) : !!String(row[f.key] ?? "").trim())));
  const valid = nameValid && ttlValid && rowsValid;

  const save = async () => {
    setBusy(true);
    try {
      const properties = { TTL: Number(ttl) };
      if (alias) properties.targetResource = { id: targetId.trim() };
      else properties[api.ARM_FIELD[type]] = api.rowsToArmField(type, rows);
      await api.putRecordSet(rg, zone.name, type, name, { properties });
      notify.success(`Record set '${name}' was saved.`, editing ? "Record set updated" : "Record set created");
      onSaved();
    } catch (e) { notify.error(e, "Saving the record set failed"); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={editing ? "Edit record set" : "Add record set"}>
        <DialogBody>
          <DialogTitle action={<Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close" onClick={onClose} />}>{editing ? "Edit record set" : "Add record set"}</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required hint={`Fully qualified domain name: ${(name || "<name>")}${name === "@" ? "" : "."}${zone.name}`}
                validationMessage={name && !nameValid ? "Enter a valid record set name (or '@' for the zone apex)." : undefined}>
                <Input value={name} disabled={editing} onChange={(_, d) => setName(d.value)} aria-label="Name" />
              </Field>
              <Field label="Type" required>
                <Select value={type} disabled={editing} onChange={(_, d) => setType(d.value)} aria-label="Type">
                  {api.RECORD_TYPES.map((t) => <option key={t} value={t}>{t}{t === "CNAME" ? " - Canonical name" : t === "NS" ? " - Name server" : t === "MX" ? " - Mail exchange" : t === "PTR" ? " - Pointer" : t === "SRV" ? " - Service locator" : t === "TXT" ? " - Text" : t === "CAA" ? " - Certification Authority Authorization" : ""}</option>)}
                </Select>
              </Field>
              {canAlias && (
                <Field label="Alias record set">
                  <RadioGroup layout="horizontal" value={alias ? "yes" : "no"} onChange={(_, d) => setAlias(d.value === "yes")} aria-label="Alias record set">
                    <Radio value="no" label="No" /><Radio value="yes" label="Yes" />
                  </RadioGroup>
                </Field>
              )}
              <Field label="TTL" required validationMessage={ttl && !ttlValid ? "TTL must be between 0 and 2147483647 seconds." : undefined}>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <Input type="number" value={ttl} onChange={(_, d) => setTtl(d.value)} style={{ width: 160 }} aria-label="TTL" />
                  <span className="vy-muted">Seconds</span>
                </div>
              </Field>
              {alias ? (
                <Field label="Choose a resource" hint="Resource ID of the Azure resource this record set aliases.">
                  <Input value={targetId} onChange={(_, d) => setTargetId(d.value)} placeholder="/subscriptions/.../providers/..." aria-label="Alias target resource ID" />
                </Field>
              ) : (
                <RecordRows type={type} rows={rows} onCell={setCell} onAdd={addRow} onDelete={delRow} />
              )}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={save}>{busy ? "Saving..." : "OK"}</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function RecordRows({ type, rows, onCell, onAdd, onDelete }) {
  const spec = api.RECORD_FIELDS[type];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Table size="small" aria-label={`${type} records`}>
        <TableHeader><TableRow>{spec.fields.map((f) => <TableHeaderCell key={f.key}>{f.label}</TableHeaderCell>)}<TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow key={i}>
              {spec.fields.map((f) => (
                <TableCell key={f.key}>
                  {f.options ? (
                    <Select size="small" value={row[f.key] || f.options[0]} onChange={(_, d) => onCell(i, f.key, d.value)} aria-label={f.label}>
                      {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                    </Select>
                  ) : (
                    <Input size="small" type={f.type === "number" ? "number" : "text"} value={row[f.key] ?? ""} onChange={(_, d) => onCell(i, f.key, d.value)} aria-label={f.label} />
                  )}
                </TableCell>
              ))}
              <TableCell>{spec.multi && rows.length > 1 && <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label="Delete record" onClick={() => onDelete(i)} />}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {spec.multi && <Button size="small" onClick={onAdd}>Add record</Button>}
    </div>
  );
}

// ── Tags ───────────────────────────────────────────────────────────────────────────────
function Tags({ z, rg, reload }) {
  const notify = useNotify();
  const init = () => [...Object.entries(z.tags || {}).map(([name, value]) => ({ name, value })), { name: "", value: "" }];
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [z]);
  const apply = async () => {
    setBusy(true);
    try {
      await api.updateZone(rg, z.name, { tags: Object.fromEntries(rows.filter((t) => t.name).map((t) => [t.name, t.value])) });
      notify.success(`Tags on '${z.name}' were updated.`, "Tags saved");
      reload();
    } catch (e) { notify.error(e, "Saving tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{z.name} | Tags</div>
      <p style={{ fontSize: 13 }}>Tags are name/value pairs that enable you to categorize resources and view consolidated billing by applying the same tag to multiple resources and resource groups.</p>
      <TagRows tags={rows} onChange={setRows} resource={z.name} />
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <Button appearance="primary" disabled={busy} onClick={apply}>Apply</Button>
        <Button onClick={() => setRows(init())}>Discard changes</Button>
      </div>
    </>
  );
}

// ── Virtual network links (Microsoft.Network/dnszones properties.registration/resolutionVirtualNetworks) ──
function VnetLinks({ z, rg, reload }) {
  const notify = useNotify();
  const [add, setAdd] = useState(null); // null | "registration" | "resolution"
  const p = z.properties || {};
  const rows = [
    ...(p.registrationVirtualNetworks || []).map((v) => ({ ...v, linkType: "Registration" })),
    ...(p.resolutionVirtualNetworks || []).map((v) => ({ ...v, linkType: "Resolution" })),
  ];
  const remove = async (row) => {
    const field = row.linkType === "Registration" ? "registrationVirtualNetworks" : "resolutionVirtualNetworks";
    const next = (p[field] || []).filter((v) => v.id !== row.id);
    try {
      await api.updateZone(rg, z.name, { properties: { [field]: next } });
      notify.success("Virtual network link removed.", "Link removed");
      reload();
    } catch (e) { notify.error(e, "Removing the virtual network link failed"); }
  };
  return (
    <CapabilityContainer id="azure.dns.vnet_links" title={`${z.name} | Virtual network links`}
      actions={<>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd("registration")}>Add registration link</ToolbarButton>
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd("resolution")}>Add resolution link</ToolbarButton>
      </>}>
      <InfoBar>Registration links auto-register that virtual network's VM records (not simulated — records are still managed manually); resolution links let that virtual network resolve this zone's records.</InfoBar>
      <Table size="small" aria-label="Virtual network links">
        <TableHeader><TableRow><TableHeaderCell>Virtual network</TableHeaderCell><TableHeaderCell>Link type</TableHeaderCell><TableHeaderCell style={{ width: 48 }} /></TableRow></TableHeader>
        <TableBody>
          {rows.length ? rows.map((r) => (
            <TableRow key={r.linkType + r.id}>
              <TableCell>{r.id}</TableCell>
              <TableCell>{r.linkType}</TableCell>
              <TableCell><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Remove ${r.id}`} onClick={() => remove(r)} /></TableCell>
            </TableRow>
          )) : <TableRow><TableCell colSpan={3} className="vy-muted">No virtual network links.</TableCell></TableRow>}
        </TableBody>
      </Table>
      {add && (
        <AddVnetLinkDialog linkType={add} onClose={() => setAdd(null)}
          onCreate={async (id) => {
            const field = add === "registration" ? "registrationVirtualNetworks" : "resolutionVirtualNetworks";
            const next = [...(p[field] || []), { id }];
            await api.updateZone(rg, z.name, { properties: { [field]: next } });
            notify.success("Virtual network link added.", "Link added");
            reload();
          }} />
      )}
    </CapabilityContainer>
  );
}

function AddVnetLinkDialog({ linkType, onClose, onCreate }) {
  const notify = useNotify();
  const vnets = useAsync(() => api.listVirtualNetworks(), []);
  const [id, setId] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await onCreate(id); onClose(); }
    catch (e) { notify.error(e, "Failed to add the virtual network link"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={`Add ${linkType} link`}>
        <DialogBody>
          <DialogTitle>Add {linkType} link</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {vnets.data?.length ? (
                <Field label="Virtual network">
                  <Select value={id} onChange={(_, d) => setId(d.value)} aria-label="Virtual network">
                    <option value="">Select a virtual network</option>
                    {vnets.data.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                  </Select>
                </Field>
              ) : (
                <Field label="Virtual network resource ID" hint="No virtual networks found in this subscription yet — paste a resource ID, or create one under Virtual networks first.">
                  <Input value={id} onChange={(_, d) => setId(d.value)} placeholder="/subscriptions/.../providers/Microsoft.Network/virtualNetworks/..." aria-label="Virtual network resource ID" />
                </Field>
              )}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!id.trim() || busy} onClick={go}>Add</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ── Locks (Microsoft.Authorization/locks, scoped to this DNS zone) ─────────────────────
function Locks({ z, rg }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listLocks(rg, z.name), [rg, z.name]);
  const [add, setAdd] = useState(false);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.dns.locks" title={`${z.name} | Locks`}>
      <BrowseGrid
        resourceName="lock" rowKey={(r) => r.name} filterPlaceholder="Search to filter items..."
        items={rows} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.deleteLock(rg, z.name, r.name);
          notify.success(`Deleted ${sel.length} lock${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="locks.csv"
        columns={[
          { key: "name", label: "Lock name" },
          { key: "type", label: "Lock type", value: (r) => (r.properties?.level === "ReadOnly" ? "Read-only" : "Delete") },
          { key: "scope", label: "Scope", value: () => z.name },
          { key: "notes", label: "Notes", value: (r) => r.properties?.notes || "--" },
        ]}
      />
      <AddLockDialog open={add} onClose={() => setAdd(false)}
        onCreate={async (name, level, notes) => { await api.putLock(rg, z.name, name, { properties: { level, notes } }); reload(); }} />
    </CapabilityContainer>
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
    try {
      await onCreate(name, type === "Read-only" ? "ReadOnly" : "CanNotDelete", notes);
      notify.success(`Lock '${name}' was added.`, "Lock added");
      setName(""); setNotes(""); setType("Delete"); onClose();
    } catch (e) { notify.error(e, "Failed to add lock"); }
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
                <Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Lock type">
                  <option>Read-only</option><option>Delete</option>
                </Select>
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

// ── Activity log (Microsoft.Insights/eventtypes/management/values, scoped to this zone) ──
function ActivityLog({ z, rg }) {
  const { data, loading, error, reload } = useAsync(() => api.listActivityLog(rg, z.name), [rg, z.name]);
  const rows = data || [];
  return (
    <CapabilityContainer id="azure.dns.activity_log" title={`${z.name} | Activity log`}
      actions={<ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>}>
      <ErrorBar error={error} />
      <table className="vy-grid">
        <thead><tr><th>Operation name</th><th>Status</th><th>Time</th><th>Time stamp</th><th>Subscription</th><th>Event initiated by</th></tr></thead>
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
    </CapabilityContainer>
  );
}

// ── Access control (IAM) — honest gap (menu item; title only, like the storage pilot's
// Diagnose and solve problems) ──────────────────────────────────────────────────────────
function Iam({ z }) {
  return <CapabilityContainer id="azure.dns.iam" title={`${z.name} | Access control (IAM)`} />;
}
