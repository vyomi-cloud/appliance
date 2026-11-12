/* Cosmos "Data Migration" and "Add Azure Function" blades.  Both drive real engines:
 *   - Data Migration  -> POST /vyomi/migrations (core/azure_cosmos_core.migrate): copies rows container->container or from
 *     pasted/uploaded JSON through the data-plane write path (change feed + cosmosDBTrigger functions see the rows).
 *   - Add Azure Function -> creates a real cosmosDBTrigger function in a Function App (Microsoft.Web) bound to this account;
 *     every later write to the container runs it through the Function App invoke path. */
import { useState } from "react";
import { Button, Field, Input, Select, Textarea, Radio, RadioGroup, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useSubscription } from "../../kit/subscription.js";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

const JobTable = ({ jobs }) => (
  <Table size="small" aria-label="Migration history">
    <TableHeader><TableRow>{["Source", "Target", "Status", "Read", "Created", "Replaced", "Skipped", "Failed"].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
    <TableBody>
      {jobs.length === 0 && <TableRow><TableCell colSpan={8}>No migrations run yet.</TableCell></TableRow>}
      {[...jobs].reverse().map((j) => (
        <TableRow key={j.id}><TableCell>{j.source}</TableCell><TableCell>{j.target}</TableCell><TableCell>{j.status}{j.dryRun ? " (dry run)" : ""}</TableCell>
          <TableCell>{j.read}</TableCell><TableCell>{j.created}</TableCell><TableCell>{j.replaced}</TableCell><TableCell>{j.skipped}</TableCell><TableCell>{j.failed}</TableCell></TableRow>
      ))}
    </TableBody>
  </Table>
);

export function DataMigration({ a }) {
  const notify = useNotify();
  const dbs = useAsync(() => api.listAllContainers(a.resourceGroup, a.name), [a.id]);
  const hist = useAsync(() => api.listMigrations(), [a.id]);
  const [kind, setKind] = useState("container");
  const [f, setF] = useState({ src: "", query: "", tdb: "", tcoll: "", pk: "/id", conflict: "upsert", json: "", rename: "", drop: "" });
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState(null);
  const set = (k) => (_, d) => setF({ ...f, [k]: d.value });
  const list = dbs.data || [];
  const run = async (dryRun) => {
    setBusy(true);
    try {
      const [sdb, scoll] = f.src.split("::");
      const mapping = {};
      if (f.rename.trim()) mapping.rename = Object.fromEntries(f.rename.split(",").map((p) => p.split("=").map((x) => x.trim())).filter((p) => p[0] && p[1]));
      if (f.drop.trim()) mapping.drop = f.drop.split(",").map((x) => x.trim()).filter(Boolean);
      const job = await api.migrate({
        source: kind === "json" ? { type: "json", data: f.json } : { type: "container", database: sdb, container: scoll, query: f.query || undefined },
        target: { database: f.tdb, container: f.tcoll, partitionKeyPath: f.pk }, conflict: f.conflict, mapping, dryRun,
      });
      setLast(job);
      (job.status === "Failed" ? notify.error : notify.success)(job.error || `${dryRun ? "Dry run: " : ""}${job.migrated} of ${job.read} documents ${dryRun ? "would be" : ""} migrated.`, job.status);
      hist.reload(); dbs.reload();
    } catch (e) { notify.error(e, "Migration failed"); } finally { setBusy(false); }
  };
  const ready = f.tdb && f.tcoll && (kind === "json" ? f.json.trim() : f.src);
  return (
    <>
      <div className="vy-panel-title">Data Migration</div>
      <p>Copies documents into a target container for real, through the same write path as the data plane (new system properties, change feed entries, <code>cosmosDBTrigger</code> functions fire). The target container is created if it does not exist.</p>
      <div className="vy-cmdbar" role="toolbar"><ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { hist.reload(); dbs.reload(); }}>Refresh</ToolbarButton></div>
      <RadioGroup layout="horizontal" value={kind} onChange={(_, d) => setKind(d.value)}>
        <Radio value="container" label="Source: container" /><Radio value="json" label="Source: JSON documents" />
      </RadioGroup>
      {kind === "container" ? (
        <>
          <Field label="Source container"><Select value={f.src} onChange={set("src")}><option value="">Select…</option>{list.map((c) => <option key={`${c.database}::${c.id}`} value={`${c.database}::${c.id}`}>{c.database} / {c.id}</option>)}</Select></Field>
          <Field label="Source query (optional)"><Input value={f.query} onChange={set("query")} placeholder="SELECT * FROM c WHERE c.status = 'active'" /></Field>
        </>
      ) : <Field label="JSON array of documents (each needs an id)"><Textarea rows={6} value={f.json} onChange={set("json")} placeholder='[{"id":"1","name":"a"}]' /></Field>}
      <Field label="Target database"><Input value={f.tdb} onChange={set("tdb")} /></Field>
      <Field label="Target container"><Input value={f.tcoll} onChange={set("tcoll")} /></Field>
      <Field label="Target partition key (used only if the container is created)"><Input value={f.pk} onChange={set("pk")} /></Field>
      <Field label="If a document id already exists"><Select value={f.conflict} onChange={set("conflict")}><option value="upsert">Replace (upsert)</option><option value="skip">Skip</option><option value="fail">Stop with an error</option></Select></Field>
      <Field label="Rename fields (old=new, comma separated)"><Input value={f.rename} onChange={set("rename")} /></Field>
      <Field label="Drop fields (comma separated)"><Input value={f.drop} onChange={set("drop")} /></Field>
      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        <Button appearance="primary" disabled={!ready || busy} onClick={() => run(false)}>Migrate</Button>
        <Button disabled={!ready || busy} onClick={() => run(true)}>Dry run</Button>
      </div>
      {last?.errors?.length > 0 && <ErrorBar error={{ message: last.errors.join("; ") }} title="Row errors" />}
      <h3>History</h3>
      {hist.loading && !hist.data ? <Loading /> : <JobTable jobs={hist.data || []} />}
    </>
  );
}

const CODE = "def main(req):\n    docs = req['body']['documents']\n    return {'processed': len(docs)}\n";
export function AddFunction({ a }) {
  const notify = useNotify();
  const sub = useSubscription();
  const apps = useAsync(() => api.listFunctionApps(sub.id), [sub.id]);
  const conts = useAsync(() => api.listAllContainers(a.resourceGroup, a.name), [a.id]);
  const [app, setApp] = useState("");
  const [fn, setFn] = useState("onCosmosChange");
  const [cont, setCont] = useState("");
  const [busy, setBusy] = useState(false);
  const wired = useAsync(async () => {
    const out = [];
    for (const s of apps.data || []) {
      const settings = await api.getAppSettings(s.id).catch(() => ({}));
      for (const f of await api.listFunctions(s.id).catch(() => [])) {
        for (const b of f.properties?.config?.bindings || []) {
          if (String(b.type).toLowerCase() !== "cosmosdbtrigger") continue;
          const conn = settings[b.connection] || settings[`${b.connection}__accountEndpoint`] || "";
          if (conn.toLowerCase().includes(`${a.name.toLowerCase()}.documents.azure.com`)) out.push({ site: s, name: f.name.split("/").pop(), db: b.databaseName, container: b.containerName });
        }
      }
    }
    return out;
  }, [apps.data]);
  const add = async () => {
    setBusy(true);
    try {
      const site = (apps.data || []).find((s) => s.id === app);
      const [db, c] = cont.split("::");
      const keys = await api.listKeys(a.resourceGroup, a.name).catch(() => ({}));
      await api.patchAppSettings(site.id, { COSMOS_CONN: `AccountEndpoint=${api.accountEndpoint(a.name)};AccountKey=${keys.primaryMasterKey || ""};` });
      await api.putFunction(site.id, fn, [{ type: "cosmosDBTrigger", direction: "in", name: "documents", databaseName: db, containerName: c, connection: "COSMOS_CONN" }], CODE);
      notify.success(`Function '${fn}' now runs on every change to ${db}/${c}.`, "Function added");
      wired.reload();
    } catch (e) { notify.error(e, "Adding the function failed"); } finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">Add Azure Function</div>
      <p>Creates a <code>cosmosDBTrigger</code> function in one of your Function Apps, bound to a container of this account. The function runs for real (sandboxed) for each write and appears in the Function App's invocation log.</p>
      {apps.error && <ErrorBar error={apps.error} title="Could not list Function Apps" />}
      <Field label="Function App"><Select value={app} onChange={(_, d) => setApp(d.value)}><option value="">Select…</option>{(apps.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      {apps.data && apps.data.length === 0 && <p>No Function App exists in this subscription. Create one from Function App first.</p>}
      <Field label="Container"><Select value={cont} onChange={(_, d) => setCont(d.value)}><option value="">Select…</option>{(conts.data || []).map((c) => <option key={`${c.database}::${c.id}`} value={`${c.database}::${c.id}`}>{c.database} / {c.id}</option>)}</Select></Field>
      <Field label="Function name"><Input value={fn} onChange={(_, d) => setFn(d.value)} /></Field>
      <div style={{ marginTop: 12 }}><Button appearance="primary" disabled={!app || !cont || !fn || busy} onClick={add}>Add function</Button></div>
      <h3>Functions triggered by this account</h3>
      <Table size="small" aria-label="Functions wired to this account">
        <TableHeader><TableRow>{["Function", "Function App", "Database", "Container", ""].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
        <TableBody>
          {(wired.data || []).length === 0 && <TableRow><TableCell colSpan={5}>None.</TableCell></TableRow>}
          {(wired.data || []).map((w) => (
            <TableRow key={w.site.id + w.name}><TableCell>{w.name}</TableCell><TableCell>{w.site.name}</TableCell><TableCell>{w.db}</TableCell><TableCell>{w.container}</TableCell>
              <TableCell><Button size="small" icon={<Delete20Regular />} aria-label={`Remove ${w.name}`} onClick={async () => { await api.deleteFunction(w.site.id, w.name); wired.reload(); }} /></TableCell></TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}
