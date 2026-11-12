/* Certificates panel: real ARM sub-resource of the service (service/certificates) — client
 * certificates used to authenticate to backends. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;

export default function Certificates({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.Certificates.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.deployment" title={`${svc} | Certificates`}>
      <BrowseGrid
        resourceName="certificate" rowKey={(r) => r.name} filterPlaceholder="Search certificates"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.Certificates.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} certificate${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="certificates.csv"
        columns={[
          { key: "name", label: "Id" },
          { key: "subject", label: "Subject", value: (r) => r.properties?.subject || "--" },
          { key: "thumbprint", label: "Thumbprint", value: (r) => r.properties?.thumbprint },
          { key: "expiration", label: "Expiration date", value: (r) => fmtDate(r.properties?.expirationDate) },
        ]}
      />
      <AddCertificateDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.Certificates.put(rg, svc, id, body); reload(); }} />
    </CapabilityContainer>
  );
}

function AddCertificateDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", subject: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.id) && f.subject.trim() && !existing.some((c) => c.name.toLowerCase() === f.id.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      const thumbprint = Array.from({ length: 20 }, () => Math.floor(Math.random() * 256).toString(16).padStart(2, "0").toUpperCase()).join("");
      await onCreate(f.id, { properties: {
        subject: f.subject, thumbprint, expirationDate: new Date(Date.now() + 365 * 86400e3).toISOString(),
      } });
      notify.success(`Certificate '${f.id}' was added.`, "Create succeeded");
      setF({ id: "", subject: "" });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add certificate">
        <DialogBody>
          <DialogTitle>Add certificate</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Id" required><Input value={f.id} onChange={(_, d) => setF((x) => ({ ...x, id: d.value }))} aria-label="Id" /></Field>
              <Field label="Subject" required><Input value={f.subject} onChange={(_, d) => setF((x) => ({ ...x, subject: d.value }))} placeholder="CN=example.com" aria-label="Subject" /></Field>
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
