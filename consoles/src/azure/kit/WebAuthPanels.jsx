/* App Service / Function App: Entra authentication (config/authsettingsV2 form + live front-door enforcement demo) and the
 * Azure OpenAI connection panel. Backed by core/azure_webauth_core.py (validation, enforcement, aoaiconnection). */
import { useState } from "react";
import { Button, Field, Input, Select, Switch, Textarea } from "@fluentui/react-components";
import { restJson } from "../../common/wire.js";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { getSubscription } from "./arm.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading } from "./common.jsx";

const Q = { "api-version": "2023-12-01" };
const site = (rg, name) => `/subscriptions/${getSubscription()}/resourceGroups/${rg}/providers/Microsoft.Web/sites/${name}`;
const ACTIONS = [["RedirectToLoginPage", "HTTP 302 Found redirect: recommended for websites"], ["Return401", "HTTP 401 Unauthorized: recommended for APIs"], ["Return403", "HTTP 403 Forbidden"], ["AllowAnonymous", "Allow unauthenticated access"]];

export function EntraAuthentication({ rg, name, capId, isFunctionApp }) {
  const notify = useNotify();
  const auth = useAsync(async () => (await restJson("GET", `${site(rg, name)}/config/authsettingsV2`, { query: Q })).properties || {}, [rg, name]);
  const fns = useAsync(async () => isFunctionApp ? ((await restJson("GET", `${site(rg, name)}/functions`, { query: Q })).value || []) : [], [rg, name]);
  const [f, setF] = useState(null);
  const [err, setErr] = useState(null);
  const [probe, setProbe] = useState({ fn: "", header: "", res: null });
  const d = auth.data;
  if (auth.loading || !d) return <Loading />;
  const aad = d.identityProviders?.azureActiveDirectory?.registration || {};
  const cur = f || {
    enabled: !!d.platform?.enabled, action: d.globalValidation?.unauthenticatedClientAction || "RedirectToLoginPage",
    clientId: aad.clientId || "", tenant: (aad.openIdIssuerUrl || "").match(/[0-9a-f-]{36}/i)?.[0] || "", secret: aad.clientSecretSettingName || "",
    audiences: (d.identityProviders?.azureActiveDirectory?.validation?.allowedAudiences || []).join(", "), excluded: (d.globalValidation?.excludedPaths || []).join("\n"),
  };
  const set = (k) => (_, v) => setF({ ...cur, [k]: v.value ?? v.checked });
  const save = async () => {
    setErr(null);
    const providers = cur.clientId || cur.tenant ? { azureActiveDirectory: { enabled: true, registration: {
      clientId: cur.clientId, openIdIssuerUrl: `https://login.microsoftonline.com/${cur.tenant}/v2.0`, ...(cur.secret ? { clientSecretSettingName: cur.secret } : {}) },
      validation: { allowedAudiences: cur.audiences.split(",").map((s) => s.trim()).filter(Boolean) } } } : undefined;
    const body = { properties: { platform: { enabled: cur.enabled }, globalValidation: { unauthenticatedClientAction: cur.action, ...(providers ? { redirectToProvider: "azureactivedirectory" } : {}),
      excludedPaths: cur.excluded.split("\n").map((s) => s.trim()).filter(Boolean) }, ...(providers ? { identityProviders: providers } : {}), login: { tokenStore: { enabled: true } } } };
    try { await restJson("PUT", `${site(rg, name)}/config/authsettingsV2`, { query: Q, body }); notify.success("Authentication settings saved.", "Save succeeded"); setF(null); auth.reload(); }
    catch (e) { setErr(e); }
  };
  const send = async () => {
    const fn = probe.fn || fns.data?.[0]?.name || "";
    try {
      const r = await restJson("POST", `${site(rg, name)}/functions/${fn}/invoke`, { query: Q, body: { method: "GET", query: {}, headers: probe.header ? { Authorization: probe.header } : {}, body: null } });
      setProbe({ ...probe, res: r });
    } catch (e) { setProbe({ ...probe, res: { status: e.status, error: e.message } }); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Authentication</div>
      <CapabilityContainer id={capId} title="App Service authentication">
        <ErrorBar error={err} title="Save failed" />
        <div style={{ display: "grid", gap: 8, maxWidth: 620 }}>
          <Field label="App Service authentication"><Switch checked={cur.enabled} aria-label="App Service authentication" onChange={set("enabled")} /></Field>
          <Field label="Restrict access / unauthenticated requests">
            <Select aria-label="Unauthenticated requests" value={cur.action} onChange={set("action")}>{ACTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
          </Field>
          <h4>Identity provider: Microsoft</h4>
          <Field label="Application (client) ID"><Input aria-label="Application client ID" value={cur.clientId} onChange={set("clientId")} /></Field>
          <Field label="Tenant ID (issuer https://login.microsoftonline.com/{tenant}/v2.0)"><Input aria-label="Tenant ID" value={cur.tenant} onChange={set("tenant")} /></Field>
          <Field label="Client secret setting name"><Input aria-label="Client secret setting name" value={cur.secret} onChange={set("secret")} /></Field>
          <Field label="Allowed token audiences (comma separated)"><Input aria-label="Allowed token audiences" value={cur.audiences} onChange={set("audiences")} /></Field>
          <Field label="Excluded paths (one per line)"><Textarea aria-label="Excluded paths" value={cur.excluded} onChange={set("excluded")} rows={3} /></Field>
          <div><Button appearance="primary" onClick={save}>Save</Button></div>
        </div>
        {d.platform?.enabled && d.token && <div className="vy-props" style={{ marginTop: 12 }}><KV label="Simulator bearer token (always accepted)" value={<code>{d.token}</code>} /></div>}
        <h3 style={{ marginTop: 20 }}>Try the front door</h3>
        {isFunctionApp ? (
          <div style={{ display: "grid", gap: 8, maxWidth: 620 }} data-testid="auth-probe">
            <Field label="Function"><Select aria-label="Probe function" value={probe.fn || fns.data?.[0]?.name || ""} onChange={(_, v) => setProbe({ ...probe, fn: v.value })}>
              {(fns.data || []).map((x) => <option key={x.name}>{x.name}</option>)}</Select></Field>
            <Field label="Authorization header (optional)"><Input aria-label="Probe Authorization header" placeholder="Bearer <token or Entra JWT>" value={probe.header} onChange={(_, v) => setProbe({ ...probe, header: v.value })} /></Field>
            <div><Button onClick={send}>Send request</Button></div>
            {probe.res && <InfoBar intent={probe.res.ok ? "success" : "error"} title={`HTTP ${probe.res.status}`}><span data-testid="probe-result">{probe.res.error || "Request reached the function."}</span></InfoBar>}
          </div>
        ) : <p style={{ fontSize: 13 }}>Web (non-function) apps do not serve requests in Vyomi, so authentication is stored and validated but not enforced. Use a Function App to see enforcement.</p>}
        <p style={{ fontSize: 12, marginTop: 8 }}>A request passes with the simulator token or a JWT whose audience, tenant and expiry match this configuration. JWT signatures are not verified and there is no interactive sign-in.</p>
      </CapabilityContainer>
    </>
  );
}

export function AzureOpenAIConnection({ rg, name, capId }) {
  const notify = useNotify();
  const sid = getSubscription();
  const accts = useAsync(async () => ((await restJson("GET", `/subscriptions/${sid}/providers/Microsoft.CognitiveServices/accounts`, { query: { "api-version": "2024-10-01" } })).value || []).filter((a) => ["OpenAI", "AIServices"].includes(a.kind)), [sid]);
  const conn = useAsync(async () => { try { return (await restJson("GET", `${site(rg, name)}/aoaiconnection`, { query: Q })).properties; } catch { return null; } }, [rg, name]);
  const [acct, setAcct] = useState("");
  const [dep, setDep] = useState("");
  const [ver, setVer] = useState("2024-06-01");
  const [mode, setMode] = useState("key");
  const [err, setErr] = useState(null);
  const sel = acct || accts.data?.[0]?.id || "";
  const deps = useAsync(async () => sel ? ((await restJson("GET", `${sel}/deployments`, { query: { "api-version": "2024-10-01" } })).value || []) : [], [sel]);
  const save = async () => {
    setErr(null);
    try {
      await restJson("PUT", `${site(rg, name)}/aoaiconnection`, { query: Q, body: { properties: { accountId: sel, deploymentName: dep || deps.data?.[0]?.name, apiVersion: ver, authMode: mode } } });
      notify.success("Azure OpenAI connection saved to the app settings.", "Save succeeded"); conn.reload();
    } catch (e) { setErr(e); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Azure OpenAI</div>
      <CapabilityContainer id={capId} title="Azure OpenAI connection">
        <ErrorBar error={err} title="Connection failed" />
        {conn.data && <div className="vy-props" data-testid="aoai-current"><KV label="Endpoint" value={conn.data.endpoint} /><KV label="Deployment" value={`${conn.data.deploymentName || "--"} (${conn.data.deploymentExists ? "exists" : "missing"})`} /><KV label="Authentication" value={conn.data.authMode} /></div>}
        <div style={{ display: "grid", gap: 8, maxWidth: 560, marginTop: 12 }}>
          <Field label="Azure OpenAI account"><Select aria-label="Azure OpenAI account" value={sel} onChange={(_, v) => setAcct(v.value)}>{(accts.data || []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
          <Field label="Deployment"><Select aria-label="Deployment" value={dep || deps.data?.[0]?.name || ""} onChange={(_, v) => setDep(v.value)}>{(deps.data || []).map((x) => <option key={x.name}>{x.name}</option>)}</Select></Field>
          <Field label="API version"><Input aria-label="API version" value={ver} onChange={(_, v) => setVer(v.value)} /></Field>
          <Field label="Authentication"><Select aria-label="Authentication type" value={mode} onChange={(_, v) => setMode(v.value)}><option value="key">API key</option><option value="managedIdentity">Managed identity</option></Select></Field>
          <div><Button appearance="primary" onClick={save}>Connect</Button></div>
        </div>
        <p style={{ fontSize: 12, marginTop: 8 }}>Writes AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, AZURE_OPENAI_API_VERSION (and AZURE_OPENAI_API_KEY) to the app settings, validated against the account and deployment. The app code is not run against it.</p>
      </CapabilityContainer>
    </>
  );
}
