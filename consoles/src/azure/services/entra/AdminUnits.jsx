/* Default Directory | Administrative units — real Microsoft Graph administrative units. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";

const COLUMNS = [
  { key: "displayName", label: "Name" },
  { key: "description", label: "Description", value: (r) => r.description || "--" },
  { key: "restricted", label: "Restricted management", value: (r) => (r.isMemberManagementRestricted ? "Yes" : "No") },
  { key: "membershipType", label: "Membership type" },
];

export default function AdminUnits() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listAdministrativeUnits(), []);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");

  const create = async () => {
    await api.createAdministrativeUnit({ displayName: name, description: desc || undefined });
    notify.success(`Created administrative unit ${name}.`, "Add administrative unit");
    setAdding(false); setName(""); setDesc("");
    reload();
  };

  return (
    <EntraShell active="adminunits" title="Default Directory | Administrative units">
      <div className="vy-page">
        <BrowseGrid
          resourceName="administrative unit"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onDelete={async (sel) => {
            for (const r of sel) await api.deleteAdministrativeUnit(r.id);
            notify.success(`Deleted ${sel.length} administrative unit${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          csvName="administrative-units.csv"
          columns={COLUMNS}
          extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdding(true)}>Add</ToolbarButton>}
        />
        <NotSimulatedContainer title="More commands" feature="Preview features, Got feedback?" note="Preview features. Got feedback? are not simulated in Vyomi." />
      </div>
      <Dialog open={adding} onOpenChange={(_, d) => setAdding(d.open)}>
        <DialogSurface aria-label="Add administrative unit">
          <DialogBody>
            <DialogTitle>Add</DialogTitle>
            <DialogContent>
              <Field label="Name" required><Input value={name} onChange={(_, d) => setName(d.value)} /></Field>
              <Field label="Description"><Input value={desc} onChange={(_, d) => setDesc(d.value)} /></Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!name.trim()} onClick={create}>Add</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </EntraShell>
  );
}
