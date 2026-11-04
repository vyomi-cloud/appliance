/* Credential manager panel: real ARM sub-resource of the service (service/authorizationProviders).
 * The nested per-provider Authorizations (the actual OAuth2 token exchange) are not modeled —
 * see azure.apim.credentialmanager. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;
const IDP_TYPES = ["aad", "google", "github", "generic"];

export default function CredentialManager({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.AuthorizationProviders.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.apim.credentialmanager" title={`${svc} | Credential manager`}>
      <BrowseGrid
        resourceName="authorization provider" rowKey={(r) => r.name} filterPlaceholder="Search authorization providers"
        items={data || []} loading={loading} error={error} onRefresh={reload}
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create</ToolbarButton>}
        onDelete={async (sel) => {
          for (const r of sel) await api.AuthorizationProviders.remove(rg, svc, r.name);
          notify.success(`Deleted ${sel.length} provider${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
          reload();
        }}
        csvName="authorization-providers.csv"
        columns={[
          { key: "name", label: "Name" },
          { key: "type", label: "Identity provider", value: (r) => r.properties?.identityProvider || "--" },
          { key: "grant", label: "Grant type", value: (r) => r.properties?.oauth2?.grantType || "AuthorizationCode" },
        ]}
      />
      <AddProviderDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.AuthorizationProviders.put(rg, svc, id, body); reload(); }} />
    </CapabilityContainer>
  );
}

function AddProviderDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", identityProvider: "aad", clientId: "", clientSecret: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.id) && f.clientId.trim() && f.clientSecret.trim() && !existing.some((p) => p.name.toLowerCase() === f.id.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.id, { properties: {
        identityProvider: f.identityProvider,
        oauth2: { grantType: "AuthorizationCode", clientId: f.clientId, clientSecret: f.clientSecret },
      } });
      notify.success(`Authorization provider '${f.id}' was created.`, "Create succeeded");
      setF({ id: "", identityProvider: "aad", clientId: "", clientSecret: "" });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create authorization provider">
        <DialogBody>
          <DialogTitle>Create authorization provider</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Name" required><Input value={f.id} onChange={(_, d) => setF((x) => ({ ...x, id: d.value }))} aria-label="Name" /></Field>
              <Field label="Identity provider" required>
                <Select value={f.identityProvider} onChange={(_, d) => setF((x) => ({ ...x, identityProvider: d.value }))} aria-label="Identity provider">
                  {IDP_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </Select>
              </Field>
              <Field label="Client ID" required><Input value={f.clientId} onChange={(_, d) => setF((x) => ({ ...x, clientId: d.value }))} aria-label="Client ID" /></Field>
              <Field label="Client secret" required><Input type="password" value={f.clientSecret} onChange={(_, d) => setF((x) => ({ ...x, clientSecret: d.value }))} aria-label="Client secret" /></Field>
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
