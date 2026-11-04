/* Self-hosted gateways panel: real ARM sub-resource of the service (service/gateways) — a
 * self-hosted gateway registers itself against one of these records. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Textarea, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;

export default function SelfHostedGateways({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.Gateways.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.deployment" title={`${svc} | Self-hosted gateways`}>
      <BrowseGrid
        resourceName="self-hosted gateway" rowKey={(r) => r.name} filterPlaceholder="Search self-hosted gateways"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.Gateways.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} gateway${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="self-hosted-gateways.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
          { key: "region", label: "Region", value: (r) => r.properties?.locationData?.name || "--" },
        ]}
      />
      <AddGatewayDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.Gateways.put(rg, svc, id, body); reload(); }} />
    </CapabilityContainer>
  );
}

function AddGatewayDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", region: "", description: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.id) && f.region.trim() && !existing.some((g) => g.name.toLowerCase() === f.id.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.id, { properties: { description: f.description || undefined, locationData: { name: f.region } } });
      notify.success(`Self-hosted gateway '${f.id}' was added.`, "Create succeeded");
      setF({ id: "", region: "", description: "" });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add self-hosted gateway">
        <DialogBody>
          <DialogTitle>Add self-hosted gateway</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.id} onChange={(_, d) => setF((x) => ({ ...x, id: d.value }))} aria-label="Name" /></Field>
              <Field label="Region" required><Input value={f.region} onChange={(_, d) => setF((x) => ({ ...x, region: d.value }))} aria-label="Region" /></Field>
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
