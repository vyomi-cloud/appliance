/* Backup / restore pages over native ARM (core/azure_dpbackup_core.py):
 *   AksBackup            - Azure Backup for AKS (backup extension, vault, policy, backup instance, recovery points, restore, jobs)
 *   CosmosPitr           - Cosmos DB point-in-time restore into a NEW account + restorable (live/deleted) accounts
 *   RestoreDeletedStorage- recover a deleted storage account (14-day window)
 *   AppBackupRestore     - App Service restore dialog (same app, slot or another app) */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, ToolbarButton } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { LOCATIONS, getSubscription, locationLabel } from "./arm.js";
import { ErrorBar, InfoBar, Loading, fmtDate } from "./common.jsx";

const sub = () => `/subscriptions/${getSubscription()}`;
const call = (method, path, version, body) => restJson(method, path, { query: { "api-version": version }, body });

export function Dlg({ open, title, onClose, onOk, okLabel = "OK", err, children, busy }) {
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={title}><DialogBody><DialogTitle>{title}</DialogTitle>
        <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}><ErrorBar error={err} title="Operation failed" />{children}</div></DialogContent>
        <DialogActions><Button appearance="primary" disabled={busy} onClick={onOk}>{okLabel}</Button><Button onClick={onClose}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
    </Dialog>
  );
}

const DP = "2023-05-01";
const EXT = "2023-05-01";

export function AksBackup({ a }) {
  const notify = useNotify();
  const sid = getSubscription();
  const ext = useAsync(async () => (await call("GET", `${a.id}/providers/Microsoft.KubernetesConfiguration/extensions`, EXT)).value || [], [a.id]);
  const vaults = useAsync(async () => (await call("GET", `${sub()}/providers/Microsoft.DataProtection/backupVaults`, DP)).value || [], [a.id]);
  const inst = useAsync(async () => {
    for (const v of (await call("GET", `${sub()}/providers/Microsoft.DataProtection/backupVaults`, DP)).value || []) {
      const items = (await call("GET", `${v.id}/backupInstances`, DP)).value || [];
      const mine = items.find((i) => i.properties?.dataSourceInfo?.resourceID?.toLowerCase() === a.id.toLowerCase());
      if (mine) return { vault: v, bi: mine };
    }
    return null;
  }, [a.id]);
  const rps = useAsync(async () => (inst.data ? (await call("GET", `${inst.data.bi.id}/recoveryPoints`, DP)).value || [] : []), [inst.data?.bi?.id]);
  const jobs = useAsync(async () => (inst.data ? (await call("GET", `${inst.data.vault.id}/backupJobs`, DP)).value || [] : []), [inst.data?.vault?.id]);
  const clusters = useAsync(async () => (await call("GET", `${sub()}/providers/Microsoft.ContainerService/managedClusters`, "2024-05-01")).value || [], [a.id]);
  const [dlg, setDlg] = useState(null);
  const [err, setErr] = useState(null);
  const [f, setF] = useState({ vault: "", newVault: "", policy: "aks-default", includeNs: "", excludeNs: "", labels: "", snapshotVolumes: true, target: "", conflict: "Skip", mapFrom: "", mapTo: "", rp: null });
  const extInstalled = (ext.data || []).some((x) => String(x.properties?.extensionType).toLowerCase() === "microsoft.dataprotection.kubernetes");
  const reloadAll = () => { ext.reload(); vaults.reload(); inst.reload(); rps.reload(); jobs.reload(); };
  const rg = a.resourceGroup || String(a.id).split("/")[4];
  const list = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

  const installExt = async () => {
    try {
      await call("PUT", `${a.id}/providers/Microsoft.KubernetesConfiguration/extensions/azure-aks-backup`, EXT, { properties: { extensionType: "microsoft.dataprotection.kubernetes", autoUpgradeMinorVersion: true, scope: { cluster: { releaseNamespace: "dataprotection-microsoft" } }, configurationSettings: { "configuration.backupStorageLocation.bucket": "aks-backup", "configuration.backupStorageLocation.config.storageAccount": "vyomidpbackup" } } });
      notify.success("Backup extension installed.", "Install extension"); reloadAll();
    } catch (e) { notify.error(e, "Install failed"); }
  };
  const vaultPolicies = useAsync(async () => (f.vault ? (await call("GET", `${(vaults.data || []).find((v) => v.name === f.vault)?.id}/backupPolicies`, DP)).value || [] : []), [f.vault, vaults.data]);
  const configure = async () => {
    setErr(null);
    try {
      let vault = (vaults.data || []).find((v) => v.name === f.vault);
      if (!vault) {
        if (!f.newVault) throw new Error("Select a backup vault or enter a name for a new one.");
        vault = await call("PUT", `${sub()}/resourceGroups/${rg}/providers/Microsoft.DataProtection/backupVaults/${f.newVault}`, DP, { location: a.location, properties: { storageSettings: [{ datastoreType: "VaultStore", type: "LocallyRedundant" }] } });
      }
      const prm = { objectType: "KubernetesClusterBackupDatasourceParameters", snapshotVolumes: f.snapshotVolumes, includeClusterScopeResources: true, includedNamespaces: list(f.includeNs), excludedNamespaces: list(f.excludeNs), labelSelectors: list(f.labels), includedResourceTypes: [], excludedResourceTypes: [] };
      await call("PUT", `${vault.id}/backupInstances/${a.name}-bi`, DP, { properties: { objectType: "BackupInstance", friendlyName: a.name, dataSourceInfo: { objectType: "Datasource", resourceID: a.id, datasourceType: "Microsoft.ContainerService/managedClusters" }, policyInfo: { policyId: `${vault.id}/backupPolicies/${f.policy}`, policyParameters: { backupDatasourceParametersList: [prm] } } } });
      notify.success(`Backup configured for '${a.name}' in vault '${vault.name}'.`, "Configure backup"); setDlg(null); reloadAll();
    } catch (e) { setErr(e); }
  };
  const backupNow = async () => {
    try { await call("POST", `${inst.data.bi.id}/backup`, DP, { backupRuleOptions: { ruleName: "BackupDaily", triggerOption: { retentionTagOverride: "Default" } } }); notify.success("Backup completed.", "Backup now"); rps.reload(); jobs.reload(); }
    catch (e) { notify.error(e, "Backup failed"); }
  };
  const restore = async () => {
    setErr(null);
    try {
      const target = (clusters.data || []).find((c) => c.name === f.target);
      if (!target) throw new Error("Select a target cluster.");
      const crit = { objectType: "KubernetesClusterRestoreCriteria", conflictPolicy: f.conflict, persistentVolumeRestoreMode: "RestoreWithVolumeData", includedNamespaces: list(f.includeNs), namespaceMappings: f.mapFrom && f.mapTo ? { [f.mapFrom]: f.mapTo } : {} };
      const r = await call("POST", `${inst.data.bi.id}/restore`, DP, { restoreRequestObject: { objectType: "AzureBackupRecoveryPointBasedRestoreRequest", recoveryPointId: f.rp.name, sourceDataStoreType: "OperationalStore", restoreTargetInfo: { objectType: "RestoreTargetInfo", recoveryOption: "FailIfExists", restoreLocation: a.location, datasourceInfo: { objectType: "Datasource", resourceID: target.id, datasourceType: "Microsoft.ContainerService/managedClusters" }, restoreCriteria: [crit] } } });
      notify.success(`Restore finished: ${r.created} created, ${r.patched} patched, ${r.skipped} skipped${r.failed?.length ? `, ${r.failed.length} failed` : ""}.`, "Restore"); setDlg(null); jobs.reload();
    } catch (e) { setErr(e); }
  };
  const setState = (verb, label) => async () => { try { await call("POST", `${inst.data.bi.id}/${verb}`, DP, {}); notify.success(`${label} done.`, label); inst.reload(); jobs.reload(); } catch (e) { notify.error(e, `${label} failed`); } };
  const del = async () => { try { await call("DELETE", inst.data.bi.id, DP); notify.success("Backup instance deleted.", "Delete"); reloadAll(); } catch (e) { notify.error(e, "Delete failed"); } };

  if (ext.loading && !ext.data) return <Loading />;
  const bi = inst.data?.bi;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Backup</div>
      <InfoBar title="Azure Backup for AKS">A backup snapshots the cluster's Kubernetes objects (namespaces, workloads, config, RBAC) into the vault; restore re-applies them to this or another cluster. Persistent volumes are recorded as metadata only and schedules are validated but do not fire on a clock.</InfoBar>
      <div className="vy-cmdbar" role="toolbar" aria-label="Backup commands">
        {!extInstalled && <ToolbarButton onClick={installExt}>Install extension</ToolbarButton>}
        {extInstalled && !bi && <ToolbarButton onClick={() => { setErr(null); setF((o) => ({ ...o, vault: (vaults.data || [])[0]?.name || "", newVault: "" })); setDlg("configure"); }}>Configure backup</ToolbarButton>}
        {bi && <ToolbarButton onClick={backupNow}>Backup now</ToolbarButton>}
        {bi && bi.properties.currentProtectionState === "ProtectionConfigured" && <ToolbarButton onClick={setState("suspendBackups", "Suspend backups")}>Suspend backups</ToolbarButton>}
        {bi && bi.properties.currentProtectionState !== "ProtectionConfigured" && <ToolbarButton onClick={setState("resumeBackups", "Resume backups")}>Resume backups</ToolbarButton>}
        {bi && <ToolbarButton onClick={del}>Delete backup instance</ToolbarButton>}
        <ToolbarButton onClick={reloadAll}>Refresh</ToolbarButton>
      </div>
      <div style={{ display: "flex", gap: 32, margin: "8px 0 16px" }}>
        <div><div style={{ fontSize: 12 }}>Backup extension</div><div>{extInstalled ? "Installed" : "Not installed"}</div></div>
        <div><div style={{ fontSize: 12 }}>Vault</div><div>{inst.data?.vault.name || "-"}</div></div>
        <div><div style={{ fontSize: 12 }}>Protection state</div><div>{bi?.properties.currentProtectionState || "Not configured"}</div></div>
        <div><div style={{ fontSize: 12 }}>Policy</div><div>{bi?.properties.policyInfo.policyId.split("/").pop() || "-"}</div></div>
        <div><div style={{ fontSize: 12 }}>Last backup</div><div>{bi?.properties.protectionStatus?.lastBackupTime ? fmtDate(bi.properties.protectionStatus.lastBackupTime) : "-"}</div></div>
      </div>
      {bi && <>
        <h3>Recovery points</h3>
        <table className="vy-grid" aria-label="Recovery points"><thead><tr><th>Time</th><th>Retention tag</th><th>Namespaces</th><th>Objects</th><th>Expires</th><th /></tr></thead><tbody>
          {(rps.data || []).length === 0 ? <tr><td colSpan={6} className="vy-muted">No recovery points yet. Use Backup now.</td></tr>
            : rps.data.map((r) => <tr key={r.name}><td>{fmtDate(r.properties.recoveryPointTime)}</td><td>{r.properties.retentionTagName}</td><td>{r.properties.namespaceCount}</td>
              <td>{Object.values(r.properties.objectCounts || {}).reduce((x, y) => x + y, 0)}</td><td>{fmtDate(r.properties.expiryTime)}</td>
              <td><Button size="small" onClick={() => { setErr(null); setF((o) => ({ ...o, rp: r, target: a.name, includeNs: "", conflict: "Skip", mapFrom: "", mapTo: "" })); setDlg("restore"); }}>Restore</Button></td></tr>)}
        </tbody></table>
        <h3 style={{ marginTop: 16 }}>Backup jobs</h3>
        <table className="vy-grid" aria-label="Backup jobs"><thead><tr><th>Operation</th><th>Status</th><th>Start time</th><th>Details</th></tr></thead><tbody>
          {(jobs.data || []).map((j) => <tr key={j.name}><td>{j.properties.operation}</td><td>{j.properties.status}</td><td>{fmtDate(j.properties.startTime)}</td>
            <td className="vy-muted">{j.properties.extendedInfo?.objectCount != null ? `${j.properties.extendedInfo.objectCount} objects` : (j.properties.extendedInfo?.created ? `${j.properties.extendedInfo.created.length} created, ${j.properties.extendedInfo.skipped.length} skipped, ${j.properties.extendedInfo.patched.length} patched` : "")}</td></tr>)}
        </tbody></table>
      </>}
      <Dlg open={dlg === "configure"} title="Configure backup" okLabel="Configure" onClose={() => setDlg(null)} err={err} onOk={configure}>
        <Field label="Backup vault"><Select value={f.vault} aria-label="Backup vault" onChange={(_, d) => setF({ ...f, vault: d.value })}>{(vaults.data || []).map((v) => <option key={v.id} value={v.name}>{v.name} ({locationLabel(v.location)})</option>)}<option value="">Create a new vault...</option></Select></Field>
        {!f.vault && <Field label="New vault name"><Input aria-label="New vault name" value={f.newVault} onChange={(_, d) => setF({ ...f, newVault: d.value })} /></Field>}
        <Field label="Backup policy"><Select value={f.policy} aria-label="Backup policy" onChange={(_, d) => setF({ ...f, policy: d.value })}>{f.vault ? (vaultPolicies.data || []).map((p) => <option key={p.id} value={p.name}>{p.name}</option>) : <option value="aks-default">aks-default</option>}</Select></Field>
        <Field label="Included namespaces" hint="Comma separated; empty = all"><Input aria-label="Included namespaces" value={f.includeNs} onChange={(_, d) => setF({ ...f, includeNs: d.value })} /></Field>
        <Field label="Excluded namespaces"><Input aria-label="Excluded namespaces" value={f.excludeNs} onChange={(_, d) => setF({ ...f, excludeNs: d.value })} /></Field>
        <Field label="Label selectors" hint="key=value, comma separated"><Input aria-label="Label selectors" value={f.labels} onChange={(_, d) => setF({ ...f, labels: d.value })} /></Field>
        <Checkbox checked={f.snapshotVolumes} onChange={(_, d) => setF({ ...f, snapshotVolumes: !!d.checked })} label="Include persistent volumes (metadata only)" />
      </Dlg>
      <Dlg open={dlg === "restore"} title="Restore" okLabel="Restore" onClose={() => setDlg(null)} err={err} onOk={restore}>
        <Field label="Target cluster"><Select value={f.target} aria-label="Target cluster" onChange={(_, d) => setF({ ...f, target: d.value })}>{(clusters.data || []).filter((c) => String(c.location).toLowerCase() === String(a.location).toLowerCase()).map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}</Select></Field>
        <Field label="Included namespaces" hint="Empty = every namespace in the recovery point"><Input aria-label="Restore included namespaces" value={f.includeNs} onChange={(_, d) => setF({ ...f, includeNs: d.value })} /></Field>
        <Field label="Conflict policy"><Select value={f.conflict} aria-label="Conflict policy" onChange={(_, d) => setF({ ...f, conflict: d.value })}><option value="Skip">Skip (keep existing objects)</option><option value="Patch">Patch (overwrite with the backup)</option></Select></Field>
        <Field label="Namespace mapping (from)"><Input aria-label="Mapping from" value={f.mapFrom} onChange={(_, d) => setF({ ...f, mapFrom: d.value })} /></Field>
        <Field label="Namespace mapping (to)"><Input aria-label="Mapping to" value={f.mapTo} onChange={(_, d) => setF({ ...f, mapTo: d.value })} /></Field>
      </Dlg>
    </>
  );
}

const iso = (d) => d.toISOString().replace(/\.\d+Z$/, "Z");

export function CosmosPitr({ a }) {
  const notify = useNotify();
  const loc = String(a.location).replace(/\s/g, "").toLowerCase();
  const accts = useAsync(async () => (await call("GET", `${sub()}/providers/Microsoft.DocumentDB/locations/${loc}/restorableDatabaseAccounts`, "2024-05-15")).value || [], [a.id]);
  const mine = (accts.data || []).find((x) => x.properties.accountName === a.name && !x.properties.deletionTime);
  const continuous = a.properties?.backupPolicy?.type === "Continuous";
  const [open, setOpen] = useState(null);
  const [f, setF] = useState({ name: "", time: "" });
  const [err, setErr] = useState(null);
  const restoreFrom = async (src) => {
    setErr(null);
    try {
      const r = await call("PUT", `/subscriptions/${getSubscription()}/resourceGroups/${a.resourceGroup}/providers/Microsoft.DocumentDB/databaseAccounts/${f.name}`, "2024-05-15", {
        location: a.location, kind: "GlobalDocumentDB",
        properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: a.location, failoverPriority: 0 }], backupPolicy: { type: "Continuous", continuousModeProperties: { tier: a.properties?.backupPolicy?.continuousModeProperties?.tier || "Continuous7Days" } }, createMode: "Restore", restoreParameters: { restoreMode: "PointInTime", restoreSource: src.id, restoreTimestampInUtc: f.time } },
      });
      notify.success(`Account '${r.name}' restored from ${f.time}.`, "Restore"); setOpen(null); accts.reload();
    } catch (e) { setErr(e); }
  };
  return (
    <>
      <h3 style={{ marginTop: 20 }}>Point in time restore</h3>
      {!continuous && <InfoBar title="Periodic backup mode">Point-in-time restore needs the Continuous backup policy. Periodic accounts take no snapshots in Vyomi, so there is nothing to restore from.</InfoBar>}
      {continuous && mine && <div style={{ display: "flex", gap: 32, margin: "8px 0" }}>
        <div><div style={{ fontSize: 12 }}>Oldest restorable time</div><div>{fmtDate(mine.properties.oldestRestorableTime)}</div></div>
        <div><div style={{ fontSize: 12 }}>Latest restorable time</div><div>now</div></div>
        <div><Button appearance="primary" onClick={() => { setErr(null); setF({ name: `${a.name}-restored`, time: iso(new Date(Date.now() - 1000)) }); setOpen(mine); }}>Restore to a new account</Button></div>
      </div>}
      <h4>Restorable accounts in {locationLabel(loc)}</h4>
      <table className="vy-grid" aria-label="Restorable accounts"><thead><tr><th>Account</th><th>Oldest restorable time</th><th>Deleted</th><th /></tr></thead><tbody>
        {(accts.data || []).length === 0 ? <tr><td colSpan={4} className="vy-muted">No continuous-backup accounts in this region.</td></tr>
          : accts.data.map((x) => <tr key={x.name}><td>{x.properties.accountName}</td><td>{fmtDate(x.properties.oldestRestorableTime)}</td><td>{x.properties.deletionTime ? fmtDate(x.properties.deletionTime) : "-"}</td>
            <td>{x.properties.deletionTime && <Button size="small" onClick={() => { setErr(null); setF({ name: `${x.properties.accountName}-restored`, time: iso(new Date(new Date(x.properties.deletionTime).getTime() - 1000)) }); setOpen(x); }}>Restore</Button>}</td></tr>)}
      </tbody></table>
      <p className="vy-muted" style={{ fontSize: 12 }}>Restore recreates databases, containers and throughput in a new account. Documents are not restored: the Cosmos data plane is one shared store with no per-account write-ahead log.</p>
      <Dlg open={!!open} title="Restore to a new account" okLabel="Restore" onClose={() => setOpen(null)} err={err} onOk={() => restoreFrom(open)}>
        <Field label="New account name" required><Input aria-label="New account name" value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} /></Field>
        <Field label="Restore point (UTC)" required hint="Between the oldest restorable time and now (or the deletion time)"><Input aria-label="Restore point" value={f.time} onChange={(_, d) => setF({ ...f, time: d.value })} /></Field>
      </Dlg>
    </>
  );
}

/** Cosmos "Restore" on the account list: pick a deleted (or live) continuous-backup account across regions and restore it to a NEW account. */
export function CosmosRestoreDialog({ open, onClose, onRestored }) {
  const notify = useNotify();
  const rows = useAsync(async () => {
    if (!open) return [];
    const out = await Promise.all(LOCATIONS.map(async ([id]) => { try { return (await call("GET", `${sub()}/providers/Microsoft.DocumentDB/locations/${id}/restorableDatabaseAccounts`, "2024-05-15")).value || []; } catch { return []; } }));
    return out.flat();
  }, [open]);
  const [sel, setSel] = useState(null);
  const [f, setF] = useState({ name: "", rg: "", time: "" });
  const [err, setErr] = useState(null);
  const pick = (x) => {
    setSel(x.name);
    const t = x.properties.deletionTime ? new Date(new Date(x.properties.deletionTime).getTime() - 1000) : new Date();
    setF({ name: `${x.properties.accountName}-restored`, rg: f.rg, time: iso(t) });
  };
  const restore = async () => {
    setErr(null);
    try {
      const x = rows.data.find((r) => r.name === sel);
      const loc = x.properties.location || x.location;
      const r = await call("PUT", `${sub()}/resourceGroups/${f.rg}/providers/Microsoft.DocumentDB/databaseAccounts/${f.name}`, "2024-05-15", {
        location: loc, kind: "GlobalDocumentDB",
        properties: { databaseAccountOfferType: "Standard", locations: [{ locationName: loc, failoverPriority: 0 }], backupPolicy: { type: "Continuous", continuousModeProperties: { tier: "Continuous7Days" } }, createMode: "Restore", restoreParameters: { restoreMode: "PointInTime", restoreSource: x.id, restoreTimestampInUtc: f.time } },
      });
      notify.success(`Account '${r.name}' restored.`, "Restore"); onRestored?.(); onClose();
    } catch (e) { setErr(e); }
  };
  return (
    <Dlg open={open} title="Restore Azure Cosmos DB account" okLabel="Restore" onClose={onClose} err={err} onOk={restore} busy={!sel || !f.name || !f.rg}>
      {rows.loading ? <Loading /> : (rows.data || []).length === 0 ? <p className="vy-muted">No continuous-backup accounts exist. Only accounts with the Continuous backup policy can be restored.</p> : (
        <>
          <table className="vy-grid" aria-label="Restorable Cosmos accounts"><thead><tr><th /><th>Account</th><th>Location</th><th>Deleted</th></tr></thead><tbody>
            {rows.data.map((r) => <tr key={r.id}><td><input type="radio" name="rcos" aria-label={`Select ${r.properties.accountName}`} checked={sel === r.name} onChange={() => pick(r)} /></td><td>{r.properties.accountName}</td><td>{locationLabel(r.properties.location || r.location)}</td><td>{r.properties.deletionTime ? fmtDate(r.properties.deletionTime) : "-"}</td></tr>)}
          </tbody></table>
          <Field label="New account name" required><Input aria-label="New account name" value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} /></Field>
          <Field label="Resource group" required><Input aria-label="Resource group" value={f.rg} onChange={(_, d) => setF({ ...f, rg: d.value })} /></Field>
          <Field label="Restore point (UTC)" required><Input aria-label="Restore point" value={f.time} onChange={(_, d) => setF({ ...f, time: d.value })} /></Field>
        </>)}
    </Dlg>
  );
}

export function RestoreDeletedStorage({ open, onClose, onRestored }) {
  const notify = useNotify();
  const rows = useAsync(async () => {
    if (!open) return [];
    const out = await Promise.all(LOCATIONS.map(async ([id]) => { try { return (await call("GET", `${sub()}/providers/Microsoft.Storage/locations/${id}/deletedAccounts`, "2023-01-01")).value || []; } catch { return []; } }));
    return out.flat();
  }, [open]);
  const [sel, setSel] = useState(null);
  const [err, setErr] = useState(null);
  const restore = async () => {
    setErr(null);
    try { const x = rows.data.find((r) => r.name === sel); await call("POST", `${sub()}/providers/Microsoft.Storage/locations/${x.properties.location}/deletedAccounts/${x.name}/restore`, "2023-01-01", {}); notify.success(`Storage account '${sel}' restored.`, "Restore"); onRestored?.(); onClose(); } catch (e) { setErr(e); }
  };
  return (
    <Dlg open={open} title="Restore deleted storage accounts" okLabel="Restore" onClose={onClose} err={err} onOk={restore} busy={!sel}>
      {rows.loading ? <Loading /> : (rows.data || []).length === 0 ? <p className="vy-muted">No storage accounts were deleted in the last 14 days.</p> : (
        <table className="vy-grid" aria-label="Deleted storage accounts"><thead><tr><th /><th>Name</th><th>Location</th><th>Deleted</th><th>Restorable until</th></tr></thead><tbody>
          {rows.data.map((r) => <tr key={r.id}><td><input type="radio" name="del" aria-label={`Select ${r.name}`} checked={sel === r.name} onChange={() => setSel(r.name)} /></td><td>{r.name}</td><td>{locationLabel(r.properties.location)}</td><td>{fmtDate(r.properties.deletionTime)}</td><td>{fmtDate(r.properties.restorableUntil)}</td></tr>)}
        </tbody></table>)}
    </Dlg>
  );
}

export function AppRestoreDialog({ open, onClose, backup, rg, name, sas, onDone, apps, slots }) {
  const notify = useNotify();
  const [f, setF] = useState({ site: "", slot: "", sas });
  const [err, setErr] = useState(null);
  const go = async () => {
    setErr(null);
    try {
      const props = { storageAccountUrl: f.sas, blobName: backup.properties.blobName, overwrite: true };
      if (f.site && f.site !== name) props.siteName = f.site;
      if (f.slot) props.targetSlot = f.slot;
      await call("POST", `${sub()}/resourceGroups/${rg}/providers/Microsoft.Web/sites/${name}/backups/${backup.properties.id}/restore`, "2023-12-01", { properties: props });
      notify.success(`Restored '${f.site || name}${f.slot ? "/" + f.slot : ""}' from ${backup.properties.blobName}.`, "Restore succeeded"); onDone?.(); onClose();
    } catch (e) { setErr(e); }
  };
  return (
    <Dlg open={open} title="Restore backup" okLabel="Restore" onClose={onClose} err={err} onOk={go}>
      <InfoBar title="Overwrites the target">The target app's configuration, app settings, connection strings and function code are replaced with the backup's.</InfoBar>
      <Field label="Container SAS URL" required><Input aria-label="Container SAS URL" value={f.sas} onChange={(_, d) => setF({ ...f, sas: d.value })} /></Field>
      <Field label="Restore to"><Select aria-label="Target app" value={f.site || name} onChange={(_, d) => setF({ ...f, site: d.value })}>{(apps || [name]).map((n) => <option key={n} value={n}>{n}{n === name ? " (this app)" : ""}</option>)}</Select></Field>
      <Field label="Deployment slot"><Select aria-label="Target slot" value={f.slot} onChange={(_, d) => setF({ ...f, slot: d.value })}><option value="">Production</option>{(slots || []).map((s) => <option key={s} value={s}>{s}</option>)}</Select></Field>
    </Dlg>
  );
}
