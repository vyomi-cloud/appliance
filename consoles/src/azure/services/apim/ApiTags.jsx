/* API Tags panel: real ARM sub-resource of the service (Microsoft.ApiManagement/service/tags).
 * Manages the service-wide tag catalog; associating a tag with a specific API is not modeled
 * (see core/capabilities/azure/apim.json azure.apim.apitags.crud). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;

export default function ApiTags({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.ApiTags.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.apitags.crud" title={`${svc} | API Tags`}>
      <BrowseGrid
        resourceName="tag" rowKey={(r) => r.name} filterPlaceholder="Search tags"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.ApiTags.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} tag${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="api-tags.csv"
        columns={[
          { key: "name", label: "Name", value: (r) => r.properties?.displayName || r.name },
        ]}
      />
      <AddTagDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id) => { await api.ApiTags.put(rg, svc, id, { properties: { displayName: id } }); reload(); }} />
    </CapabilityContainer>
  );
}

function AddTagDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(name) && !existing.some((t) => t.name.toLowerCase() === name.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(name);
      notify.success(`Tag '${name}' was created.`, "Create succeeded");
      setName(""); onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add tag">
        <DialogBody>
          <DialogTitle>Add tag</DialogTitle>
          <DialogContent>
            <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Name" /></Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Save</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
