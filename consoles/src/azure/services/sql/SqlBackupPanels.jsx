/* SQL database Replicas (active geo-replication) and Backups (short/long-term retention, point-in-time restore, copy, restore deleted)
 * over native ARM on Microsoft.Sql (core/azure_sqlbackup_core.py). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select, ToolbarButton } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { ErrorBar, InfoBar, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const Q = { "api-version": api.API_VERSION };
const dbId = (a, server = a.server, db = a.name) => `/subscriptions/${a.id.split("/")[2]}/resourceGroups/${a.resourceGroup}/providers/Microsoft.Sql/servers/${server}/databases/${db}`;
const put = (path, body) => restJson("PUT", path, { query: Q, body });
const get = (path) => restJson("GET", path, { query: Q });

function Dlg({ open, title, onClose, onOk, okLabel, err, children }) {
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={title}><DialogBody><DialogTitle>{title}</DialogTitle>
        <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}><ErrorBar error={err} title="Operation failed" />{children}</div></DialogContent>
        <DialogActions><Button appearance="primary" onClick={onOk}>{okLabel}</Button><Button onClick={onClose}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
    </Dialog>
  );
}

export function SqlReplicas({ a }) {
  const notify = useNotify();
  const links = useAsync(async () => (await get(`${dbId(a)}/replicaLinks`)).value || [], [a.id]);
  const servers = useAsync(() => api.listServers(), []);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ server: "", name: "" });
  const [err, setErr] = useState(null);
  const act = (l, verb, label) => async () => {
    try {
      const partner = l.properties?.role === "Primary" ? l.properties.partnerDatabase : a.name; // failover is issued on the secondary
      const secDb = l.properties?.role === "Secondary" ? a : null;
      const base = secDb ? dbId(a) : dbId(a, l.properties.partnerServer, l.properties.partnerDatabase);
      await restJson("POST", `${base}/replicaLinks/${encodeURIComponent(l.name)}/${verb}`, { query: Q, body: {} });
      notify.success(`${label} completed.`, label); links.reload();
    } catch (e) { notify.error(e, `${label} failed`); }
  };
  return (
    <>
      <div className="vy-panel-title">{a.name} | Replicas</div>
      <InfoBar title="Active geo-replication">The secondary is seeded from this database and every later write is replayed on it; it is read-only until failover or termination. Replication is synchronous in-process (no lag) and regions are labels.</InfoBar>
      <BrowseGrid resourceName="replica link" rowKey={(r) => r.id} items={links.data || []} loading={links.loading} error={links.error} onRefresh={links.reload} onCreate={() => { setErr(null); setOpen(true); }} csvName="replica-links.csv"
        extraCommands={(sel) => <>
          <ToolbarButton disabled={sel.length !== 1} onClick={act(sel[0], "failover", "Planned failover")}>Forced failover (planned)</ToolbarButton>
          <ToolbarButton disabled={sel.length !== 1} onClick={act(sel[0], "forceFailoverAllowDataLoss", "Forced failover")}>Forced failover (allow data loss)</ToolbarButton></>}
        onDelete={async (sel) => { for (const l of sel) { const base = l.properties?.role === "Secondary" ? dbId(a) : dbId(a, l.properties.partnerServer, l.properties.partnerDatabase); await restJson("DELETE", `${base}/replicaLinks/${encodeURIComponent(l.name)}`, { query: Q }); } notify.success("Replication terminated.", "Stop replication"); links.reload(); }}
        columns={[{ key: "r", label: "Role", value: (r) => r.properties?.role }, { key: "ps", label: "Partner server", value: (r) => r.properties?.partnerServer }, { key: "pd", label: "Partner database", value: (r) => r.properties?.partnerDatabase },
          { key: "pl", label: "Partner location", value: (r) => locationLabel(r.properties?.partnerLocation) }, { key: "st", label: "Replication state", value: (r) => r.properties?.replicationState }, { key: "m", label: "Replication mode", value: (r) => r.properties?.replicationMode }]}
        emptyAction={<Link as="button" onClick={() => setOpen(true)}>Create replica</Link>} />
      <Dlg open={open} title="Create geo-replica" okLabel="Create" onClose={() => setOpen(false)} err={err}
        onOk={async () => { setErr(null); try { const srv = (servers.data || []).find((s) => s.name === f.server);
          await put(dbId(a, f.server, f.name || a.name), { location: srv.location, properties: { createMode: "Secondary", sourceDatabaseId: dbId(a) } });
          notify.success(`Geo-replica '${f.name || a.name}' created on ${f.server}.`, "Create replica"); setOpen(false); links.reload(); } catch (e) { setErr(e); } }}>
        <Field label="Target server" required><Select value={f.server} onChange={(_, d) => setF({ ...f, server: d.value })} aria-label="Target server"><option value="">Select a server</option>{(servers.data || []).filter((s) => s.name !== a.server).map((s) => <option key={s.id} value={s.name}>{s.name} ({locationLabel(s.location)})</option>)}</Select></Field>
        <Field label="Database name" hint="Defaults to the primary's name."><Input value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} aria-label="Database name" /></Field>
      </Dlg>
    </>
  );
}

export function SqlBackups({ a }) {
  const notify = useNotify();
  const str = useAsync(async () => (await get(`${dbId(a)}/backupShortTermRetentionPolicies/default`)).properties || {}, [a.id]);
  const ltr = useAsync(async () => (await get(`${dbId(a)}/backupLongTermRetentionPolicies/default`)).properties || {}, [a.id]);
  const loc = a.location;
  const ltrBackups = useAsync(async () => (await get(`/subscriptions/${a.id.split("/")[2]}/providers/Microsoft.Sql/locations/${loc}/longTermRetentionServers/${a.server}/longTermRetentionDatabases/${a.name}/longTermRetentionBackups`)).value || [], [a.id]);
  const dropped = useAsync(async () => (await get(`/subscriptions/${a.id.split("/")[2]}/resourceGroups/${a.resourceGroup}/providers/Microsoft.Sql/servers/${a.server}/restorableDroppedDatabases`)).value || [], [a.id]);
  const [dlg, setDlg] = useState(null);
  const [f, setF] = useState({ target: "", time: "", days: "", diff: "12", weekly: "", monthly: "", yearly: "", week: "1" });
  const [err, setErr] = useState(null);
  const restore = async (props, label) => { setErr(null); try { await put(dbId(a, a.server, f.target), { location: loc, properties: props }); notify.success(`${label} '${f.target}' created.`, label); setDlg(null); ltrBackups.reload(); } catch (e) { setErr(e); } };
  const earliest = a.properties?.earliestRestoreDate || new Date(Date.now() - 6 * 864e5).toISOString();
  return (
    <>
      <div className="vy-panel-title">{a.name} | Backups</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Backup commands">
        <ToolbarButton onClick={() => { setErr(null); setF((o) => ({ ...o, target: `${a.name}_restored`, time: new Date().toISOString().slice(0, 19) + "Z" })); setDlg("pitr"); }}>Restore (point in time)</ToolbarButton>
        <ToolbarButton onClick={() => { setErr(null); setF((o) => ({ ...o, target: `${a.name}_copy` })); setDlg("copy"); }}>Copy</ToolbarButton>
        <ToolbarButton onClick={() => { setErr(null); setF((o) => ({ ...o, days: String(str.data?.retentionDays ?? 7), diff: String(str.data?.diffBackupIntervalInHours ?? 12) })); setDlg("str"); }}>Configure retention</ToolbarButton>
      </div>
      <div style={{ display: "flex", gap: 32, margin: "8px 0 16px" }}>
        <div><div style={{ fontSize: 12 }}>Earliest PITR restore point</div><div>{fmtDate(earliest)}</div></div>
        <div><div style={{ fontSize: 12 }}>Short-term retention</div><div>{str.data?.retentionDays ?? 7} days (differential every {str.data?.diffBackupIntervalInHours ?? 12} h)</div></div>
        <div><div style={{ fontSize: 12 }}>Long-term retention</div><div>weekly {ltr.data?.weeklyRetention || "PT0S"}, monthly {ltr.data?.monthlyRetention || "PT0S"}, yearly {ltr.data?.yearlyRetention || "PT0S"}</div></div>
      </div>
      <div className="vy-panel-title">Long-term retention backups</div>
      <BrowseGrid resourceName="long-term backup" rowKey={(r) => r.id} items={ltrBackups.data || []} loading={ltrBackups.loading} onRefresh={ltrBackups.reload} csvName="ltr-backups.csv"
        extraCommands={(sel) => <ToolbarButton disabled={sel.length !== 1} onClick={() => { setErr(null); setF((o) => ({ ...o, target: `${a.name}_ltr`, ltr: sel[0].id })); setDlg("ltr"); }}>Restore</ToolbarButton>}
        onDelete={async (sel) => { for (const b of sel) await restJson("DELETE", b.id, { query: Q }); notify.success("Backup deleted.", "Delete succeeded"); ltrBackups.reload(); }}
        columns={[{ key: "n", label: "Backup", value: (r) => r.name }, { key: "t", label: "Backup time", value: (r) => fmtDate(r.properties?.backupTime) }, { key: "e", label: "Expiry", value: (r) => fmtDate(r.properties?.backupExpirationTime) }]} />
      <div className="vy-panel-title" style={{ marginTop: 16 }}>Deleted databases</div>
      <BrowseGrid resourceName="deleted database" rowKey={(r) => r.id} items={dropped.data || []} loading={dropped.loading} onRefresh={dropped.reload} csvName="deleted-databases.csv"
        extraCommands={(sel) => <ToolbarButton disabled={sel.length !== 1} onClick={() => { setErr(null); setF((o) => ({ ...o, target: `${sel[0].properties?.databaseName}_restored`, dropped: sel[0].id })); setDlg("dropped"); }}>Restore</ToolbarButton>}
        columns={[{ key: "n", label: "Database", value: (r) => r.properties?.databaseName }, { key: "d", label: "Deletion date", value: (r) => fmtDate(r.properties?.deletionDate) }, { key: "c", label: "Creation date", value: (r) => fmtDate(r.properties?.creationDate) }]} />

      <Dlg open={dlg === "pitr"} title="Restore database (point in time)" okLabel="Review + create" onClose={() => setDlg(null)} err={err}
        onOk={() => restore({ createMode: "PointInTimeRestore", sourceDatabaseId: dbId(a), restorePointInTime: f.time }, "Restored database")}>
        <Field label="Database name" required><Input value={f.target} onChange={(_, d) => setF({ ...f, target: d.value })} aria-label="Database name" /></Field>
        <Field label="Restore point (UTC)" required hint={`Earliest: ${earliest}`}><Input value={f.time} onChange={(_, d) => setF({ ...f, time: d.value })} aria-label="Restore point" /></Field>
      </Dlg>
      <Dlg open={dlg === "copy"} title="Copy database" okLabel="Create" onClose={() => setDlg(null)} err={err}
        onOk={() => restore({ createMode: "Copy", sourceDatabaseId: dbId(a) }, "Database copy")}>
        <Field label="Database name" required><Input value={f.target} onChange={(_, d) => setF({ ...f, target: d.value })} aria-label="Database name" /></Field>
      </Dlg>
      <Dlg open={dlg === "ltr"} title="Restore from long-term backup" okLabel="Create" onClose={() => setDlg(null)} err={err}
        onOk={() => restore({ createMode: "RestoreLongTermRetentionBackup", recoveryServicesRecoveryPointId: f.ltr }, "Database restored from LTR")}>
        <Field label="Database name" required><Input value={f.target} onChange={(_, d) => setF({ ...f, target: d.value })} aria-label="Database name" /></Field>
      </Dlg>
      <Dlg open={dlg === "dropped"} title="Restore deleted database" okLabel="Create" onClose={() => setDlg(null)} err={err}
        onOk={() => restore({ createMode: "Restore", restorableDroppedDatabaseId: f.dropped }, "Restored deleted database")}>
        <Field label="Database name" required><Input value={f.target} onChange={(_, d) => setF({ ...f, target: d.value })} aria-label="Database name" /></Field>
      </Dlg>
      <Dlg open={dlg === "str"} title="Configure retention policies" okLabel="Apply" onClose={() => setDlg(null)} err={err}
        onOk={async () => { setErr(null); try {
          await put(`${dbId(a)}/backupShortTermRetentionPolicies/default`, { properties: { retentionDays: Number(f.days), diffBackupIntervalInHours: Number(f.diff) } });
          const p = { ...(f.weekly ? { weeklyRetention: f.weekly } : {}), ...(f.monthly ? { monthlyRetention: f.monthly } : {}), ...(f.yearly ? { yearlyRetention: f.yearly, weekOfYear: Number(f.week) } : {}) };
          if (Object.keys(p).length) await put(`${dbId(a)}/backupLongTermRetentionPolicies/default`, { properties: p });
          notify.success("Retention policies updated.", "Backup retention"); setDlg(null); str.reload(); ltr.reload(); ltrBackups.reload(); } catch (e) { setErr(e); } }}>
        <Field label="PITR retention (days, 1-35)"><Input value={f.days} onChange={(_, d) => setF({ ...f, days: d.value })} aria-label="PITR retention days" /></Field>
        <Field label="Differential backup frequency (hours)"><Select value={f.diff} onChange={(_, d) => setF({ ...f, diff: d.value })} aria-label="Differential frequency"><option>12</option><option>24</option></Select></Field>
        <Field label="Weekly LTR (ISO 8601, e.g. P4W)"><Input value={f.weekly} onChange={(_, d) => setF({ ...f, weekly: d.value })} aria-label="Weekly LTR" /></Field>
        <Field label="Monthly LTR (e.g. P12M)"><Input value={f.monthly} onChange={(_, d) => setF({ ...f, monthly: d.value })} aria-label="Monthly LTR" /></Field>
        <Field label="Yearly LTR (e.g. P5Y)"><Input value={f.yearly} onChange={(_, d) => setF({ ...f, yearly: d.value })} aria-label="Yearly LTR" /></Field>
      </Dlg>
    </>
  );
}
