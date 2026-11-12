/* Browse-grid command-bar tools shared by every Azure list blade:
 *  - Open query: a real Azure Resource Graph query (minimal KQL subset evaluated over the ARM
 *    engine's own resource store, core/azure_arm_core.py _resource_graph);
 *  - Assign tags: real ARM PATCHes that MERGE the tags onto every selected resource.
 * Rows must be ARM resources (an `id`). Used through BrowseGrid's `tools` prop. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Input, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea } from "@fluentui/react-components";
import { restJson } from "../../common/wire.js";
import { useNotify } from "../../common/notify.jsx";
import { getSubscription } from "./arm.js";

// Subscription-prefixed form (the shared core also answers real ARG's tenant-level path on Nano; the
// offline router only mounts /subscriptions/*).
export const graphQuery = (query) => restJson("POST", `/subscriptions/${getSubscription()}/providers/Microsoft.ResourceGraph/resources`,
  { query: { "api-version": "2021-03-01" }, body: { subscriptions: [getSubscription()], query } });

export function OpenQueryDialog({ open, onClose, type }) {
  const notify = useNotify();
  const [q, setQ] = useState(`Resources\n${type ? `| where type =~ '${type}'\n` : ""}| project name, type, resourceGroup, location\n| limit 100`);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setResult((await graphQuery(q)).data); } catch (e) { notify.error(e, "Query run failed"); setResult(null); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Open query" style={{ maxWidth: 760 }}>
        <DialogBody>
          <DialogTitle>Resource Graph Explorer</DialogTitle>
          <DialogContent>
            <p style={{ fontSize: 13 }}>A real, minimal Kusto subset evaluated over Vyomi's own ARM resource store (tables <code>Resources</code> and <code>ResourceContainers</code>; <code>where</code>, <code>project</code>, <code>limit</code>, <code>count</code>).</p>
            <Textarea value={q} onChange={(_, d) => setQ(d.value)} rows={5} style={{ width: "100%", fontFamily: "monospace" }} aria-label="Query" />
            <div className="vy-cmdbar" style={{ marginTop: 8 }}><Button appearance="primary" disabled={busy} onClick={run}>Run query</Button></div>
            {result && (
              <Table size="small" aria-label="Query results" style={{ marginTop: 12 }}>
                <TableHeader><TableRow>{result.columns.map((c) => <TableHeaderCell key={c.name}>{c.name}</TableHeaderCell>)}</TableRow></TableHeader>
                <TableBody>
                  {result.rows.length ? result.rows.map((row, i) => <TableRow key={i}>{row.map((v, j) => <TableCell key={j}>{typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}</TableCell>)}</TableRow>)
                    : <TableRow><TableCell colSpan={result.columns.length} className="vy-muted">No results</TableCell></TableRow>}
                </TableBody>
              </Table>
            )}
          </DialogContent>
          <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

const API = "2023-01-01";
export function AssignTagsDialog({ rows, onClose, onDone }) {
  const notify = useNotify();
  const [tags, setTags] = useState([{ name: "", value: "" }]);
  const [busy, setBusy] = useState(false);
  if (!rows) return null;
  const upd = (i, k, v) => {
    const xs = tags.map((t, j) => (j === i ? { ...t, [k]: v } : t));
    if (xs[xs.length - 1].name || xs[xs.length - 1].value) xs.push({ name: "", value: "" });
    setTags(xs);
  };
  const go = async () => {
    const add = Object.fromEntries(tags.filter((t) => t.name).map((t) => [t.name, t.value]));
    setBusy(true);
    try {
      for (const r of rows) {
        const cur = await restJson("GET", r.id, { query: { "api-version": API } });
        await restJson("PATCH", r.id, { query: { "api-version": API }, body: { tags: { ...(cur.tags || {}), ...add } } });
      }
      notify.success(`Tags were assigned to ${rows.length} resource${rows.length === 1 ? "" : "s"}.`, "Assign tags succeeded");
      setTags([{ name: "", value: "" }]); onClose(); onDone?.();
    } catch (e) { notify.error(e, "Assign tags failed"); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Assign tags">
        <DialogBody>
          <DialogTitle>Assign tags</DialogTitle>
          <DialogContent>
            <p style={{ fontSize: 13 }}>Apply tags to the {rows.length} selected resource{rows.length === 1 ? "" : "s"}. Existing tags on each resource are kept.</p>
            <Table size="small" aria-label="Tags">
              <TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell></TableRow></TableHeader>
              <TableBody>{tags.map((t, i) => (
                <TableRow key={i}>
                  <TableCell><Input size="small" value={t.name} onChange={(_, d) => upd(i, "name", d.value)} aria-label={`Tag name ${i + 1}`} /></TableCell>
                  <TableCell><Input size="small" value={t.value} onChange={(_, d) => upd(i, "value", d.value)} aria-label={`Tag value ${i + 1}`} /></TableCell>
                </TableRow>))}</TableBody>
            </Table>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || !tags.some((t) => t.name)} onClick={go}>Apply</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
