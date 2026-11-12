/* AKS GitOps (Flux configurations) + Automated deployments (GitHub Actions). Both are real ARM child resources of the
 * managed cluster handled by core/azure_flux_core.py (reconcile over the cluster object store, real build/push/deploy runs).
 * Every action goes over the native ARM wire; the capability registry says exactly what is and is not real. */
import { useState } from "react";
import { Button, Checkbox, Field, Input, Select, Textarea } from "@fluentui/react-components";
import { restJson } from "../../common/wire.js";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, InfoBar, Loading } from "./common.jsx";
import { getSubscription } from "./arm.js";

const FLUX_V = { "api-version": "2023-05-01" };
const AD_V = { "api-version": "2024-09-02-preview" };

function useRun(reload) {
  const notify = useNotify();
  return async (fn, ok) => {
    try { await fn(); notify.success(ok, "Done"); await reload?.(); return true; } catch (e) { notify.error(e, "Operation failed"); return false; }
  };
}

const badge = (s) => <span className={s === "Compliant" || s === "Succeeded" ? "vy-ok" : s === "Pending" || s === "InProgress" ? "vy-muted" : "vy-err"}>{s || "-"}</span>;

export function AksGitOps({ a }) {
  const base = `${a.id}/providers/Microsoft.KubernetesConfiguration/fluxConfigurations`;
  const list = useAsync(async () => (await restJson("GET", base, { query: FLUX_V })).value || [], [a.id]);
  const run = useRun(list.reload);
  const [f, setF] = useState({ name: "", url: "", branch: "main", path: "./", prune: true, namespace: "", key: "" });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value ?? d.checked }));
  const create = async () => {
    const ok = await run(() => restJson("PUT", `${base}/${f.name}`, { query: FLUX_V, body: { properties: {
      scope: "cluster", namespace: f.namespace || f.name, sourceKind: "GitRepository",
      gitRepository: { url: f.url, repositoryRef: { branch: f.branch }, ...(f.key ? { httpsUser: "git" } : {}) },
      ...(f.key ? { configurationProtectedSettings: { httpsKey: f.key } } : {}),
      kustomizations: { apps: { path: f.path, prune: f.prune } } } } }), `Flux configuration '${f.name}' was created.`);
    if (ok) setF((x) => ({ ...x, name: "", url: "", key: "" }));
  };
  return (
    <CapabilityContainer id="azure.aks.gitops" title={`${a.name} | GitOps`}>
      <ErrorBar error={list.error} />
      {list.loading && !list.data ? <Loading /> : (
        <table className="vy-grid" aria-label="Flux configurations">
          <thead><tr><th>Name</th><th>Source</th><th>Compliance</th><th>Synced revision</th><th>Last sync</th><th /></tr></thead>
          <tbody>{(list.data || []).length ? list.data.map((c) => {
            const p = c.properties || {};
            return (
              <tr key={c.name}>
                <td>{c.name}</td><td>{p.gitRepository?.url}@{p.gitRepository?.repositoryRef?.branch}</td><td>{badge(p.complianceState)}</td>
                <td title={p.errorMessage || ""}>{p.sourceSyncedCommitId ? p.sourceSyncedCommitId.replace("sha1:", "").slice(0, 20) : p.errorMessage || "-"}</td><td>{p.lastSourceSyncedAt || "-"}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <Button size="small" aria-label={`Reconcile ${c.name}`} onClick={() => run(() => restJson("POST", `${base}/${c.name}/reconcile`, { query: FLUX_V, body: {} }), `Reconciled '${c.name}'.`)}>Reconcile</Button>{" "}
                  <Button size="small" aria-label={`Delete ${c.name}`} onClick={() => run(() => restJson("DELETE", `${base}/${c.name}`, { query: FLUX_V }), `Flux configuration '${c.name}' was deleted.`)}>Delete</Button>
                </td>
              </tr>
            );
          }) : <tr><td colSpan={6} className="vy-muted">No Flux configurations.</td></tr>}</tbody>
        </table>
      )}
      {(list.data || []).map((c) => (c.properties?.statuses || []).length > 0 && (
        <details key={c.name} style={{ marginTop: 8 }}><summary>{c.name} - object status</summary>
          <table className="vy-grid" aria-label={`${c.name} status`}><thead><tr><th>Kind</th><th>Name</th><th>State</th><th>Message</th></tr></thead>
            <tbody>{c.properties.statuses.map((s) => <tr key={s.kind + s.name}><td>{s.kind}</td><td>{s.name}</td><td>{badge(s.complianceState)}</td><td>{s.statusConditions?.[0]?.message}</td></tr>)}</tbody></table>
        </details>
      ))}
      <h4 style={{ marginTop: 16 }}>Create configuration</h4>
      <InfoBar>Source is a https://github.com/owner/repo URL (private repos: a personal access token) or vyomi://repo for a repository inside Vyomi. Installs the Flux extension if absent.</InfoBar>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Configuration name"><Input value={f.name} onChange={set("name")} aria-label="Configuration name" /></Field>
        <Field label="Repository URL"><Input value={f.url} onChange={set("url")} placeholder="https://github.com/org/repo" aria-label="Repository URL" /></Field>
        <Field label="Branch"><Input value={f.branch} onChange={set("branch")} aria-label="Branch" /></Field>
        <Field label="Kustomization path"><Input value={f.path} onChange={set("path")} aria-label="Kustomization path" /></Field>
        <Field label="Namespace"><Input value={f.namespace} onChange={set("namespace")} aria-label="Namespace" /></Field>
        <Field label="Personal access token (optional)"><Input type="password" value={f.key} onChange={set("key")} aria-label="Personal access token" /></Field>
        <Checkbox checked={f.prune} onChange={set("prune")} label="Prune" aria-label="Prune" />
        <Button appearance="primary" disabled={!f.name || !f.url} onClick={create} aria-label="Create Flux configuration">Create</Button>
      </div>
    </CapabilityContainer>
  );
}

export function AksAutomatedDeployments({ a }) {
  const base = `${a.id}/vyomiAutomatedDeployments`;
  const list = useAsync(async () => (await restJson("GET", base, { query: AD_V })).value || [], [a.id]);
  const acrs = useAsync(async () => (await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.ContainerRegistry/registries`, { query: { "api-version": "2023-07-01" } })).value || [], []);
  const run = useRun(list.reload);
  const [f, setF] = useState({ name: "", repoUrl: "", branch: "main", acrId: "", imageName: "", namespace: "default", manifestPath: "manifests", dockerfilePath: "Dockerfile", key: "" });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const create = async () => {
    const ok = await run(() => restJson("PUT", `${base}/${f.name}`, { query: AD_V, body: { properties: {
      repoUrl: f.repoUrl, branch: f.branch, acrId: f.acrId || acrs.data?.[0]?.id, imageName: f.imageName, namespace: f.namespace,
      manifestPath: f.manifestPath, dockerfilePath: f.dockerfilePath, ...(f.key ? { vyomiAccessToken: f.key } : {}) } } }), `Automated deployment '${f.name}' was created.`);
    if (ok) setF((x) => ({ ...x, name: "", key: "" }));
  };
  return (
    <CapabilityContainer id="azure.aks.automateddeployments" title={`${a.name} | Automated deployments`}>
      <ErrorBar error={list.error} />
      {list.loading && !list.data ? <Loading /> : (list.data || []).length ? list.data.map((d) => {
        const p = d.properties || {};
        return (
          <section key={d.name} className="vy-form-section" aria-label={`Deployment ${d.name}`}>
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <strong>{d.name}</strong><span>{p.repoUrl}@{p.branch}</span><span>{p.lastRun ? badge(p.lastRun.status) : "no runs"}</span>
              <span style={{ marginLeft: "auto" }}>
                <Button size="small" aria-label={`Run workflow ${d.name}`} onClick={() => run(() => restJson("POST", `${base}/${d.name}/run`, { query: AD_V, body: {} }), `Workflow run for '${d.name}' finished.`)}>Run workflow</Button>{" "}
                <Button size="small" aria-label={`Delete ${d.name}`} onClick={() => run(() => restJson("DELETE", `${base}/${d.name}`, { query: AD_V }), `Automated deployment '${d.name}' was deleted.`)}>Delete</Button>
              </span>
            </div>
            {p.workflowCommitError && <InfoBar>{p.workflowCommitError}</InfoBar>}
            {p.workflowCommit && <p className="vy-muted">Workflow committed to {p.workflowCommit.repo || p.repoUrl}: {p.workflowCommit.path}{p.workflowCommit.commit ? ` (${String(p.workflowCommit.commit).slice(0, 7)})` : ""}</p>}
            <details><summary>Generated workflow {p.workflowFilePath}</summary><Textarea readOnly resize="vertical" value={p.workflowYaml || ""} style={{ width: "100%", fontFamily: "monospace" }} rows={14} aria-label={`Workflow ${d.name}`} /></details>
            <table className="vy-grid" aria-label={`Runs ${d.name}`}><thead><tr><th>Run</th><th>Trigger</th><th>Status</th><th>Image</th><th>Log</th></tr></thead>
              <tbody>{(p.runs || []).length ? p.runs.map((r) => <tr key={r.id + r.startedAt}><td>{r.id}</td><td>{r.trigger}</td><td>{badge(r.status)}</td><td>{r.image || r.error || "-"}</td>
                <td><details><summary>{(r.logs || []).length} lines</summary><pre style={{ maxHeight: 200, overflow: "auto" }}>{(r.logs || []).join("\n")}</pre></details></td></tr>) : <tr><td colSpan={5} className="vy-muted">No runs yet.</td></tr>}</tbody></table>
          </section>
        );
      }) : <p className="vy-muted">No automated deployments.</p>}
      <h4 style={{ marginTop: 16 }}>Create automated deployment</h4>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Name"><Input value={f.name} onChange={set("name")} aria-label="Deployment name" /></Field>
        <Field label="Repository"><Input value={f.repoUrl} onChange={set("repoUrl")} placeholder="https://github.com/org/repo" aria-label="Repository" /></Field>
        <Field label="Branch"><Input value={f.branch} onChange={set("branch")} aria-label="Branch" /></Field>
        <Field label="Container registry"><Select value={f.acrId || acrs.data?.[0]?.id || ""} onChange={set("acrId")} aria-label="Container registry">{(acrs.data || []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select></Field>
        <Field label="Image name"><Input value={f.imageName} onChange={set("imageName")} placeholder="contoso/web" aria-label="Image name" /></Field>
        <Field label="Namespace"><Input value={f.namespace} onChange={set("namespace")} aria-label="Namespace" /></Field>
        <Field label="Manifests path"><Input value={f.manifestPath} onChange={set("manifestPath")} aria-label="Manifests path" /></Field>
        <Field label="Dockerfile"><Input value={f.dockerfilePath} onChange={set("dockerfilePath")} aria-label="Dockerfile path" /></Field>
        <Field label="GitHub token (to commit the workflow)"><Input type="password" value={f.key} onChange={set("key")} aria-label="GitHub token" /></Field>
        <Button appearance="primary" disabled={!f.name || !f.repoUrl || !f.imageName} onClick={create} aria-label="Create automated deployment">Create</Button>
      </div>
    </CapabilityContainer>
  );
}
