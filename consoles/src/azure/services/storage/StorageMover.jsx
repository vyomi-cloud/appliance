/* Storage Mover + Data migration for a storage account. "Copy data" drives the real Microsoft.StorageMover engine
 * (core/azure_storagemover_core.py): mover + project + endpoints + job definition are created through ARM and the job
 * run really copies bytes between Blob containers / Azure Files shares hosted by Vyomi. */
import { useState } from "react";
import { Button, Field, Input, Link, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { arm, armList, rgPath, subPath } from "../../kit/az08.js";
import { ErrorBar, fmtBytes, InfoBar, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";
import * as files from "./files.js";

const V = "2024-07-01";
const moverBase = (rg, n) => `${rgPath(rg)}/providers/Microsoft.StorageMover/storageMovers/${n}`;

export function StorageMover({ a }) {
  const notify = useNotify();
  const containers = useAsync(() => api.listContainers(a.name), [a.name]);
  const shares = useAsync(() => files.listShares(a, false), [a.id]);
  const movers = useAsync(() => armList(`${subPath()}/providers/Microsoft.StorageMover/storageMovers`, {}), []);
  const [f, setF] = useState({ source: "", target: "", targetKind: "container", subpath: "", mode: "Additive" });
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState(null);
  const mover = (movers.data || [])[0];
  const cs = containers.data || [], ss = shares.data || [];

  const copy = async () => {
    setBusy(true);
    try {
      const rg = a.resourceGroup, mname = mover?.name || `${a.name}-mover`;
      if (!mover) await arm("PUT", moverBase(rg, mname), { location: a.location || "eastus", properties: { description: `Storage Mover for ${a.name}` } }, {}, V);
      const mrg = mover ? (mover.id.match(/resourceGroups\/([^/]+)/i) || [])[1] : rg;
      const base = moverBase(mrg, mname);
      const ep = (name, props) => arm("PUT", `${base}/endpoints/${name}`, { properties: props }, {}, V);
      const key = `${f.source}-${f.target}`.replace(/[^A-Za-z0-9_-]/g, "-").slice(0, 40);
      await ep(`src-${key}`, { endpointType: "AzureStorageBlobContainer", storageAccountResourceId: a.id, blobContainerName: f.source });
      await ep(`dst-${key}`, f.targetKind === "container"
        ? { endpointType: "AzureStorageBlobContainer", storageAccountResourceId: a.id, blobContainerName: f.target }
        : { endpointType: "AzureStorageSmbFileShare", storageAccountResourceId: a.id, fileShareName: f.target });
      await arm("PUT", `${base}/projects/default`, { properties: {} }, {}, V);
      const job = `copy-${key}`;
      await arm("PUT", `${base}/projects/default/jobDefinitions/${job}`, { properties: { copyMode: f.mode, sourceName: `src-${key}`, targetName: `dst-${key}`, ...(f.subpath ? { targetSubpath: f.subpath } : {}) } }, {}, V);
      await arm("POST", `${base}/projects/default/jobDefinitions/${job}/startJob`, {}, {}, V);
      const r = await armList(`${base}/projects/default/jobDefinitions/${job}/jobRuns`, {});
      setRuns(r);
      const st = r[0]?.properties;
      (st?.status === "Succeeded" ? notify.success : notify.error)(st?.status === "Succeeded" ? `Copied ${st.transferredItemsCount} item(s), ${fmtBytes(st.transferredBytes)}.` : (st?.error?.message || "The job failed."), st?.status === "Succeeded" ? "Copy job succeeded" : "Copy job failed");
      movers.reload(); containers.reload(); shares.reload();
    } catch (e) { notify.error(e, "Failed to start the copy job"); } finally { setBusy(false); }
  };

  return (
    <CapabilityContainer id="azure.storage.storagemover" title={`${a.name} | Storage Mover`}>
      <InfoBar>Storage Mover jobs here really copy data between Blob containers and Azure Files shares hosted by this Vyomi. On-premises NFS / SMB sources need a Storage Mover agent, which Vyomi does not provide.</InfoBar>
      <ErrorBar error={containers.error || shares.error || movers.error} />
      {containers.loading || shares.loading ? <Loading /> : (
        <section className="vy-section" style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 10 }}>
          <h3>Copy data</h3>
          <Field label="Source container"><Select value={f.source} onChange={(_, d) => setF({ ...f, source: d.value })} aria-label="Source container">
            <option value="">Select</option>{cs.map((c) => <option key={c.name}>{c.name}</option>)}</Select></Field>
          <Field label="Target type"><Select value={f.targetKind} onChange={(_, d) => setF({ ...f, targetKind: d.value, target: "" })} aria-label="Target type">
            <option value="container">Blob container</option><option value="share">Azure Files share</option></Select></Field>
          <Field label="Target"><Select value={f.target} onChange={(_, d) => setF({ ...f, target: d.value })} aria-label="Target">
            <option value="">Select</option>{(f.targetKind === "container" ? cs : ss).map((c) => <option key={c.name}>{c.name}</option>)}</Select></Field>
          <Field label="Target sub-path (optional)"><Input value={f.subpath} onChange={(_, d) => setF({ ...f, subpath: d.value })} aria-label="Target sub-path" /></Field>
          <Field label="Copy mode"><Select value={f.mode} onChange={(_, d) => setF({ ...f, mode: d.value })} aria-label="Copy mode">
            <option value="Additive">Additive (keep extra files at the target)</option><option value="Mirror">Mirror (delete files missing at the source)</option></Select></Field>
          <div><Button appearance="primary" disabled={busy || !f.source || !f.target} onClick={copy}>Start copy job</Button></div>
        </section>
      )}
      {runs && (
        <section className="vy-section" style={{ marginTop: 16 }}><h3>Job runs</h3>
          <table className="vy-grid">
            <thead><tr><th>Run</th><th>Status</th><th>Scanned</th><th>Copied</th><th>Skipped</th><th>Deleted</th><th>Error</th></tr></thead>
            <tbody>{runs.map((r) => (
              <tr key={r.name}><td>{r.name.slice(0, 8)}</td><td>{r.properties.status}</td><td>{r.properties.scannedItemsCount}</td>
                <td>{r.properties.transferredItemsCount} ({fmtBytes(r.properties.transferredBytes)})</td><td>{r.properties.itemsExcluded}</td><td>{r.properties.itemsDeleted}</td>
                <td>{r.properties.error?.message || "--"}</td></tr>))}</tbody>
          </table>
        </section>
      )}
      <p style={{ fontSize: 13, marginTop: 12 }}>Storage Mover: {mover ? <>{mover.name} in {(mover.id.match(/resourceGroups\/([^/]+)/i) || [])[1]}</> : "none yet (created with the first job)"}. For one-off copies see <Link href={`#/storage/${a.resourceGroup}/${a.name}/datamigration`}>Data migration</Link>.</p>
    </CapabilityContainer>
  );
}

/** Data migration blade: ready-made AzCopy commands for this account + the in-product copy engine. */
export function DataMigration({ a }) {
  const ep = api.blobEndpoint(a.name);
  const cmds = [
    ["Upload a local folder to a container", `azcopy copy "./data/*" "${ep}/<container>?<SAS>" --recursive`],
    ["Copy one container to another", `azcopy copy "${ep}/<source>?<SAS>" "${ep}/<target>?<SAS>" --recursive`],
    ["Keep two containers in sync", `azcopy sync "./data" "${ep}/<container>?<SAS>" --delete-destination=true`],
  ];
  return (
    <CapabilityContainer id="azure.storage.datamigration" title={`${a.name} | Data migration`}>
      <InfoBar>AzCopy is a separately installed CLI; point it at this account's Vyomi endpoint. For copies that run inside Vyomi use <Link href={`#/storage/${a.resourceGroup}/${a.name}/storagemover`}>Storage Mover</Link>. Azure Data Box needs a physical device shipped by Microsoft and is not simulated.</InfoBar>
      <section className="vy-section" style={{ maxWidth: 820 }}>
        <h3>AzCopy commands for this account</h3>
        {cmds.map(([t, c]) => (<Field key={t} label={t}><Input readOnly value={c} aria-label={t} /></Field>))}
      </section>
    </CapabilityContainer>
  );
}
