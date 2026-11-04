/* Default Directory | Custom domain names — real Microsoft Graph domains. Verification
 * (DNS TXT/MX lookup) is not simulated: added domains honestly stay unverified. */
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
  { key: "id", label: "Name" },
  { key: "status", label: "Status", value: (r) => (r.isVerified ? "Verified" : "Unverified") },
  { key: "federated", label: "Federated", value: (r) => (r.authenticationType === "Federated" ? "Yes" : "No") },
  { key: "primary", label: "Primary", value: (r) => (r.isDefault ? "Yes" : "No") },
];

export default function CustomDomains() {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.listDomains(), []);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");

  const create = async () => {
    await api.addDomain(name);
    notify.success(`Added custom domain ${name}.`, "Add custom domain");
    setAdding(false); setName("");
    reload();
  };

  return (
    <EntraShell active="customdomains" title="Default Directory | Custom domain names">
      <div className="vy-page">
        <BrowseGrid
          resourceName="domain"
          rowKey={(r) => r.id}
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onDelete={async (sel) => {
            for (const r of sel.filter((d) => !d.isInitial)) await api.deleteDomain(r.id);
            notify.success(`Deleted ${sel.length} domain${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          csvName="custom-domains.csv"
          columns={COLUMNS}
          extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdding(true)}>Add custom domain</ToolbarButton>}
        />
        <NotSimulatedContainer title="More commands" feature="Diagnose and solve problems, Columns, Got feedback?"
          note="Diagnose and solve problems. Columns. Got feedback? are not simulated in Vyomi." />
      </div>
      <Dialog open={adding} onOpenChange={(_, d) => setAdding(d.open)}>
        <DialogSurface aria-label="Add custom domain">
          <DialogBody>
            <DialogTitle>Add custom domain</DialogTitle>
            <DialogContent>
              <Field label="Custom domain name" required><Input value={name} onChange={(_, d) => setName(d.value)} placeholder="contoso.com" /></Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!name.trim()} onClick={create}>Add domain</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </EntraShell>
  );
}
