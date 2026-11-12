/* Real panels for the Entra user and app-registration blades. Everything here round-trips through the Microsoft Graph core
 * (core/azure_graph_core.py: PATCH stores the properties as written, audit/sign-in logs are appended by real operations) or
 * through ARM role assignments -- no canned rows. */
import { useState } from "react";
import { Button, Checkbox, Field, Input, Textarea } from "@fluentui/react-components";
import { Add20Regular, Delete16Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import * as api from "./api.js";

const uuid = api.uid;
const Title = ({ children }) => <div className="vy-panel-title">{children}</div>;

// ── User blade ────────────────────────────────────────────────────────────────
export function UserAuditLogs({ user }) {
  const { data, loading, error, reload } = useAsync(() => api.listAuditLogs(), [user.id]);
  const mine = (data || []).filter((r) => (r.targetResources || []).some((t) => t.id === user.id || t.displayName === user.displayName || t.userPrincipalName === user.userPrincipalName));
  return (
    <>
      <Title>{`${user.displayName} | Audit logs`}</Title>
      <BrowseGrid resourceName="audit log entry" rowKey={(r) => r.id} items={mine} loading={loading} error={error} onRefresh={reload}
        columns={[
          { key: "date", label: "Date", value: (r) => r.activityDateTime }, { key: "service", label: "Service", value: (r) => r.loggedByService },
          { key: "category", label: "Category" }, { key: "activity", label: "Activity", value: (r) => r.activityDisplayName }, { key: "status", label: "Status", value: (r) => r.result },
        ]} />
    </>
  );
}

export function UserSignInLogs({ user }) {
  const { data, loading, error, reload } = useAsync(() => api.listSignInLogs(), [user.id]);
  const mine = (data || []).filter((r) => r.userId === user.id || r.userPrincipalName === user.userPrincipalName);
  return (
    <>
      <Title>{`${user.displayName} | Sign-in logs`}</Title>
      <p className="vy-muted" style={{ fontSize: 12 }}>Sign-ins are recorded from real token requests against the simulator's own token endpoint (password and client-credential grants); there is no interactive browser sign-in flow.</p>
      <BrowseGrid resourceName="sign-in" rowKey={(r) => r.id} items={mine} loading={loading} error={error} onRefresh={reload}
        columns={[
          { key: "date", label: "Date", value: (r) => r.createdDateTime }, { key: "app", label: "Application", value: (r) => r.appDisplayName },
          { key: "status", label: "Status", value: (r) => (r.status?.errorCode ? "Failure" : "Success") }, { key: "ip", label: "IP address", value: (r) => r.ipAddress || "--" },
        ]} />
    </>
  );
}

export function UserAzureRoles({ user }) {
  const { data, loading, error } = useAsync(async () => {
    const [as, defs] = await Promise.all([api.listRoleAssignments(), api.listRoleDefinitions()]);
    const name = Object.fromEntries((defs || []).map((d) => [d.id, d.properties?.roleName || d.name]));
    return (as || []).filter((a) => a.properties?.principalId === user.id).map((a) => ({ id: a.name, role: name[a.properties.roleDefinitionId] || a.properties.roleDefinitionId, scope: a.properties.scope }));
  }, [user.id]);
  return (
    <>
      <Title>{`${user.displayName} | Azure role assignments`}</Title>
      <ErrorBar error={error} title="Failed to list role assignments" />
      {loading && !data ? <Loading /> : (
        <table className="vy-grid" aria-label="Azure role assignments">
          <thead><tr><th>Role</th><th>Scope</th></tr></thead>
          <tbody>{(data || []).length ? data.map((r) => <tr key={r.id}><td>{r.role}</td><td>{r.scope}</td></tr>) : <tr><td colSpan={2} className="vy-muted">{user.displayName} has no Azure role assignments.</td></tr>}</tbody>
        </table>
      )}
    </>
  );
}

export function UserAuthMethods({ user, reload }) {
  const notify = useNotify();
  const [pwd, setPwd] = useState("");
  const [force, setForce] = useState(true);
  const reset = async () => {
    try { await api.updateUser(user.id, { passwordProfile: { password: pwd, forceChangePasswordNextSignIn: force } }); notify.success("Password reset.", "Reset succeeded"); setPwd(""); reload(); }
    catch (e) { notify.error(e, "Reset password failed"); }
  };
  return (
    <>
      <Title>{`${user.displayName} | Authentication methods`}</Title>
      <table className="vy-grid" aria-label="Authentication methods">
        <thead><tr><th>Method</th><th>Detail</th></tr></thead>
        <tbody><tr><td>Password</td><td>{user.passwordProfile?.forceChangePasswordNextSignIn ? "Must be changed at next sign-in" : "Set"}{user.lastPasswordChangeDateTime ? `; last changed ${api.fmtDateTime(user.lastPasswordChangeDateTime)}` : ""}</td></tr></tbody>
      </table>
      <p className="vy-muted" style={{ fontSize: 12 }}>Password is the only method the simulator's token endpoint accepts; MFA, FIDO2 and Microsoft Authenticator registration are not modelled.</p>
      <section className="vy-section"><h3>Reset password</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 360 }}>
          <Field label="New password"><Input type="password" aria-label="New password" value={pwd} onChange={(_, d) => setPwd(d.value)} /></Field>
          <Checkbox checked={force} onChange={(_, d) => setForce(!!d.checked)} label="Require this user to change their password when they first sign in" />
          <div><Button appearance="primary" disabled={!pwd} onClick={reset}>Reset password</Button></div>
        </div>
      </section>
    </>
  );
}

// ── App registration blade ────────────────────────────────────────────────────
function useSave(app, reload, label) {
  const notify = useNotify();
  return async (patch, ok) => {
    try { await api.updateApplication(app.id, patch); notify.success(ok || `${label} saved.`, "Saved"); reload(); } catch (e) { notify.error(e, `Saving ${label} failed`); }
  };
}

export function ExposeApi({ app, reload }) {
  const save = useSave(app, reload, "API settings");
  const scopes = app.api?.oauth2PermissionScopes || [];
  const [uri, setUri] = useState((app.identifierUris || [])[0] || "");
  const [f, setF] = useState({ value: "", display: "", desc: "" });
  const setScopes = (next, ok) => save({ api: { ...(app.api || {}), oauth2PermissionScopes: next } }, ok);
  const add = () => {
    if (!f.value) return;
    setScopes([...scopes, { id: uuid(), value: f.value, type: "User", isEnabled: true, adminConsentDisplayName: f.display || f.value, adminConsentDescription: f.desc || f.display || f.value, userConsentDisplayName: f.display || f.value, userConsentDescription: f.desc || f.display || f.value }], `Scope ${f.value} added.`);
    setF({ value: "", display: "", desc: "" });
  };
  return (
    <>
      <Title>{`${app.displayName} | Expose an API`}</Title>
      <section className="vy-section"><h3>Application ID URI</h3>
        <div style={{ display: "flex", gap: 8, maxWidth: 520 }}>
          <Input aria-label="Application ID URI" style={{ flex: 1 }} value={uri} onChange={(_, d) => setUri(d.value)} placeholder={`api://${app.appId}`} />
          <Button onClick={() => save({ identifierUris: uri ? [uri] : [] }, "Application ID URI saved.")}>Save</Button>
          <Button onClick={() => setUri(`api://${app.appId}`)}>Use default</Button>
        </div>
      </section>
      <section className="vy-section"><h3>Scopes defined by this API</h3>
        <table className="vy-grid" aria-label="Scopes">
          <thead><tr><th>Scope</th><th>Who can consent</th><th>State</th><th></th></tr></thead>
          <tbody>{scopes.length ? scopes.map((s) => (
            <tr key={s.id}><td>{(app.identifierUris || [])[0] ? `${app.identifierUris[0]}/` : ""}{s.value}<div className="vy-muted" style={{ fontSize: 11 }}>{s.adminConsentDisplayName}</div></td><td>{s.type === "Admin" ? "Admins only" : "Admins and users"}</td>
              <td><Checkbox checked={s.isEnabled} label={s.isEnabled ? "Enabled" : "Disabled"} onChange={(_, d) => setScopes(scopes.map((x) => (x.id === s.id ? { ...x, isEnabled: !!d.checked } : x)), "Scope updated.")} /></td>
              <td><Button size="small" icon={<Delete16Regular />} aria-label={`Delete scope ${s.value}`} onClick={() => setScopes(scopes.filter((x) => x.id !== s.id), "Scope deleted.")} /></td></tr>
          )) : <tr><td colSpan={4} className="vy-muted">No scopes defined.</td></tr>}</tbody>
        </table>
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <Input aria-label="Scope name" placeholder="Scope name (e.g. access_as_user)" value={f.value} onChange={(_, d) => setF({ ...f, value: d.value })} />
          <Input aria-label="Consent display name" placeholder="Admin consent display name" value={f.display} onChange={(_, d) => setF({ ...f, display: d.value })} />
          <Input aria-label="Consent description" placeholder="Admin consent description" value={f.desc} onChange={(_, d) => setF({ ...f, desc: d.value })} />
          <Button appearance="primary" icon={<Add20Regular />} disabled={!f.value} onClick={add}>Add a scope</Button>
        </div>
      </section>
    </>
  );
}

export function AppRoles({ app, reload }) {
  const save = useSave(app, reload, "App roles");
  const roles = app.appRoles || [];
  const [f, setF] = useState({ displayName: "", value: "", description: "", users: true, apps: false });
  const add = () => {
    const allowed = [f.users && "User", f.apps && "Application"].filter(Boolean);
    if (!f.displayName || !f.value || !allowed.length) return;
    save({ appRoles: [...roles, { id: uuid(), displayName: f.displayName, value: f.value, description: f.description || f.displayName, allowedMemberTypes: allowed, isEnabled: true }] }, `App role ${f.displayName} created.`);
    setF({ displayName: "", value: "", description: "", users: true, apps: false });
  };
  return (
    <>
      <Title>{`${app.displayName} | App roles`}</Title>
      <table className="vy-grid" aria-label="App roles">
        <thead><tr><th>Display name</th><th>Allowed member types</th><th>Value</th><th>State</th><th></th></tr></thead>
        <tbody>{roles.length ? roles.map((r) => (
          <tr key={r.id}><td>{r.displayName}<div className="vy-muted" style={{ fontSize: 11 }}>{r.description}</div></td><td>{(r.allowedMemberTypes || []).join(", ")}</td><td>{r.value}</td>
            <td><Checkbox checked={r.isEnabled} label={r.isEnabled ? "Enabled" : "Disabled"} onChange={(_, d) => save({ appRoles: roles.map((x) => (x.id === r.id ? { ...x, isEnabled: !!d.checked } : x)) }, "App role updated.")} /></td>
            <td><Button size="small" icon={<Delete16Regular />} aria-label={`Delete app role ${r.displayName}`} onClick={() => save({ appRoles: roles.filter((x) => x.id !== r.id) }, "App role deleted.")} /></td></tr>
        )) : <tr><td colSpan={5} className="vy-muted">No app roles defined.</td></tr>}</tbody>
      </table>
      <section className="vy-section"><h3>Create app role</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label="Display name"><Input aria-label="Role display name" value={f.displayName} onChange={(_, d) => setF({ ...f, displayName: d.value })} /></Field>
          <Field label="Value"><Input aria-label="Role value" value={f.value} onChange={(_, d) => setF({ ...f, value: d.value })} /></Field>
          <Field label="Description"><Input aria-label="Role description" value={f.description} onChange={(_, d) => setF({ ...f, description: d.value })} /></Field>
          <Checkbox label="Users/Groups" checked={f.users} onChange={(_, d) => setF({ ...f, users: !!d.checked })} />
          <Checkbox label="Applications" checked={f.apps} onChange={(_, d) => setF({ ...f, apps: !!d.checked })} />
          <Button appearance="primary" icon={<Add20Regular />} onClick={add}>Create</Button>
        </div>
      </section>
    </>
  );
}

const CLAIMS = { idToken: ["email", "family_name", "given_name", "upn", "preferred_username", "ipaddr"], accessToken: ["email", "upn", "ipaddr", "idtyp"], saml2Token: ["email", "upn", "family_name", "given_name"] };
const TOKEN_LABEL = { idToken: "ID", accessToken: "Access", saml2Token: "SAML" };
export function TokenConfiguration({ app, reload }) {
  const save = useSave(app, reload, "Optional claims");
  const oc = app.optionalClaims || {};
  const toggle = (tok, claim, on) => {
    const cur = oc[tok] || [];
    const next = on ? [...cur, { name: claim, source: null, essential: false, additionalProperties: [] }] : cur.filter((c) => c.name !== claim);
    save({ optionalClaims: { ...oc, [tok]: next } }, `Optional claim ${claim} ${on ? "added" : "removed"}.`);
  };
  return (
    <>
      <Title>{`${app.displayName} | Token configuration`}</Title>
      <p style={{ fontSize: 13 }}>Optional claims are stored on the application (optionalClaims) exactly as Graph returns them; the simulator's token endpoint issues opaque tokens, so the claims are configuration the SDK and CLI can read back, not claims in an issued JWT.</p>
      {Object.keys(CLAIMS).map((tok) => (
        <section className="vy-section" key={tok}><h3>{TOKEN_LABEL[tok]} token</h3>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {CLAIMS[tok].map((c) => <Checkbox key={c} label={c} checked={(oc[tok] || []).some((x) => x.name === c)} onChange={(_, d) => toggle(tok, c, !!d.checked)} />)}
          </div>
        </section>
      ))}
    </>
  );
}

export function Branding({ app, reload }) {
  const save = useSave(app, reload, "Branding");
  const [f, setF] = useState({ displayName: app.displayName || "", homePageUrl: app.web?.homePageUrl || "", logoUrl: app.info?.logoUrl || "", termsOfServiceUrl: app.info?.termsOfServiceUrl || "", privacyStatementUrl: app.info?.privacyStatementUrl || "", supportUrl: app.info?.supportUrl || "", marketingUrl: app.info?.marketingUrl || "", notes: app.notes || "" });
  const set = (k) => (_, d) => setF({ ...f, [k]: d.value });
  const row = (k, label) => <Field label={label}><Input aria-label={label} value={f[k]} onChange={set(k)} /></Field>;
  return (
    <>
      <Title>{`${app.displayName} | Branding & properties`}</Title>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 560 }}>
        {row("displayName", "Name")}{row("homePageUrl", "Home page URL")}{row("logoUrl", "Logo URL")}{row("termsOfServiceUrl", "Terms of service URL")}
        {row("privacyStatementUrl", "Privacy statement URL")}{row("supportUrl", "Support URL")}{row("marketingUrl", "Marketing URL")}
        <Field label="Internal notes"><Textarea aria-label="Internal notes" value={f.notes} onChange={set("notes")} /></Field>
        <Field label="Application (client) ID"><Input readOnly value={app.appId} aria-label="Application (client) ID" /></Field>
        <Field label="Publisher domain"><Input readOnly value={app.publisherDomain || api.DEFAULT_DOMAIN} aria-label="Publisher domain" /></Field>
        <div><Button appearance="primary" disabled={!f.displayName} onClick={() => save({ displayName: f.displayName, notes: f.notes, web: { ...(app.web || {}), homePageUrl: f.homePageUrl || null },
          info: { logoUrl: f.logoUrl || null, termsOfServiceUrl: f.termsOfServiceUrl || null, privacyStatementUrl: f.privacyStatementUrl || null, supportUrl: f.supportUrl || null, marketingUrl: f.marketingUrl || null } })}>Save</Button></div>
      </div>
    </>
  );
}

export function Quickstart({ app }) {
  const authority = `https://login.microsoftonline.com/${api.DEFAULT_TENANT_ID}`;
  const snippet = `# pip install msal\\nimport msal\\napp = msal.ConfidentialClientApplication(\\n    "${app.appId}",\\n    authority="${authority}",\\n    client_credential="<client secret>")\\nresult = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])`;
  return (
    <>
      <Title>{`${app.displayName} | Quickstart`}</Title>
      <p style={{ fontSize: 13 }}>Use these values from your own code; they are this registration's real identifiers, and the token endpoint below is served by the simulator.</p>
      <table className="vy-grid" aria-label="Identifiers"><tbody>
        <tr><th>Application (client) ID</th><td>{app.appId}</td></tr><tr><th>Directory (tenant) ID</th><td>{api.DEFAULT_TENANT_ID}</td></tr>
        <tr><th>Authority</th><td>{authority}</td></tr><tr><th>Token endpoint</th><td>{authority}/oauth2/v2.0/token</td></tr>
      </tbody></table>
      <section className="vy-section"><h3>Acquire a token (Python, MSAL)</h3><pre style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{snippet.replace(/\\n/g, "\n")}</pre></section>
    </>
  );
}

export function IntegrationAssistant({ app }) {
  const checks = [
    ["Redirect URI configured", (app.web?.redirectUris?.length || app.spa?.redirectUris?.length || app.publicClient?.redirectUris?.length) > 0, "Add a redirect URI under Authentication."],
    ["Client secret or certificate configured", (app.passwordCredentials?.length || app.keyCredentials?.length) > 0, "Add a credential under Certificates & secrets."],
    ["API permissions requested", (app.requiredResourceAccess?.length || 0) > 0, "Request at least the delegated permissions your app calls."],
    ["Client secrets not expired", !(app.passwordCredentials || []).some((c) => c.endDateTime && new Date(c.endDateTime) < new Date()), "Rotate the expired secret."],
    ["Application ID URI set (APIs)", (app.identifierUris?.length || 0) > 0, "Set one under Expose an API if this app publishes an API."],
    ["Publisher branding set", !!(app.info?.logoUrl || app.info?.termsOfServiceUrl || app.web?.homePageUrl), "Add branding under Branding & properties."],
  ];
  const ok = checks.filter((c) => c[1]).length;
  return (
    <>
      <Title>{`${app.displayName} | Integration assistant`}</Title>
      <p style={{ fontSize: 13 }} data-testid="integration-score"><b>{ok} of {checks.length}</b> recommended settings are in place. Each result is computed from this registration's current configuration.</p>
      <table className="vy-grid" aria-label="Recommendations">
        <thead><tr><th>Status</th><th>Check</th><th>Recommended action</th></tr></thead>
        <tbody>{checks.map(([name, pass, fix]) => <tr key={name} data-status={pass ? "ok" : "todo"}><td>{pass ? "✓ Done" : "! To do"}</td><td>{name}</td><td>{pass ? "—" : fix}</td></tr>)}</tbody>
      </table>
    </>
  );
}
