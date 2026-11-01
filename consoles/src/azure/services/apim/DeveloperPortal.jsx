/* Developer portal: Users, Groups and Identity providers are real ARM sub-resources of the
 * service (service/users, service/groups, service/identityProviders); Portal settings edits
 * the real portalsettings/signin + portalsettings/signup singletons; Delegation edits the real
 * portalsettings/delegation singleton. The portal CMS/theme/live-preview itself is not modeled
 * (azure.apim.developerportal) — Portal overview is a dashboard over this same real data. */
import { useState, useEffect } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { KV, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-._]{0,255}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CAP = "azure.apim.developerportal";

export function PortalOverview({ rg, svc, self }) {
  const users = useAsync(() => api.PortalUsers.list(rg, svc), [rg, svc]);
  const groups = useAsync(() => api.PortalGroups.list(rg, svc), [rg, svc]);
  const identities = useAsync(() => api.IdentityProviders.list(rg, svc), [rg, svc]);
  if (users.loading || groups.loading || identities.loading) return <Loading />;
  return (
    <CapabilityContainer id={CAP} title={`${svc} | Developer portal`}>
      <p style={{ fontSize: 13 }}>Manage who can sign in to the developer portal and how they're organized.</p>
      <div className="vy-props" style={{ marginTop: 12 }}>
        <KV label="Users" value={<a href={`${self}/users`}>{(users.data || []).length}</a>} />
        <KV label="Groups" value={<a href={`${self}/groups`}>{(groups.data || []).length}</a>} />
        <KV label="Identity providers" value={<a href={`${self}/identities`}>{(identities.data || []).length}</a>} />
      </div>
    </CapabilityContainer>
  );
}

export function PortalSettings({ rg, svc }) {
  const notify = useNotify();
  const signin = useAsync(() => api.SignIn.get(rg, svc), [rg, svc]);
  const signup = useAsync(() => api.SignUp.get(rg, svc), [rg, svc]);
  const [requireSignin, setRequireSignin] = useState(false);
  const [allowSignup, setAllowSignup] = useState(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRequireSignin(!!signin.data?.properties?.enabled), [signin.data]);
  useEffect(() => setAllowSignup(signup.data?.properties?.enabled !== false), [signup.data]);
  if (signin.loading || signup.loading) return <Loading />;
  const save = async () => {
    setBusy(true);
    try {
      await api.SignIn.put(rg, svc, { properties: { enabled: requireSignin } });
      await api.SignUp.put(rg, svc, { properties: { enabled: allowSignup, termsOfService: { enabled: false, consentRequired: false } } });
      notify.success("Portal settings were saved.", "Saved");
      signin.reload(); signup.reload();
    } catch (e) { notify.error(e, "Saving portal settings failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id={CAP} title={`${svc} | Portal settings`}>
      <section className="vy-section">
        <h3>Authentication</h3>
        <Checkbox label="Require sign-in to view APIs and products" checked={requireSignin} onChange={(_, d) => setRequireSignin(!!d.checked)} />
      </section>
      <section className="vy-section">
        <h3>Self sign-up</h3>
        <Checkbox label="Allow anonymous users to sign up" checked={allowSignup} onChange={(_, d) => setAllowSignup(!!d.checked)} />
      </section>
      <div style={{ marginTop: 12 }}><Button appearance="primary" disabled={busy} onClick={save}>Save</Button></div>
    </CapabilityContainer>
  );
}

export function Delegation({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, reload } = useAsync(() => api.Delegation.get(rg, svc), [rg, svc]);
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [delegateRegistration, setDelegateRegistration] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const p = data?.properties;
    setUrl(p?.url || ""); setKey(p?.validationKey || ""); setDelegateRegistration(!!p?.subscriptions?.enabled);
  }, [data]);
  if (loading) return <Loading />;
  const save = async () => {
    setBusy(true);
    try {
      await api.Delegation.put(rg, svc, { properties: { url: url || undefined, validationKey: key || undefined, subscriptions: { enabled: delegateRegistration } } });
      notify.success("Delegation settings were saved.", "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving delegation failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id={CAP} title={`${svc} | Delegation`}>
      <p style={{ fontSize: 13 }}>Delegate user registration and product subscription to your own site.</p>
      <Field label="Delegation endpoint URL" style={{ maxWidth: 480 }}><Input value={url} onChange={(_, d) => setUrl(d.value)} placeholder="https://..." aria-label="Delegation endpoint URL" /></Field>
      <Field label="Delegation validation key" style={{ maxWidth: 480, marginTop: 8 }}><Input value={key} onChange={(_, d) => setKey(d.value)} aria-label="Delegation validation key" /></Field>
      <div style={{ marginTop: 8 }}><Checkbox label="Delegate product subscriptions" checked={delegateRegistration} onChange={(_, d) => setDelegateRegistration(!!d.checked)} /></div>
      <div style={{ marginTop: 12 }}><Button appearance="primary" disabled={busy} onClick={save}>Save</Button></div>
    </CapabilityContainer>
  );
}

function directoryGrid({ title, resourceName, list, remove, columns, AddDialog }) {
  return function Panel({ rg, svc }) {
    const notify = useNotify();
    const { data, loading, error, reload } = useAsync(() => list(rg, svc), [rg, svc]);
    const [add, setAdd] = useState(false);
    return (
      <CapabilityContainer id={CAP} title={`${svc} | ${title}`}>
        <BrowseGrid
          resourceName={resourceName} rowKey={(r) => r.name} filterPlaceholder={`Search ${resourceName}s`}
          items={data || []} loading={loading} error={error} onRefresh={reload}
          extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>}
          onDelete={async (sel) => {
            for (const r of sel) await remove(rg, svc, r.name);
            notify.success(`Deleted ${sel.length} ${resourceName}${sel.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          csvName={`${resourceName}s.csv`}
          columns={columns}
        />
        <AddDialog open={add} onClose={() => setAdd(false)} existing={data || []} rg={rg} svc={svc} onCreated={reload} />
      </CapabilityContainer>
    );
  };
}

function AddUserDialog({ open, onClose, existing, rg, svc, onCreated }) {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", email: "", firstName: "", lastName: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.id) && EMAIL_RE.test(f.email) && f.firstName.trim() && f.lastName.trim()
    && !existing.some((u) => u.name.toLowerCase() === f.id.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await api.PortalUsers.put(rg, svc, f.id, { properties: { email: f.email, firstName: f.firstName, lastName: f.lastName, state: "active" } });
      notify.success(`User '${f.email}' was added.`, "Create succeeded");
      setF({ id: "", email: "", firstName: "", lastName: "" });
      onClose(); onCreated();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add user">
        <DialogBody>
          <DialogTitle>Add user</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Id" required><Input value={f.id} onChange={(_, d) => setF((x) => ({ ...x, id: d.value }))} aria-label="Id" /></Field>
              <Field label="Email" required><Input value={f.email} onChange={(_, d) => setF((x) => ({ ...x, email: d.value }))} aria-label="Email" /></Field>
              <Field label="First name" required><Input value={f.firstName} onChange={(_, d) => setF((x) => ({ ...x, firstName: d.value }))} aria-label="First name" /></Field>
              <Field label="Last name" required><Input value={f.lastName} onChange={(_, d) => setF((x) => ({ ...x, lastName: d.value }))} aria-label="Last name" /></Field>
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

export const Users = directoryGrid({
  title: "Users", resourceName: "user", list: api.PortalUsers.list, remove: api.PortalUsers.remove,
  AddDialog: AddUserDialog,
  columns: [
    { key: "email", label: "Email", value: (r) => r.properties?.email },
    { key: "name", label: "First name", value: (r) => r.properties?.firstName },
    { key: "lastName", label: "Last name", value: (r) => r.properties?.lastName },
    { key: "state", label: "State", value: (r) => r.properties?.state || "active" },
  ],
});

function AddGroupDialog({ open, onClose, existing, rg, svc, onCreated }) {
  const notify = useNotify();
  const [f, setF] = useState({ id: "", displayName: "", description: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.id) && f.displayName.trim() && !existing.some((g) => g.name.toLowerCase() === f.id.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await api.PortalGroups.put(rg, svc, f.id, { properties: { displayName: f.displayName, description: f.description || undefined, type: "custom" } });
      notify.success(`Group '${f.displayName}' was created.`, "Create succeeded");
      setF({ id: "", displayName: "", description: "" });
      onClose(); onCreated();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add group">
        <DialogBody>
          <DialogTitle>Add group</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Id" required><Input value={f.id} onChange={(_, d) => setF((x) => ({ ...x, id: d.value }))} aria-label="Id" /></Field>
              <Field label="Name" required><Input value={f.displayName} onChange={(_, d) => setF((x) => ({ ...x, displayName: d.value }))} aria-label="Name" /></Field>
              <Field label="Description"><Input value={f.description} onChange={(_, d) => setF((x) => ({ ...x, description: d.value }))} aria-label="Description" /></Field>
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

export const Groups = directoryGrid({
  title: "Groups", resourceName: "group", list: api.PortalGroups.list, remove: api.PortalGroups.remove,
  AddDialog: AddGroupDialog,
  columns: [
    { key: "name", label: "Name", value: (r) => r.properties?.displayName || r.name },
    { key: "description", label: "Description", value: (r) => r.properties?.description || "--" },
    { key: "type", label: "Type", value: (r) => r.properties?.type || "custom" },
  ],
});

const IDP_TYPES = ["aad", "aadB2C", "google", "facebook", "microsoft", "twitter"];

function AddIdentityDialog({ open, onClose, existing, rg, svc, onCreated }) {
  const notify = useNotify();
  const [f, setF] = useState({ type: "aad", clientId: "", clientSecret: "" });
  const [busy, setBusy] = useState(false);
  const valid = IDP_TYPES.includes(f.type) && f.clientId.trim() && f.clientSecret.trim() && !existing.some((i) => i.name.toLowerCase() === f.type.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await api.IdentityProviders.put(rg, svc, f.type, { properties: { clientId: f.clientId, clientSecret: f.clientSecret } });
      notify.success(`Identity provider '${f.type}' was added.`, "Create succeeded");
      setF({ type: "aad", clientId: "", clientSecret: "" });
      onClose(); onCreated();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add identity provider">
        <DialogBody>
          <DialogTitle>Add identity provider</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Type" required>
                <Select value={f.type} onChange={(_, d) => setF((x) => ({ ...x, type: d.value }))} aria-label="Type">
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

export const Identities = directoryGrid({
  title: "Identities", resourceName: "identity provider", list: api.IdentityProviders.list, remove: api.IdentityProviders.remove,
  AddDialog: AddIdentityDialog,
  columns: [
    { key: "name", label: "Type", value: (r) => r.name },
    { key: "clientId", label: "Client ID", value: (r) => r.properties?.clientId },
  ],
});
