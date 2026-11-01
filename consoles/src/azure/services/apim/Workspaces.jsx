/* Workspaces panel: real ARM sub-resource of the service (service/workspaces). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Textarea, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;

export default function Workspaces({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.Workspaces.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.workspaces" title={`${svc} | Workspaces`}>
      <BrowseGrid
        resourceName="workspace" rowKey={(r) => r.name} filterPlaceholder="Search workspaces"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.Workspaces.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} workspace${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="workspaces.csv"
        columns={[
          { key: "name", label: "Name", value: (r) => r.properties?.displayName || r.name },
          { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
        ]}
      />
      <AddWorkspaceDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.Workspaces.put(rg, svc, id, body); reload(); }} />
    </CapabilityContainer>
  );
}

function AddWorkspaceDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", displayName: "", description: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.id) && f.displayName.trim() && !existing.some((w) => w.name.toLowerCase() === f.id.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.id, { properties: { displayName: f.displayName, description: f.description || undefined } });
      notify.success(`Workspace '${f.displayName}' was created.`, "Create succeeded");
      setF({ id: "", displayName: "", description: "" });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add workspace">
        <DialogBody>
          <DialogTitle>Add workspace</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Id" required><Input value={f.id} onChange={(_, d) => setF((x) => ({ ...x, id: d.value }))} aria-label="Id" /></Field>
              <Field label="Display name" required><Input value={f.displayName} onChange={(_, d) => setF((x) => ({ ...x, displayName: d.value }))} aria-label="Display name" /></Field>
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
