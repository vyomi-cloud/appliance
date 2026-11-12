/* SQL database | Database watcher and Sync to other databases - both run against the database's real engine
 * (core/azure_sql_ext_core.py).  The watcher samples while this page is open (no background collector). */
import { useEffect, useState } from "react";
import { Button, Field, Select, Switch, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorBar, Loading, fmtBytes } from "../../kit/common.jsx";
import * as api from "./api.js";

const Grid = ({ cols, rows, empty, label }) => (
  <Table size="small" aria-label={label}>
    <TableHeader><TableRow>{cols.map((c) => <TableHeaderCell key={c.l}>{c.l}</TableHeaderCell>)}</TableRow></TableHeader>
    <TableBody>
      {rows.length === 0 && <TableRow><TableCell colSpan={cols.length}>{empty}</TableCell></TableRow>}
      {rows.map((r, i) => <TableRow key={i}>{cols.map((c) => <TableCell key={c.l}>{c.v(r)}</TableCell>)}</TableRow>)}
    </TableBody>
  </Table>
);

export function DatabaseWatcher({ a }) {
  const notify = useNotify();
  const w = useAsync(() => api.watcherGet(a.server, a.name), [a.id]);
  const [auto, setAuto] = useState(true);
  const collect = async () => { try { await api.watcherCollect(a.server, a.name); w.reload(); } catch (e) { notify.error(e, "Collecting a sample failed"); } };
  useEffect(() => { collect(); }, [a.id]);
  useEffect(() => { if (!auto) return undefined; const t = setInterval(collect, 10000); return () => clearInterval(t); }, [auto, a.id]);
  const d = w.data;
  return (
    <>
      <div className="vy-panel-title">Database watcher</div>
      <p>Samples the live database engine (size, every table's real row count, measured statement latency and failures). Collection runs while this page is open; nothing is collected in the background.</p>
      <div style={{ display: "flex", gap: 12, alignItems: "center" }}><Button onClick={collect}>Collect sample now</Button><Switch checked={auto} onChange={(_, x) => setAuto(x.checked)} label="Collect every 10 s" /></div>
      {w.error && <ErrorBar error={w.error} title="Could not read the watcher" />}
      {w.loading && !d ? <Loading /> : d && (
        <>
          <h3>Alerts</h3>
          <Grid label="Alerts" cols={[{ l: "Severity", v: (x) => x.severity }, { l: "Message", v: (x) => x.message }]} rows={d.alerts} empty="No alerts." />
          <h3>Latest sample{d.latest ? ` (${new Date(d.latest.ts * 1000).toLocaleTimeString()})` : ""}</h3>
          {d.latest && <p>Size {fmtBytes(d.latest.sizeBytes)} - {d.latest.totalRows} rows - {d.latest.statements} statements in the last minute (p95 {d.latest.p95Ms} ms, {d.latest.failed} failed)</p>}
          <Grid label="Tables" cols={[{ l: "Table", v: (x) => x.name }, { l: "Rows", v: (x) => x.rows }]} rows={d.latest?.tables || []} empty="No tables." />
          <h3>History ({d.sampleCount} samples)</h3>
          <Grid label="Samples" cols={[{ l: "Time", v: (x) => new Date(x.ts * 1000).toLocaleTimeString() }, { l: "Size", v: (x) => fmtBytes(x.sizeBytes) }, { l: "Rows", v: (x) => x.totalRows }, { l: "Statements", v: (x) => x.statements }, { l: "p95 ms", v: (x) => x.p95Ms }, { l: "Failed", v: (x) => x.failed }]} rows={[...d.samples].reverse().slice(0, 30)} empty="No samples." />
        </>
      )}
    </>
  );
}

export function SyncDatabases({ a }) {
  const notify = useNotify();
  const dbs = useAsync(() => api.listAllDatabases(), []);
  const hist = useAsync(() => api.syncHistory(a.server, a.name), [a.id]);
  const [member, setMember] = useState(""); const [conflict, setConflict] = useState("hub-wins"); const [del, setDel] = useState(false); const [busy, setBusy] = useState(false);
  const others = (dbs.data || []).filter((d) => d.id !== a.id && !/\/master$/i.test(d.id));
  const run = async () => {
    setBusy(true);
    try {
      const [srv, name] = member.split("::");
      const r = await api.syncRun(a.server, a.name, { memberServer: srv, memberDatabase: name, conflict, deleteMissing: del });
      notify.success(`${r.status}: ${r.tables.map((t) => `${t.table} +${t.inserted ?? 0} ~${t.updated ?? 0} -${t.deleted ?? 0}`).join(", ") || "no tables"}`, "Sync");
      hist.reload();
    } catch (e) { notify.error(e, "Sync failed"); } finally { setBusy(false); }
  };
  const sname = (d) => d.id.split("/servers/")[1]?.split("/")[0];
  return (
    <>
      <div className="vy-panel-title">Sync to other databases</div>
      <p>This database is the hub. A run copies its tables (creating them in the member from the hub's own definition when missing) and upserts rows by primary key into the member database. One direction per run; run it the other way for bidirectional sync.</p>
      <Field label="Member database"><Select value={member} onChange={(_, d) => setMember(d.value)}><option value="">Select…</option>{others.map((d) => <option key={d.id} value={`${sname(d)}::${d.name.split("/").pop()}`}>{sname(d)} / {d.name.split("/").pop()}</option>)}</Select></Field>
      <Field label="On conflict"><Select value={conflict} onChange={(_, d) => setConflict(d.value)}><option value="hub-wins">Hub wins (overwrite)</option><option value="skip">Keep the member's row</option></Select></Field>
      <Switch checked={del} onChange={(_, x) => setDel(x.checked)} label="Delete member rows that no longer exist in the hub" />
      <div style={{ marginTop: 8 }}><Button appearance="primary" disabled={!member || busy} onClick={run}>Sync now</Button></div>
      <h3>History</h3>
      <Grid label="Sync history" cols={[{ l: "When", v: (x) => new Date(x.ts * 1000).toLocaleString() }, { l: "Member", v: (x) => x.member }, { l: "Status", v: (x) => x.status }, { l: "Result", v: (x) => x.tables.map((t) => (t.error ? `${t.table}: ${t.error}` : `${t.table} +${t.inserted} ~${t.updated} -${t.deleted}`)).join("; ") }]} rows={[...(hist.data || [])].reverse()} empty="No syncs yet." />
    </>
  );
}
