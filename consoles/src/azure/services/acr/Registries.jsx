/* Container registries browse blade (ARM list at subscription scope). "Manage view" is
 * BrowseGrid's own column chooser (real, no backend needed — a console preference). "Open
 * query" runs a real Azure Resource Graph query (api.queryResourceGraph, a minimal KQL subset
 * evaluated over the ARM engine's own resource store) and "Assign tags" PATCHes real tags onto
 * every selected registry (azure.acr.registry.listactions). */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Link,
  Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Search20Regular, TagMultiple20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";
import { TagRows } from "../keyvaults/KeyVaultBlade.jsx";

const DEFAULT_QUERY = "Resources\n| where type =~ 'microsoft.containerregistry/registries'\n| project name, resourceGroup, location";

export default function Registries() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listRegistries(), [sub.id]);
  const subName = sub.displayName || sub.id;
  const [query, setQuery] = useState(false);
  const [tagsFor, setTagsFor] = useState(null); // selected rows to bulk-tag
  return (
    <>
      <TitleRow title="Container registries" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="acr" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="container registry"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("acr", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteRegistry(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} container registr${rows.length === 1 ? "y" : "ies"}.`, "Delete succeeded");
            reload();
          }}
          extraCommands={(selected) => <>
            <ToolbarButton icon={<Search20Regular />} onClick={() => setQuery(true)}>Open query</ToolbarButton>
            <ToolbarButton icon={<TagMultiple20Regular />} disabled={!selected.length} onClick={() => setTagsFor(selected)}>Assign tags</ToolbarButton>
          </>}
          subscriptionLabel={subName}
          csvName="container-registries.csv"
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/acr/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "type", label: "Type", value: () => "Container Registry" },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/acr/create">Create container registry</Link>}
        />
        <OpenQueryDialog open={query} onClose={() => setQuery(false)} />
        <AssignTagsDialog rows={tagsFor} onClose={() => setTagsFor(null)} onDone={reload} />
      </div>
    </>
  );
}

// ── Open query (Azure Resource Graph) ──────────────────────────────────────────────────
function OpenQueryDialog({ open, onClose }) {
  const notify = useNotify();
  const [q, setQ] = useState(DEFAULT_QUERY);
  const [result, setResult] = useState(null); // {columns, rows}
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const r = await api.queryResourceGraph(q);
      setResult(r.data);
    } catch (e) { notify.error(e, "Query run failed"); setResult(null); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Open query" style={{ maxWidth: 760 }}>
        <DialogBody>
          <DialogTitle>Resource Graph Explorer</DialogTitle>
          <DialogContent>
            <p style={{ fontSize: 13 }}>A real, minimal Kusto query subset evaluated over Vyomi's own ARM resource store (table <code>Resources</code>; <code>where</code>/<code>project</code>/<code>limit</code>/<code>order by</code>/<code>count</code>).</p>
            <Textarea value={q} onChange={(_, d) => setQ(d.value)} rows={4} style={{ width: "100%", fontFamily: "monospace" }} aria-label="Query" />
            <div className="vy-cmdbar" style={{ marginTop: 8 }}><Button appearance="primary" disabled={busy} onClick={run}>Run query</Button></div>
            {result && (
              <Table size="small" aria-label="Query results" style={{ marginTop: 12 }}>
                <TableHeader><TableRow>{result.columns.map((c) => <TableHeaderCell key={c.name}>{c.name}</TableHeaderCell>)}</TableRow></TableHeader>
                <TableBody>
                  {result.rows.length ? result.rows.map((row, i) => (
                    <TableRow key={i}>{row.map((v, j) => <TableCell key={j}>{typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}</TableCell>)}</TableRow>
                  )) : <TableRow><TableCell colSpan={result.columns.length} className="vy-muted">No results</TableCell></TableRow>}
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

// ── Assign tags (bulk, merged onto every selected registry) ───────────────────────────
function AssignTagsDialog({ rows, onClose, onDone }) {
  const notify = useNotify();
  const [tags, setTags] = useState([{ name: "", value: "" }]);
  const [busy, setBusy] = useState(false);
  if (!rows) return null;
  const go = async () => {
    const add = Object.fromEntries(tags.filter((t) => t.name).map((t) => [t.name, t.value]));
    if (!Object.keys(add).length) return;
    setBusy(true);
    try {
      for (const r of rows) await api.updateRegistry(r.resourceGroup, r.name, { tags: add });
      notify.success(`Tags were assigned to ${rows.length} container registr${rows.length === 1 ? "y" : "ies"}.`, "Assign tags succeeded");
      setTags([{ name: "", value: "" }]); onClose(); onDone();
    } catch (e) { notify.error(e, "Assign tags failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Assign tags">
        <DialogBody>
          <DialogTitle>Assign tags</DialogTitle>
          <DialogContent>
            <p style={{ fontSize: 13 }}>Apply tags to the {rows.length} selected resource{rows.length === 1 ? "" : "s"}. Existing tags on each resource are kept.</p>
            <TagRows tags={tags} onChange={setTags} resource={`${rows.length} resource${rows.length === 1 ? "" : "s"}`} />
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
