/* Products panel: real ARM sub-resource of the service (Microsoft.ApiManagement/service/
 * {name}/products/{productId}). */
import { useState } from "react";
import {
  Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input,
  Textarea, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-]{0,255}$/;

export default function Products({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.Products.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <>
      <div className="vy-panel-title">{svc} | Products</div>
      <BrowseGrid
        resourceName="product" rowKey={(r) => r.name} filterPlaceholder="Search products"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.Products.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} product${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="products.csv"
        columns={[
          { key: "name", label: "Name", value: (r) => r.properties?.displayName || r.name },
          { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
          { key: "visibility", label: "Visibility", value: () => "--" },
          { key: "state", label: "State", value: (r) => (r.properties?.state === "published" ? "Published" : "Not published") },
        ]}
      />
      <AddProductDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.Products.put(rg, svc, id, body); reload(); }} />
    </>
  );
}

function AddProductDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", displayName: "", description: "", published: false, subscriptionRequired: true, approvalRequired: false });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.id) && f.displayName.trim() && !existing.some((p) => p.name.toLowerCase() === f.id.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.id, { properties: {
        displayName: f.displayName, description: f.description || undefined,
        state: f.published ? "published" : "notPublished",
        subscriptionRequired: f.subscriptionRequired, approvalRequired: f.subscriptionRequired && f.approvalRequired,
      } });
      notify.success(`Product '${f.displayName}' was created.`, "Create succeeded");
      setF({ id: "", displayName: "", description: "", published: false, subscriptionRequired: true, approvalRequired: false });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add product">
        <DialogBody>
          <DialogTitle>Add product</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Display name" required><Input value={f.displayName} onChange={(_, d) => setF((x) => ({ ...x, displayName: d.value, id: x.id || d.value.toLowerCase().replace(/[^a-z0-9-]+/g, "-") }))} aria-label="Display name" /></Field>
              <Field label="Id" required><Input value={f.id} onChange={(_, d) => setF((x) => ({ ...x, id: d.value }))} aria-label="Id" /></Field>
              <Field label="Description"><Textarea value={f.description} onChange={(_, d) => setF((x) => ({ ...x, description: d.value }))} aria-label="Description" /></Field>
              <Field><Checkbox label="Published" checked={f.published} onChange={(_, d) => setF((x) => ({ ...x, published: !!d.checked }))} /></Field>
              <Field><Checkbox label="Requires subscription" checked={f.subscriptionRequired} onChange={(_, d) => setF((x) => ({ ...x, subscriptionRequired: !!d.checked }))} /></Field>
              {f.subscriptionRequired && <Field><Checkbox label="Requires approval" checked={f.approvalRequired} onChange={(_, d) => setF((x) => ({ ...x, approvalRequired: !!d.checked }))} /></Field>}
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
