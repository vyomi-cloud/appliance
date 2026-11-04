/* Deployment Center for App Service / Function App (Microsoft.Web/sites): Settings (source control), Logs, FTPS credentials.
 * Real ARM calls against core/azure_webdeploy_core.py. A sync is recorded as a Failed deployment with an explanation:
 * Vyomi has no build runner and no outbound git access (see core/capabilities/azure/appservices.json). */
import { useState } from "react";
import { Button, Field, Input, Select, Tab, TabList, Textarea, Switch } from "@fluentui/react-components";
import { restJson } from "../../common/wire.js";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";
import { Loading } from "./common.jsx";

const q = { "api-version": "2023-12-01" };
const STACKS = [["python", "Python"], ["node", "Node.js"], ["dotnetcore", ".NET"], ["java", "Java"]];

export default function DeploymentCenter({ a, cap = "azure.appservices.webapp.deploymentcenter", onChanged }) {
  const [tab, setTab] = useState("settings");
  return (
    <>
      <div className="vy-panel-title">{a.name} | Deployment Center</div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Deployment Center tabs">
        <Tab value="settings">Settings</Tab><Tab value="logs">Logs</Tab><Tab value="ftps">FTPS credentials</Tab>
      </TabList>
      <div style={{ marginTop: 12 }}>
        <CapabilityContainer id={cap} title={{ settings: "Settings", logs: "Logs", ftps: "FTPS credentials" }[tab]}>
          {tab === "settings" && <Settings a={a} onChanged={onChanged} />}
          {tab === "logs" && <Logs a={a} />}
          {tab === "ftps" && <Ftps a={a} />}
        </CapabilityContainer>
      </div>
    </>
  );
}

function Settings({ a, onChanged }) {
  const notify = useNotify();
  const src = useAsync(async () => { try { return await restJson("GET", `${a.id}/sourcecontrols/web`, { query: q }); } catch { return null; } }, [a.id]);
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);
  if (src.loading && !src.data && f === null) return <Loading />;
  const p = src.data?.properties;
  const cur = f || { source: p ? (p.isGitHubAction ? "gh" : "git") : "none", repoUrl: p?.repoUrl || "", branch: p?.branch || "main", manual: p?.isManualIntegration || false,
    stack: STACKS.find(([, l]) => l === p?.gitHubActionConfiguration?.codeConfiguration?.runtimeStack)?.[0] || "python", version: p?.gitHubActionConfiguration?.codeConfiguration?.runtimeVersion || "" };
  const set = (k, v) => setF({ ...cur, [k]: v });
  const yaml = p?.gitHubActionConfiguration?.workflowYaml;
  const save = async () => {
    setBusy(true);
    try {
      if (cur.source === "none") { await restJson("DELETE", `${a.id}/sourcecontrols/web`, { query: q }); notify.success("Disconnected from source control.", "Disconnect succeeded"); }
      else {
        const properties = { repoUrl: cur.repoUrl, branch: cur.branch, isManualIntegration: cur.source === "git" ? cur.manual : false, isGitHubAction: cur.source === "gh" };
        if (cur.source === "gh") properties.gitHubActionConfiguration = { codeConfiguration: { runtimeStack: cur.stack, runtimeVersion: cur.version || undefined }, isLinux: String(a.kind || "").includes("linux") };
        await restJson("PUT", `${a.id}/sourcecontrols/web`, { query: q, body: { properties } });
        notify.success("Deployment settings were saved.", "Save succeeded");
      }
      setF(null); src.reload(); onChanged && onChanged();
    } catch (e) { notify.error(e, "Failed to save deployment settings"); } finally { setBusy(false); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 640 }}>
      <Field label="Source">
        <Select value={cur.source} onChange={(_, d) => set("source", d.value)} aria-label="Source">
          <option value="none">Select source</option><option value="gh">GitHub</option><option value="git">External Git</option>
        </Select>
      </Field>
      {cur.source !== "none" && <>
        <Field label="Repository" required><Input value={cur.repoUrl} placeholder="https://github.com/org/repo" onChange={(_, d) => set("repoUrl", d.value)} aria-label="Repository" /></Field>
        <Field label="Branch" required><Input value={cur.branch} onChange={(_, d) => set("branch", d.value)} aria-label="Branch" /></Field>
      </>}
      {cur.source === "gh" && <>
        <Field label="Runtime stack"><Select value={cur.stack} onChange={(_, d) => set("stack", d.value)} aria-label="Runtime stack">{STACKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
        <Field label="Version"><Input value={cur.version} placeholder="e.g. 3.11" onChange={(_, d) => set("version", d.value)} aria-label="Runtime version" /></Field>
      </>}
      {cur.source === "git" && <Switch checked={cur.manual} onChange={(_, d) => set("manual", !!d.checked)} label="Manual integration (do not sync on save)" />}
      <div style={{ display: "flex", gap: 8 }}>
        <Button appearance="primary" disabled={busy || (cur.source !== "none" && !cur.repoUrl)} onClick={save}>Save</Button>
        <Button disabled={busy || f === null} onClick={() => setF(null)}>Discard</Button>
      </div>
      {yaml && <Field label={`Generated workflow (${p.gitHubActionConfiguration.workflowFilePath})`} hint="Generated, not committed: Vyomi makes no outbound connection to GitHub.">
        <Textarea readOnly value={yaml} rows={14} style={{ fontFamily: "monospace" }} aria-label="Generated GitHub workflow" /></Field>}
    </div>
  );
}

function Logs({ a }) {
  const notify = useNotify();
  const deps = useAsync(async () => (await restJson("GET", `${a.id}/deployments`, { query: q })).value || [], [a.id]);
  const sync = async () => {
    try { await restJson("POST", `${a.id}/sync`, { query: q, body: {} }); deps.reload(); }
    catch (e) { notify.error(e, "Sync failed"); }
  };
  return (
    <BrowseGrid
      resourceName="deployment" rowKey={(r) => r.id} items={deps.data || []} loading={deps.loading} error={deps.error} onRefresh={deps.reload} csvName="deployments.csv"
      extraCommands={<Button size="small" onClick={sync}>Sync</Button>}
      columns={[
        { key: "time", label: "Date", value: (r) => r.properties?.start_time },
        { key: "status", label: "Status", value: (r) => r.properties?.status_text },
        { key: "message", label: "Commit / message", value: (r) => r.properties?.message },
        { key: "log", label: "Logs", value: (r) => r.properties?.logs?.[0]?.message || "--" },
      ]}
    />
  );
}

function Ftps({ a }) {
  const notify = useNotify();
  const creds = useAsync(async () => (await restJson("POST", `${a.id}/config/publishingcredentials/list`, { query: q, body: {} })).properties, [a.id]);
  const pol = useAsync(async () => Object.fromEntries(((await restJson("GET", `${a.id}/basicPublishingCredentialsPolicies`, { query: q })).value || []).map((x) => [x.name, x.properties.allow])), [a.id]);
  const [show, setShow] = useState(false);
  const setPol = async (n, allow) => { try { await restJson("PUT", `${a.id}/basicPublishingCredentialsPolicies/${n}`, { query: q, body: { properties: { allow } } }); pol.reload(); } catch (e) { notify.error(e, "Failed to update"); } };
  const reset = async () => { try { await restJson("POST", `${a.id}/newpassword`, { query: q, body: {} }); creds.reload(); notify.success("Publishing password was reset.", "Reset succeeded"); } catch (e) { notify.error(e, "Reset failed"); } };
  if (creds.loading && !creds.data) return <Loading />;
  const c = creds.data || {};
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 640 }}>
      <Field label="FTPS endpoint"><Input readOnly value={`ftps://${a.name}.ftp.azurewebsites.windows.net/site/wwwroot`} aria-label="FTPS endpoint" /></Field>
      <Field label="Username"><Input readOnly value={c.publishingUserName || ""} aria-label="FTPS username" /></Field>
      <Field label="Password"><Input readOnly type={show ? "text" : "password"} value={c.publishingPassword || ""} aria-label="FTPS password" /></Field>
      <div style={{ display: "flex", gap: 8 }}><Button onClick={() => setShow(!show)}>{show ? "Hide" : "Show"} password</Button><Button onClick={reset}>Reset</Button></div>
      <Switch checked={!!pol.data?.ftp} onChange={(_, d) => setPol("ftp", !!d.checked)} label="Basic authentication for FTP" />
      <Switch checked={!!pol.data?.scm} onChange={(_, d) => setPol("scm", !!d.checked)} label="Basic authentication for SCM" />
    </div>
  );
}
