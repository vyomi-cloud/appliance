/* Backends panel: real ARM sub-resource of the service. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Textarea, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;

export default function Backends({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.Backends.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <>
      <div className="vy-panel-title">{svc} | Backends</div>
      <BrowseGrid
        resourceName="backend" rowKey={(r) => r.name} filterPlaceholder="Search backends"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create new backend</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.Backends.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} backend${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="backends.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "type", label: "Type", value: (r) => r.properties?.protocol === "soap" ? "SOAP passthrough" : "Custom URL" },
          { key: "url", label: "Runtime URL", value: (r) => r.properties?.url },
          { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
        ]}
      />
      <AddBackendDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.Backends.put(rg, svc, id, body); reload(); }} />
    </>
  );
}

function AddBackendDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ name: "", url: "", description: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.name) && f.url.trim() && !existing.some((b) => b.name.toLowerCase() === f.name.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.name, { properties: { protocol: "http", url: f.url, description: f.description || undefined } });
      notify.success(`Backend '${f.name}' was created.`, "Create succeeded");
      setF({ name: "", url: "", description: "" });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create new backend">
        <DialogBody>
          <DialogTitle>Create new backend</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Name" /></Field>
              <Field label="Runtime URL" required><Input value={f.url} onChange={(_, d) => setF((x) => ({ ...x, url: d.value }))} placeholder="https://..." aria-label="Runtime URL" /></Field>
              <Field label="Description"><Textarea value={f.description} onChange={(_, d) => setF((x) => ({ ...x, description: d.value }))} aria-label="Description" /></Field>
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
