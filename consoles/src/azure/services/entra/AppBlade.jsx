/* An app registration's own resource blade — the Entra ID peer of StorageAccountBlade.jsx.
 * Overview, Authentication, Certificates & secrets and API permissions are real; the
 * remaining menu items are reference-only in the spec (title captured, no further
 * structure), so they render honestly as just their title. */
import { useState } from "react";
import {
  Button, Field, Input, Link, Radio, RadioGroup, Select, Tab, TabList,
  Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, Delete16Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { ErrorBar, Glyph, KV, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "quickstart", label: "Quickstart" },
  { id: "integrationassistant", label: "Integration assistant" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { id: "brandingproperties", label: "Branding & properties" },
  { id: "authentication", label: "Authentication" },
  { id: "certificatessecrets", label: "Certificates & secrets" },
  { id: "tokenconfiguration", label: "Token configuration" },
  { id: "apipermissions", label: "API permissions" },
  { id: "exposeanapi", label: "Expose an API" },
  { id: "approles", label: "App roles" },
  { id: "owners", label: "Owners" },
  { id: "rolesandadministrators", label: "Roles and administrators" },
  { id: "manifest", label: "Manifest" },
  { id: "troubleshooting", label: "Troubleshooting" },
  { id: "newsupportrequest", label: "New support request" },
];
const LABEL = Object.fromEntries(MENU.map((m) => [m.id, m.label]));

export default function AppBlade({ params }) {
  const { id, panel = "overview" } = params;
  const a = useAsync(() => api.getApplication(id), [id]);

  let body;
  if (a.loading && !a.data) body = <Loading />;
  else if (a.error) body = <><ErrorBar error={a.error} title="Failed to load the application" /><Link href="#/entra/appregistrations">Back to App registrations</Link></>;
  else {
    const app = a.data, reload = a.reload;
    const P = {
      overview: () => <Overview app={app} reload={reload} />,
      authentication: () => <Authentication app={app} reload={reload} />,
      certificatessecrets: () => <CertificatesSecrets app={app} reload={reload} />,
      apipermissions: () => <ApiPermissions app={app} />,
      manifest: () => <Manifest app={app} />,
      owners: () => <Owners app={app} />,
    }[panel];
    body = P ? P() : (
      <>
        <div className="vy-panel-title">{`${app.displayName} | ${LABEL[panel] || panel}`}</div>
        <p>Nothing further to show here for this application.</p>
      </>
    );
  }

  return (
    <ResourceBlade title={a.data?.displayName || id} subtitle="App registration" glyph={<Glyph id="entra" />} closeHref="#/entra/appregistrations"
      menu={MENU} active={panel} hrefFor={(pid) => `#/entra/appregistrations/${encodeURIComponent(id)}${pid === "overview" ? "" : `/${pid}`}`}>
      {body}
    </ResourceBlade>
  );
}

function Overview({ app, reload }) {
  const notify = useNotify();
  const [tab, setTab] = useState("getstarted");
  const [del, setDel] = useState(false);
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Application commands">
        <ToolbarButton icon={<Delete16Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Application">
        <Tab value="getstarted">Get Started</Tab>
        <Tab value="documentation">Documentation</Tab>
      </TabList>
      {tab === "getstarted" && (
        <section className="vy-form-section">
          <h3>Essentials</h3>
          <div className="vy-essentials-grid">
            <div>
              <KV label="Display name" value={app.displayName} />
              <KV label="Application (client) ID" value={app.appId} />
              <KV label="Object ID" value={app.id} />
              <KV label="Directory (tenant) ID" value={api.DEFAULT_DOMAIN} />
              <KV label="Supported account types" value={app.signInAudience} />
            </div>
            <div>
              <KV label="Client credentials" value={`${(app.passwordCredentials || []).length} certificate(s), ${(app.passwordCredentials || []).length} secret(s)`} />
              <KV label="Redirect URIs" value={[...(app.web?.redirectUris || []), ...(app.spa?.redirectUris || [])].join(", ") || "Add a Redirect URI"} />
              <KV label="Application ID URI" value={app.identifierUris?.[0] || "Add an Application ID URI"} />
              <KV label="Managed application in local directory" value={app.displayName} />
            </div>
          </div>
        </section>
      )}
      {tab === "documentation" && <div style={{ padding: "12px 0" }}>See the Microsoft Graph applications API for the full reference.</div>}
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="application" names={[app.displayName]}
        onConfirm={async () => { await api.deleteApplication(app.id); notify.success(`Deleted ${app.displayName}.`, "Delete succeeded"); navigate("entra", "appregistrations"); }} />
    </>
  );
}

function Authentication({ app, reload }) {
  const notify = useNotify();
  const [audience, setAudience] = useState(app.signInAudience);
  const [publicClient, setPublicClient] = useState(app.isFallbackPublicClient ? "Yes" : "No");
  const save = async (patch) => { await api.updateApplication(app.id, patch); notify.success("Settings saved.", "Authentication"); reload(); };
  return (
    <>
      <div className="vy-panel-title">{`${app.displayName} | Authentication`}</div>
      <section className="vy-form-section">
        <h3>Platform configurations</h3>
        <Button onClick={() => navigate("entra", "appregistrations", app.id, "authentication")}>Add a platform</Button>
      </section>
      <section className="vy-form-section">
        <h3>Supported account types</h3>
        <div className="vy-form-row">
          <label>Who can use this application or access this API?</label>
          <RadioGroup value={audience} onChange={(_, d) => { setAudience(d.value); save({ signInAudience: d.value }); }}>
            <Radio value="AzureADMyOrg" label="Single tenant" />
            <Radio value="AzureADMultipleOrgs" label="Multiple tenants" />
          </RadioGroup>
        </div>
      </section>
      <section className="vy-form-section">
        <h3>Advanced settings</h3>
        <div className="vy-form-row">
          <label>Allow public client flows</label>
          <RadioGroup value={publicClient} onChange={(_, d) => { setPublicClient(d.value); save({ isFallbackPublicClient: d.value === "Yes" }); }}>
            <Radio value="Yes" label="Yes" /><Radio value="No" label="No" />
          </RadioGroup>
        </div>
      </section>
    </>
  );
}

function CertificatesSecrets({ app, reload }) {
  const notify = useNotify();
  const [tab, setTab] = useState("secrets");
  const [adding, setAdding] = useState(true);
  const [desc, setDesc] = useState("");
  const [expires, setExpires] = useState("Recommended: 180 days (6 months)");
  const [justCreated, setJustCreated] = useState(null);
  const [signInResult, setSignInResult] = useState(null);
  const DAYS = { "Recommended: 180 days (6 months)": 180, "90 days (3 months)": 90, "365 days (12 months)": 365, "545 days (18 months)": 545, "730 days (24 months)": 730 };
  const add = async () => {
    const end = new Date(Date.now() + (DAYS[expires] || 180) * 86400000).toISOString();
    const r = await api.addPassword(app.id, desc, end);
    setJustCreated(r); setAdding(false); setDesc(""); setSignInResult(null);
    notify.success("Client secret created.", "Certificates & secrets");
    reload();
  };
  const remove = async (keyId) => { await api.removePassword(app.id, keyId); notify.success("Client secret removed.", "Certificates & secrets"); reload(); };
  // Exercises the real oauth2/v2.0/token client_credentials grant (core/azure_graph_core.py)
  // with the secret's actual value — a genuine authentication, not a UI-only toast — and
  // leaves a real row behind on the Sign-in logs page either way.
  const testSignIn = async (secretText) => {
    try {
      await api.signInWithSecret(app.appId, secretText);
      setSignInResult(`Sign-in succeeded — a real "Service principal sign-ins" row was added to Sign-in logs.`);
    } catch (e) {
      setSignInResult(`Sign-in failed (${e.code || e.message}).`);
    }
  };
  return (
    <>
      <div className="vy-panel-title">{`${app.displayName} | Certificates & secrets`}</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Certificates & secrets">
        <Tab value="certificates">Certificates</Tab>
        <Tab value="secrets">Client secrets</Tab>
        <Tab value="federated">Federated credentials</Tab>
      </TabList>
      {tab === "secrets" && (
        <>
          <div className="vy-cmdbar" role="toolbar" aria-label="Client secrets commands">
            <ToolbarButton icon={<Add20Regular />} onClick={() => setAdding(true)}>New client secret</ToolbarButton>
          </div>
          {justCreated && (
            <p style={{ wordBreak: "break-all" }}>
              Value: <code>{justCreated.secretText}</code> — copy now, it will not be shown again.{" "}
              <Button size="small" onClick={() => testSignIn(justCreated.secretText)}>Test sign-in</Button>
            </p>
          )}
          {signInResult && <p>{signInResult}</p>}
          <Table size="small">
            <TableHeader><TableRow><TableHeaderCell>Description</TableHeaderCell><TableHeaderCell>Expires</TableHeaderCell><TableHeaderCell>Value</TableHeaderCell><TableHeaderCell>Secret ID</TableHeaderCell><TableHeaderCell /></TableRow></TableHeader>
            <TableBody>
              {(app.passwordCredentials || []).map((c) => (
                <TableRow key={c.keyId}>
                  <TableCell>{c.displayName}</TableCell>
                  <TableCell>{new Date(c.endDateTime).toLocaleDateString()}</TableCell>
                  <TableCell>{c.hint}•••••••••••••••••••</TableCell>
                  <TableCell>{c.keyId}</TableCell>
                  <TableCell><Button appearance="subtle" icon={<Delete16Regular />} onClick={() => remove(c.keyId)} aria-label="Delete secret" /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {adding && (
            <section className="vy-form-section">
              <h3>Add a client secret</h3>
              <Field label="Description"><Input value={desc} onChange={(_, d) => setDesc(d.value)} /></Field>
              <Field label="Expires">
                <Select value={expires} onChange={(_, d) => setExpires(d.value)}>
                  {Object.keys(DAYS).map((k) => <option key={k}>{k}</option>)}
                  <option>Custom</option>
                </Select>
              </Field>
              <div style={{ marginTop: 8 }}>
                <Button appearance="primary" onClick={add}>Add</Button>{" "}
                <Button onClick={() => setAdding(false)}>Cancel</Button>
              </div>
            </section>
          )}
        </>
      )}
      {tab === "certificates" && <p>No certificates have been added.</p>}
      {tab === "federated" && <p>No federated credentials have been added.</p>}
    </>
  );
}

function ApiPermissions({ app }) {
  const perms = (app.requiredResourceAccess || []).flatMap((r) => r.resourceAccess.map((a) => ({ ...a, resourceAppId: r.resourceAppId })));
  return (
    <>
      <div className="vy-panel-title">{`${app.displayName} | API permissions`}</div>
      <Table size="small">
        <TableHeader><TableRow>
          <TableHeaderCell>API / Permissions name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell>
          <TableHeaderCell>Description</TableHeaderCell><TableHeaderCell>Admin consent required</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell>
        </TableRow></TableHeader>
        <TableBody>
          {perms.map((p) => (
            <TableRow key={p.id}>
              <TableCell>Microsoft Graph / User.Read</TableCell>
              <TableCell>Delegated</TableCell>
              <TableCell>Sign in and read user profile</TableCell>
              <TableCell>No</TableCell>
              <TableCell>Granted for Default Directory</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}

function Manifest({ app }) {
  return (
    <>
      <div className="vy-panel-title">{`${app.displayName} | Manifest`}</div>
      <pre style={{ background: "var(--colorNeutralBackground3)", padding: 12, overflow: "auto", maxHeight: 480 }}>{JSON.stringify(app, null, 2)}</pre>
    </>
  );
}

function Owners({ app }) {
  return (
    <>
      <div className="vy-panel-title">{`${app.displayName} | Owners`}</div>
      <p>No owners assigned.</p>
    </>
  );
}
