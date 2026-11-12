/* Subscriptions panel: real ARM sub-resource of the service. Primary/secondary keys are
 * generated client-side (the same "clearly-fake simulator token" convention the generic ARM
 * listKeys/regenerateKey action uses) and stored/returned exactly as any other property. */
import { useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input,
  Select, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-]{0,255}$/;

export default function Subscriptions({ rg, svc }) {
  const notify = useNotify();
  const subs = useAsync(() => api.Subscriptions.list(rg, svc), [rg, svc]);
  const products = useAsync(() => api.Products.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <>
      <div className="vy-panel-title">{svc} | Subscriptions</div>
      <BrowseGrid
        resourceName="subscription" rowKey={(r) => r.name} filterPlaceholder="Search subscriptions"
        items={subs.data || []} loading={subs.loading} error={subs.error} onRefresh={subs.reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add subscription</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.Subscriptions.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} subscription${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          subs.reload();
        }}
        csvName="subscriptions.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "displayName", label: "Display name", value: (r) => r.properties?.displayName || r.name },
          { key: "primaryKey", label: "Primary key", value: (r) => r.properties?.primaryKey },
          { key: "secondaryKey", label: "Secondary key", value: (r) => r.properties?.secondaryKey },
          { key: "scope", label: "Scope", value: (r) => (r.properties?.scope || "").includes("/products/") ? (r.properties.scope.split("/products/")[1]) : "All APIs" },
          { key: "owner", label: "Owner", value: () => "--" },
          { key: "state", label: "State", value: (r) => r.properties?.state || "active" },
          { key: "allowTracing", label: "Allow tracing", value: (r) => (r.properties?.allowTracing ? "Yes" : "No") },
        ]}
      />
      <AddSubscriptionDialog open={add} onClose={() => setAdd(false)} existing={subs.data || []} products={products.data || []}
        onCreate={async (id, body) => { await api.Subscriptions.put(rg, svc, id, body); subs.reload(); }} />
    </>
  );
}

function AddSubscriptionDialog({ open, onClose, onCreate, existing, products }) {
  const notify = useNotify();
  const [f, setF] = useState({ name: "", displayName: "", scope: "", allowTracing: false });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.name) && f.displayName.trim() && !existing.some((s) => s.name.toLowerCase() === f.name.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.name, { properties: {
        displayName: f.displayName,
        scope: f.scope ? `/products/${f.scope}` : "/apis",
        state: "active",
        allowTracing: f.allowTracing,
        primaryKey: api.simKey(), secondaryKey: api.simKey(),
      } });
      notify.success(`Subscription '${f.displayName}' was created.`, "Create succeeded");
      setF({ name: "", displayName: "", scope: "", allowTracing: false });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add subscription">
        <DialogBody>
          <DialogTitle>Add subscription</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.displayName} onChange={(_, d) => setF((x) => ({ ...x, displayName: d.value, name: x.name || d.value.toLowerCase().replace(/[^a-z0-9-]+/g, "-") }))} aria-label="Name" /></Field>
              <Field label="Id" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Id" /></Field>
              <Field label="Scope">
                <Select value={f.scope} onChange={(_, d) => setF((x) => ({ ...x, scope: d.value }))} aria-label="Scope">
                  <option value="">All APIs</option>
                  {products.map((p) => <option key={p.name} value={p.name}>{p.properties?.displayName || p.name}</option>)}
                </Select>
              </Field>
              <Field><Checkbox label="Allow tracing" checked={f.allowTracing} onChange={(_, d) => setF((x) => ({ ...x, allowTracing: !!d.checked }))} /></Field>
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
