/* Policy fragments panel: real ARM sub-resource of the service
 * (Microsoft.ApiManagement/service/policyFragments). The XML round-trips through ARM exactly
 * as configured, but Vyomi's gateway never executes it (see capabilities.json
 * azure.apim.policyfragments.crud). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Textarea, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;
const DEFAULT_VALUE = "<fragment>\n</fragment>";

export default function PolicyFragments({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.PolicyFragments.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.policyfragments.crud" title={`${svc} | Policy fragments`}>
      <BrowseGrid
        resourceName="policy fragment" rowKey={(r) => r.name} filterPlaceholder="Search policy fragments"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.PolicyFragments.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} policy fragment${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="policy-fragments.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
        ]}
      />
      <AddFragmentDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.PolicyFragments.put(rg, svc, id, body); reload(); }} />
    </CapabilityContainer>
  );
}

function AddFragmentDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ name: "", description: "", value: DEFAULT_VALUE });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.name) && f.value.trim() && !existing.some((p) => p.name.toLowerCase() === f.name.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.name, { properties: { format: "xml", value: f.value, description: f.description || undefined } });
      notify.success(`Policy fragment '${f.name}' was created.`, "Create succeeded");
      setF({ name: "", description: "", value: DEFAULT_VALUE });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create policy fragment">
        <DialogBody>
          <DialogTitle>Create policy fragment</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Name" /></Field>
              <Field label="Description"><Input value={f.description} onChange={(_, d) => setF((x) => ({ ...x, description: d.value }))} aria-label="Description" /></Field>
              <Field label="Policy XML" required>
                <Textarea value={f.value} onChange={(_, d) => setF((x) => ({ ...x, value: d.value }))} rows={8} style={{ fontFamily: "monospace" }} aria-label="Policy XML" />
              </Field>
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
