/* Cloud-agnostic split-screen "cluster backup & restore" shell: LEFT = dashboard (cluster health, namespaces + pods, backup storage,
 * recovery points, jobs), RIGHT = terminal, plus the 'Deploy mock application' / 'Inject disaster' quick buttons.
 * Lens-neutral (plain elements) so Azure/AWS/GCP pages can all host it; the cloud supplies a small adapter (README.md).
 * Every number on the left is read live (poll) from the adapter's native calls -- nothing here is canned. */
import { useCallback, useEffect, useRef, useState } from "react";
import Terminal from "./Terminal.jsx";
import { APPLY_MOCK, DISASTER, MOCK_NS } from "./mockApp.js";
import { runKubectl } from "./kubectl.js";

const CSS = `
.vk-split{display:grid;grid-template-columns:minmax(380px,1fr) minmax(380px,1fr);gap:16px;height:calc(100vh - 210px);min-height:520px}
@media (max-width:900px){.vk-split{grid-template-columns:1fr;height:auto}.vk-split .vk-term{min-height:380px}}
.vk-left{overflow:auto;display:flex;flex-direction:column;gap:12px;padding-right:4px}
.vk-card{border:1px solid var(--vk-line,#d1d1d1);border-radius:6px;padding:12px 14px;background:var(--vk-card,#fff);color:inherit}
.vk-card h3{margin:0 0 8px;font-size:13px;font-weight:600}
.vk-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.vk-btn{padding:6px 12px;border-radius:4px;border:1px solid #8a8a8a;background:transparent;color:inherit;cursor:pointer;font:inherit}
.vk-btn.primary{background:#0f6cbd;border-color:#0f6cbd;color:#fff}.vk-btn.danger{background:#b10e1c;border-color:#b10e1c;color:#fff}
.vk-btn:disabled{opacity:.5;cursor:not-allowed}
.vk-pill{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11.5px;background:#e6e6e6;color:#222}
.vk-pill.ok{background:#dff6dd;color:#0e700e}.vk-pill.warn{background:#fff4ce;color:#835b00}.vk-pill.bad{background:#fde7e9;color:#a4262c}
.vk-kv{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:12.5px}.vk-kv b{font-weight:600}
.vk-table{width:100%;border-collapse:collapse;font-size:12.5px}.vk-table th{text-align:left;font-weight:600;padding:3px 6px;border-bottom:1px solid var(--vk-line,#d1d1d1)}.vk-table td{padding:3px 6px;vertical-align:top}
.vk-muted{opacity:.7;font-size:12px}
`;
const pill = (txt, kind) => <span className={`vk-pill ${kind || ""}`}>{txt}</span>;
const jobKind = (s) => (/complete|succeed/i.test(s) ? "ok" : /fail/i.test(s) ? "bad" : "warn");

async function readKube(adapter) {
  let items;
  if (adapter.store) items = [...(await adapter.store.list("Namespace")), ...(await adapter.store.list("Pod", null)), ...(await adapter.store.list("Deployment", null))];
  else {
    const r = adapter.kubectl ? await adapter.kubectl("kubectl get namespaces,pods,deployments -A -o json") : await runKubectl(adapter.store, "kubectl get namespaces,pods,deployments -A -o json");
    if (r.exitCode) throw new Error(r.logs);
    items = JSON.parse(r.logs).items || [];
  }
  const system = new Set(["kube-system", "kube-public", "kube-node-lease"]);
  const nss = items.filter((o) => o.kind === "Namespace").map((o) => o.metadata.name).filter((n) => !system.has(n));
  return nss.map((n) => ({ name: n, pods: items.filter((o) => o.kind === "Pod" && o.metadata.namespace === n), deployments: items.filter((o) => o.kind === "Deployment" && o.metadata.namespace === n) }));
}

export default function BackupDashboard({ adapter }) {
  const L = { cluster: "Cluster", vault: "Backup vault", storage: "Backup storage", recoveryPoints: "Recovery points", ...(adapter.labels || {}) };
  const [snap, setSnap] = useState({ loading: true });
  const term = useRef(null);
  const alive = useRef(true);
  const refresh = useCallback(async () => {
    try {
      const [cluster, kube, backup] = await Promise.all([adapter.getCluster(), readKube(adapter), adapter.getBackup()]);
      if (alive.current) setSnap({ cluster, kube, backup });
    } catch (e) { if (alive.current) setSnap((s) => ({ ...s, loading: false, error: e.message || String(e) })); }
  }, [adapter]);
  useEffect(() => { alive.current = true; refresh(); const t = setInterval(refresh, 2000); return () => { alive.current = false; clearInterval(t); }; }, [refresh]);
  const run = (cmd) => term.current?.exec(cmd);
  const { cluster, kube, backup, error } = snap;
  const hasApp = (kube || []).some((n) => n.name === MOCK_NS);
  const running = (backup?.jobs || []).some((j) => /progress/i.test(j.status));
  return (
    <div data-testid="kube-backup">
      <style>{CSS}</style>
      <div className="vk-row" style={{ marginBottom: 10 }}>
        <button className="vk-btn primary" data-testid="deploy-mock" onClick={() => run(adapter.deployCommand || APPLY_MOCK)}>Deploy mock application</button>
        <button className="vk-btn danger" data-testid="inject-disaster" onClick={() => run(adapter.disasterCommand || DISASTER)}>Inject disaster (delete namespace)</button>
        <button className="vk-btn" onClick={refresh}>Refresh</button>
        <span className="vk-muted">{adapter.podsNote ?? "Pods are Pending: Vyomi stores Kubernetes objects but runs no kubelet or containers."}</span>
      </div>
      {error && <div className="vk-card" style={{ borderColor: "#a4262c" }}>{error}</div>}
      <div className="vk-split">
        <div className="vk-left" data-testid="kube-dashboard">
          <div className="vk-card"><h3>{L.cluster} health</h3>
            {cluster ? <div className="vk-kv"><b>Name</b><span>{cluster.name}</span><b>State</b><span>{pill(cluster.state, /run|ok|healthy/i.test(cluster.state) ? "ok" : "warn")}</span>
              {cluster.version && <><b>Kubernetes</b><span>{cluster.version}</span></>}{cluster.location && <><b>Location</b><span>{cluster.location}</span></>}
              <b>Namespaces</b><span>{(kube || []).length} user, {(kube || []).reduce((n, x) => n + x.pods.length, 0)} pods</span></div> : <span className="vk-muted">Loading...</span>}</div>
          <div className="vk-card"><h3>Active namespaces</h3>
            {!kube ? <span className="vk-muted">Loading...</span> : !kube.length ? <span data-testid="no-namespaces" className="vk-muted">No user namespaces. Use 'Deploy mock application' or kubectl apply.</span> :
              <table className="vk-table"><thead><tr><th>Namespace</th><th>Deployments</th><th>Pods</th></tr></thead><tbody>
                {kube.map((n) => <tr key={n.name} data-testid={`ns-${n.name}`}><td>{n.name}</td><td>{n.deployments.length}</td>
                  <td>{n.pods.length ? n.pods.map((p) => <div key={p.metadata.name}>{p.metadata.name} {pill(p.status?.phase || "Pending", "warn")}</div>) : <span className="vk-muted">none</span>}</td></tr>)}
              </tbody></table>}</div>
          <div className="vk-card"><h3>{L.vault} and {L.storage.toLowerCase()}</h3>
            {!backup ? <span className="vk-muted">Loading...</span> : <>
              <div className="vk-kv"><b>{L.vault}</b><span data-testid="vault-state">{backup.vault ? <>{backup.vault.name} {pill(backup.vault.state || "Ready", "ok")}</> : <span className="vk-muted">not created</span>}</span>
                <b>Protection</b><span>{backup.instance ? <>{backup.instance.name} {pill(backup.instance.state || "Configured", "ok")}</> : <span className="vk-muted">no backup instance</span>}</span>
                <b>{L.storage}</b><span data-testid="storage-state">{backup.storage ? <>{backup.storage.account} / {backup.storage.container} {pill(`${backup.storage.blobs} blob${backup.storage.blobs === 1 ? "" : "s"}`, backup.storage.blobs ? "ok" : "")}</> : <span className="vk-muted">not provisioned</span>}</span></div>
              {backup.note && <div className="vk-muted" style={{ marginTop: 6 }}>{backup.note}</div>}</>}</div>
          <div className="vk-card"><h3>{L.recoveryPoints}</h3>
            {!backup?.recoveryPoints?.length ? <span data-testid="no-rps" className="vk-muted">No recovery points yet. Run the ad-hoc backup command in the terminal.</span> :
              <table className="vk-table" data-testid="rp-table"><thead><tr><th>Recovery point</th><th>Time</th><th>Contents</th></tr></thead><tbody>
                {backup.recoveryPoints.map((r) => <tr key={r.id}><td>{r.id.slice(0, 12)}</td><td>{new Date(r.time).toLocaleString()}</td><td>{r.contents}</td></tr>)}</tbody></table>}</div>
          <div className="vk-card"><h3>Backup and restore jobs {running && pill("running", "warn")}</h3>
            {!backup?.jobs?.length ? <span className="vk-muted">No jobs.</span> :
              <table className="vk-table" data-testid="job-table"><thead><tr><th>Operation</th><th>Status</th><th>Started</th></tr></thead><tbody>
                {backup.jobs.map((j) => <tr key={j.id}><td>{j.operation}</td><td>{pill(j.status, jobKind(j.status))}</td><td>{new Date(j.start).toLocaleTimeString()}</td></tr>)}</tbody></table>}</div>
          {adapter.footer}
        </div>
        <Terminal ref={term} adapter={adapter} onCommandDone={refresh} />
      </div>
    </div>
  );
}
