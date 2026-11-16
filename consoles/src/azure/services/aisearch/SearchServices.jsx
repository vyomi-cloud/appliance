/* Azure AI Search browse blade + Create a search service (Microsoft.Search/searchServices, core/azure_search_core.py). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { LOCATIONS, listResourceGroups, locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { ErrorBar, Glyph } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export const link = (r) => `#/aisearch/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`;

export function CreateSearchService({ open, onClose, onCreated }) {
  const notify = useNotify();
  const rgs = useAsync(() => listResourceGroups(), []);
  const [f, setF] = useState({ name: "", rg: "", location: "eastus", sku: "basic" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const go = async () => {
    setBusy(true); setErr(null);
    try {
      await api.putService(f.rg, f.name, { location: f.location, sku: { name: f.sku }, properties: { replicaCount: 1, partitionCount: 1 } });
      notify.success(`Search service '${f.name}' was created.`, "Deployment succeeded");
      onCreated?.(f); onClose();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create a search service">
        <DialogBody>
          <DialogTitle>Create a search service</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Service name" required hint="2-60 characters: lowercase letters, digits and dashes."><Input value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} aria-label="Service name" /></Field>
              <Field label="Resource group" required><Select value={f.rg} onChange={(_, d) => setF({ ...f, rg: d.value })} aria-label="Resource group">
                <option value="">Select a resource group</option>{(rgs.data || []).map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}</Select></Field>
              <Field label="Location"><Select value={f.location} onChange={(_, d) => setF({ ...f, location: d.value })} aria-label="Location">
                {LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</Select></Field>
              <Field label="Pricing tier"><Select value={f.sku} onChange={(_, d) => setF({ ...f, sku: d.value })} aria-label="Pricing tier">
                {api.SKUS.map((s) => <option key={s} value={s}>{s}</option>)}</Select></Field>
              <ErrorBar error={err} title="Failed to create the search service" />
            </div>
          </DialogContent>
          <DialogActions><Button appearance="primary" disabled={!f.name || !f.rg || busy} onClick={go}>{busy ? "Creating..." : "Create"}</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

export default function SearchServices() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listServices(), [sub.id]);
  const [creating, setCreating] = useState(false);
  const subName = sub.displayName || sub.id;
  return (
    <>
      <TitleRow title="AI Search" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="cognitiveservices" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="search service" items={data || []} loading={loading} error={error} onRefresh={reload} onCreate={() => setCreating(true)}
          onDelete={async (rows) => { for (const r of rows) await api.deleteService(r.resourceGroup, r.name); notify.success(`Deleted ${rows.length} search service${rows.length === 1 ? "" : "s"}.`, "Delete succeeded"); reload(); }}
          subscriptionLabel={subName} csvName="ai-search.csv"
          pills={[{ key: "rg", label: "Resource group", value: (r) => r.resourceGroup }, { key: "loc", label: "Location", value: (r) => locationLabel(r.location) }]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={link(r)}>{r.name}</Link> },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "tier", label: "Pricing tier", value: (r) => r.sku?.name },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link as="button" onClick={() => setCreating(true)}>Create</Link>}
        />
      </div>
      <CreateSearchService open={creating} onClose={() => setCreating(false)} onCreated={(f) => { reload(); navigate("aisearch", encodeURIComponent(f.rg), encodeURIComponent(f.name)); }} />
    </>
  );
}
