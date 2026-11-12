/* Recovery Services vault blade: Overview, Backup items (back up now / restore / stop), Backup policies, Backup jobs, Replicated items
 * (Site Recovery: enable replication, test failover, failover, commit, re-protect), Site Recovery jobs, Properties. All native ARM
 * calls on Microsoft.RecoveryServices (core/azure_backup_core.py). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select, ToolbarButton, Switch } from "@fluentui/react-components";
import { ArrowClockwise20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { listResourceGroups, locationLabel, LOCATIONS, parseId } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Essentials, ErrorBar, Glyph, InfoBar, Loading, fmtDate } from "../../kit/common.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

export const MENU = [
  { id: "overview", label: "Overview" },
  { group: "Protected items", items: [{ id: "items", label: "Backup items" }, { id: "replicated", label: "Replicated items" }] },
  { group: "Manage", items: [{ id: "policies", label: "Backup policies" }, { id: "jobs", label: "Backup jobs" }, { id: "srjobs", label: "Site Recovery jobs" }] },
  { group: "Settings", items: [{ id: "properties", label: "Properties" }] },
];
const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const last = (id = "") => id.split("/").pop();
const sourceName = (it) => last(it.properties?.sourceResourceId || it.name);
const dailyPolicy = (days, kind = "vm") => ({
  backupManagementType: kind === "vm" ? "AzureIaasVM" : "AzureStorage", ...(kind === "vm" ? {} : { workLoadType: "AzureFileShare" }),
  schedulePolicy: { schedulePolicyType: "SimpleSchedulePolicy", scheduleRunFrequency: "Daily", scheduleRunTimes: ["2026-01-01T03:00:00Z"] },
  retentionPolicy: { retentionPolicyType: "LongTermRetentionPolicy", dailySchedule: { retentionTimes: ["2026-01-01T03:00:00Z"], retentionDuration: { count: days, durationType: "Days" } } },
});

function Dlg({ open, title, onClose, onOk, okLabel, children, err }) {
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label={title}><DialogBody>
        <DialogTitle>{title}</DialogTitle>
        <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}><ErrorBar error={err} title="Operation failed" />{children}</div></DialogContent>
        <DialogActions><Button appearance="primary" onClick={onOk}>{okLabel}</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}

export default function VaultBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const vault = useAsync(() => api.getVault(rg, name), [rg, name]);
  const self = `#/recoveryservices/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  let body;
  if (vault.loading && !vault.data) body = <Loading />;
  else if (vault.error) body = <><ErrorBar error={vault.error} title="Failed to load the vault" /><Link href="#/recoveryservices">Back to Recovery Services vaults</Link></>;
  else {
    const v = vault.data;
    body = { overview: () => <Overview v={v} self={self} />, items: () => <Items v={v} />, policies: () => <Policies v={v} />, jobs: () => <Jobs v={v} />,
      replicated: () => <Replicated v={v} />, srjobs: () => <SrJobs v={v} />, properties: () => <Properties v={v} reload={vault.reload} /> }[panel]?.() ?? null;
  }
  return (
    <ResourceBlade title={panel === "overview" ? name : `${name} | ${LABEL[panel] || panel}`} subtitle="Recovery Services vault" glyph={<Glyph id="recoveryservices" />} closeHref="#/recoveryservices"
      menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}>
      {body}
    </ResourceBlade>
  );
}

function Overview({ v, self }) {
  const sub = useSubscription();
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const items = useAsync(() => api.items(v), [v.id]);
  const rep = useAsync(() => api.replicated(v), [v.id]);
  const jobs = useAsync(() => api.jobs(v), [v.id]);
  const protectedN = (items.data || []).length;
  const failed = (jobs.data || []).filter((j) => /fail/i.test(j.properties?.status || "")).length;
  return (
    <>
      <div className="vy-cmdbar" role="toolbar" aria-label="Overview commands">
        <ToolbarButton icon={<Delete20Regular />} onClick={() => setDel(true)}>Delete</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={() => { items.reload(); rep.reload(); jobs.reload(); }}>Refresh</ToolbarButton>
      </div>
      <Essentials left={[["Resource group", v.resourceGroup], ["Location", locationLabel(v.location)], ["Subscription", sub.displayName || sub.id]]}
        right={[["SKU", `${v.sku?.name || "RS0"} (${v.sku?.tier || "Standard"})`], ["Provisioning state", v.properties?.provisioningState], ["Immutability", v.properties?.securitySettings?.immutabilitySettings?.state || "Disabled"]]} />
      <div style={{ display: "flex", gap: 24, margin: "16px 0", flexWrap: "wrap" }} data-testid="rsv-tiles">
        {[["Backup items", protectedN, "items"], ["Replicated items", (rep.data || []).length, "replicated"], ["Backup jobs", (jobs.data || []).length, "jobs"], ["Failed jobs", failed, "jobs"]].map(([l, n, p]) => (
          <div key={l} style={{ minWidth: 150 }}><div style={{ fontSize: 12 }}>{l}</div><div style={{ fontSize: 28 }}><Link href={`${self}/${p}`}>{n}</Link></div></div>))}
      </div>
      <InfoBar title="What is real">Recovery points write the VM/file-share configuration (and, for file shares, every file) as an artifact into the simulator's own Blob store. Disk block data is not captured, and Site Recovery replication has no lag (a second set of records, not a second region).</InfoBar>
      <DeleteDialog open={del} onClose={() => setDel(false)} resourceType="Recovery Services vault" names={[v.name]}
        onConfirm={async () => { await api.deleteVault(v.resourceGroup, v.name); notify.success(`Vault '${v.name}' was deleted.`, "Delete succeeded"); navigate("recoveryservices"); }} />
    </>
  );
}

function Items({ v }) {
  const notify = useNotify();
  const t = useAsync(() => api.items(v), [v.id]);
  const pol = useAsync(() => api.policies(v), [v.id]);
  const vms = useAsync(() => api.listVms(), [v.id]);
  const [enable, setEnable] = useState(false);
  const [f, setF] = useState({ vm: "", policy: "" });
  const [rs, setRs] = useState(null);
  const [err, setErr] = useState(null);
  const [rp, setRp] = useState([]);
  const [rf, setRf] = useState({ type: "OriginalLocation", rp: "", target: "", targetRg: "", storage: "", vnet: "" });
  const rgs = useAsync(() => listResourceGroups(), []);
  const open = async (it) => { setErr(null); setRs(it); const x = await api.recoveryPoints(it).catch(() => []); setRp(x); setRf((o) => ({ ...o, rp: x[0]?.name || "" })); };
  const doRestore = async () => {
    setErr(null);
    try {
      const subId = parseId(v.id).subscription;
      const rgId = (n) => `/subscriptions/${subId}/resourceGroups/${n}`;
      const p = rs.properties.protectedItemType === "AzureFileShareProtectedItem"
        ? { objectType: "AzureFileShareRestoreRequest", recoveryType: "OriginalLocation", restoreRequestType: "FullShareRestore", copyOptions: "CreateCopy" }
        : { objectType: "IaasVMRestoreRequest", recoveryType: rf.type,
            ...(rf.type === "RestoreDisks" ? { storageAccountId: rf.storage, targetResourceGroupId: rgId(rf.targetRg) } : {}),
            ...(rf.type === "AlternateLocation" ? { targetVirtualMachineId: `${rgId(rf.targetRg)}/providers/Microsoft.Compute/virtualMachines/${rf.target}`, targetResourceGroupId: rgId(rf.targetRg), virtualNetworkId: rf.vnet, subnetId: `${rf.vnet}/subnets/${rf.subnet || "default"}` } : {}) };
      await api.restore(rs, rf.rp, p);
      notify.success("Restore job triggered.", "Restore"); setRs(null);
    } catch (e) { setErr(e); }
  };
  return (
    <>
      <div className="vy-panel-title">Backup items</div>
      <BrowseGrid resourceName="backup item" rowKey={(r) => r.id} items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} onCreate={() => { setErr(null); setEnable(true); }}
        csvName="backup-items.csv"
        extraCommands={(sel) => <>
          <ToolbarButton disabled={sel.length !== 1} onClick={async () => { try { await api.backupNow(sel[0]); notify.success("Backup completed; a recovery point was created.", "Backup now"); t.reload(); } catch (e) { notify.error(e, "Backup failed"); } }}>Backup now</ToolbarButton>
          <ToolbarButton disabled={sel.length !== 1} onClick={() => open(sel[0])}>Restore</ToolbarButton></>}
        onDelete={async (sel) => { for (const s of sel) await api.stopProtection(s); notify.success("Protection stopped (soft-deleted for 14 days).", "Stop backup"); t.reload(); }}
        columns={[{ key: "n", label: "Backup item", value: (r) => sourceName(r) }, { key: "t", label: "Type", value: (r) => (r.properties?.protectedItemType === "AzureFileShareProtectedItem" ? "Azure Storage (Azure Files)" : "Azure Virtual Machine") },
          { key: "s", label: "Protection state", value: (r) => (r.properties?.isScheduledForDeferredDelete ? "Soft deleted" : r.properties?.protectionState) }, { key: "p", label: "Policy", value: (r) => last(r.properties?.policyId) },
          { key: "l", label: "Last backup", value: (r) => (r.properties?.lastBackupTime ? fmtDate(r.properties.lastBackupTime) : "--") }]}
        emptyAction={<Link as="button" onClick={() => setEnable(true)}>Enable backup</Link>} />
      <Dlg open={enable} title="Enable backup" okLabel="Enable backup" onClose={() => setEnable(false)} err={err}
        onOk={async () => { setErr(null); try { const vm = (vms.data || []).find((x) => x.id === f.vm); await api.protect(v, "vm", vm.id, parseId(vm.id).resourceGroup, vm.name, f.policy || (pol.data || [])[0]?.id); notify.success(`Backup enabled for ${vm.name}.`, "Enable backup"); setEnable(false); t.reload(); } catch (e) { setErr(e); } }}>
        <Field label="Virtual machine" required><Select value={f.vm} onChange={(_, d) => setF({ ...f, vm: d.value })} aria-label="Virtual machine"><option value="">Select a virtual machine</option>{(vms.data || []).map((x) => <option key={x.id} value={x.id}>{x.name} ({locationLabel(x.location)})</option>)}</Select></Field>
        <Field label="Backup policy" required><Select value={f.policy} onChange={(_, d) => setF({ ...f, policy: d.value })} aria-label="Backup policy">{(pol.data || []).filter((p) => p.properties?.backupManagementType === "AzureIaasVM").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
      </Dlg>
      <Dlg open={!!rs} title="Restore Virtual Machine" okLabel="Restore" onClose={() => setRs(null)} err={err} onOk={doRestore}>
        <Field label="Recovery point"><Select value={rf.rp} onChange={(_, d) => setRf({ ...rf, rp: d.value })} aria-label="Recovery point">{rp.map((x) => <option key={x.name} value={x.name}>{x.name} - {fmtDate(x.properties?.recoveryPointTime)}</option>)}</Select></Field>
        {rs?.properties?.protectedItemType !== "AzureFileShareProtectedItem" && <>
          <Field label="Restore configuration"><Select value={rf.type} onChange={(_, d) => setRf({ ...rf, type: d.value })} aria-label="Restore type"><option value="OriginalLocation">Replace existing</option><option value="AlternateLocation">Create new</option><option value="RestoreDisks">Restore disks</option></Select></Field>
          {rf.type !== "OriginalLocation" && <Field label="Target resource group"><Select value={rf.targetRg} onChange={(_, d) => setRf({ ...rf, targetRg: d.value })} aria-label="Target resource group"><option value="">Select</option>{(rgs.data || []).map((r) => <option key={r.name}>{r.name}</option>)}</Select></Field>}
          {rf.type === "AlternateLocation" && <><Field label="New virtual machine name"><Input value={rf.target} onChange={(_, d) => setRf({ ...rf, target: d.value })} aria-label="New virtual machine name" /></Field>
            <Field label="Virtual network ID"><Input value={rf.vnet} onChange={(_, d) => setRf({ ...rf, vnet: d.value })} aria-label="Virtual network ID" /></Field>
            <Field label="Subnet name"><Input value={rf.subnet || ""} placeholder="default" onChange={(_, d) => setRf({ ...rf, subnet: d.value })} aria-label="Subnet name" /></Field></>}
          {rf.type === "RestoreDisks" && <Field label="Staging storage account ID"><Input value={rf.storage} onChange={(_, d) => setRf({ ...rf, storage: d.value })} aria-label="Storage account ID" /></Field>}</>}
      </Dlg>
    </>
  );
}

function Policies({ v }) {
  const notify = useNotify();
  const t = useAsync(() => api.policies(v), [v.id]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", days: "30" });
  const [err, setErr] = useState(null);
  return (
    <>
      <div className="vy-panel-title">Backup policies</div>
      <BrowseGrid resourceName="backup policy" rowKey={(r) => r.id} items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} onCreate={() => { setErr(null); setOpen(true); }} csvName="backup-policies.csv"
        onDelete={async (sel) => { for (const s of sel) await api.deletePolicy(v, s.name); notify.success("Policy deleted.", "Delete succeeded"); t.reload(); }}
        columns={[{ key: "name", label: "Policy name" }, { key: "t", label: "Backup management type", value: (r) => r.properties?.backupManagementType }, { key: "f", label: "Frequency", value: (r) => r.properties?.schedulePolicy?.scheduleRunFrequency || "--" },
          { key: "r", label: "Daily retention", value: (r) => { const d = r.properties?.retentionPolicy?.dailySchedule?.retentionDuration; return d ? `${d.count} ${d.durationType}` : "--"; } }, { key: "i", label: "Protected items", value: (r) => r.properties?.protectedItemsCount ?? 0 }]} />
      <Dlg open={open} title="Create backup policy" okLabel="Create" onClose={() => setOpen(false)} err={err}
        onOk={async () => { setErr(null); try { await api.putPolicy(v, f.name, dailyPolicy(Number(f.days))); notify.success(`Policy '${f.name}' created.`, "Create policy"); setOpen(false); t.reload(); } catch (e) { setErr(e); } }}>
        <Field label="Policy name" required><Input value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} aria-label="Policy name" /></Field>
        <Field label="Daily backup retention (days)" hint="Azure VM backups keep daily points for 7-9999 days."><Input value={f.days} onChange={(_, d) => setF({ ...f, days: d.value })} aria-label="Retention days" /></Field>
      </Dlg>
    </>
  );
}

const jobCols = [{ key: "op", label: "Operation", value: (r) => r.properties?.operation }, { key: "st", label: "Status", value: (r) => r.properties?.status }, { key: "w", label: "Workload / item", value: (r) => r.properties?.entityFriendlyName || r.properties?.friendlyName },
  { key: "s", label: "Start time", value: (r) => fmtDate(r.properties?.startTime) }];
function Jobs({ v }) { const t = useAsync(() => api.jobs(v), [v.id]); return (<><div className="vy-panel-title">Backup jobs</div><BrowseGrid resourceName="job" rowKey={(r) => r.id} items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} columns={jobCols} csvName="backup-jobs.csv" /></>); }
function SrJobs({ v }) { const t = useAsync(() => api.rjobs(v), [v.id]); return (<><div className="vy-panel-title">Site Recovery jobs</div><BrowseGrid resourceName="job" rowKey={(r) => r.id} items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} columns={jobCols} csvName="site-recovery-jobs.csv" /></>); }

function Replicated({ v }) {
  const notify = useNotify();
  const t = useAsync(() => api.replicated(v), [v.id]);
  const vms = useAsync(() => api.listVms(), [v.id]);
  const vnets = useAsync(() => api.listVnets(), [v.id]);
  const rgs = useAsync(() => listResourceGroups(), []);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ vm: "", loc: "westus", rg: "" });
  const [err, setErr] = useState(null);
  const [fo, setFo] = useState(null);
  const [net, setNet] = useState("");
  const subId = parseId(v.id).subscription;
  const act = (it, a, label) => async () => { try { await api.rAction(it, a, a === "testFailover" || a === "unplannedFailover" ? net : undefined); notify.success(`${label} completed.`, label); t.reload(); } catch (e) { notify.error(e, `${label} failed`); } };
  return (
    <>
      <div className="vy-panel-title">Replicated items</div>
      <BrowseGrid resourceName="replicated item" rowKey={(r) => r.id} items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} onCreate={() => { setErr(null); setOpen(true); }} csvName="replicated-items.csv"
        extraCommands={(sel) => <>
          <ToolbarButton disabled={sel.length !== 1} onClick={() => { setNet(""); setFo({ it: sel[0], a: "testFailover", label: "Test failover" }); }}>Test failover</ToolbarButton>
          <ToolbarButton disabled={sel.length !== 1} onClick={act(sel[0], "testFailoverCleanup", "Cleanup test failover")}>Cleanup test failover</ToolbarButton>
          <ToolbarButton disabled={sel.length !== 1} onClick={() => { setNet(""); setFo({ it: sel[0], a: "unplannedFailover", label: "Failover" }); }}>Failover</ToolbarButton>
          <ToolbarButton disabled={sel.length !== 1} onClick={act(sel[0], "commit", "Commit")}>Commit</ToolbarButton>
          <ToolbarButton disabled={sel.length !== 1} onClick={act(sel[0], "reProtect", "Re-protect")}>Re-protect</ToolbarButton></>}
        onDelete={async (sel) => { for (const s of sel) await api.disableReplication(s); notify.success("Replication disabled.", "Disable replication"); t.reload(); }}
        columns={[{ key: "n", label: "Replicated item", value: (r) => r.properties?.friendlyName || r.name }, { key: "h", label: "Replication health", value: (r) => r.properties?.replicationHealth }, { key: "s", label: "Status", value: (r) => r.properties?.protectionState },
          { key: "a", label: "Active location", value: (r) => r.properties?.activeLocation || "Primary" }, { key: "tl", label: "Target region", value: (r) => locationLabel(r.properties?.providerSpecificDetails?.recoveryAzureLocation) }, { key: "fo", label: "Failover health", value: (r) => r.properties?.failoverHealth || "--" }]}
        emptyAction={<Link as="button" onClick={() => setOpen(true)}>Enable replication</Link>} />
      <Dlg open={open} title="Enable replication" okLabel="Enable replication" onClose={() => setOpen(false)} err={err}
        onOk={async () => { setErr(null); try { const vm = (vms.data || []).find((x) => x.id === f.vm); const fabric = vm.location;
          await api.putFabric(v, fabric, vm.location); await api.enableReplication(v, fabric, `${vm.name}-repl`, vm.id, f.loc, `/subscriptions/${subId}/resourceGroups/${f.rg}`);
          notify.success(`Replication enabled for ${vm.name}.`, "Enable replication"); setOpen(false); t.reload(); } catch (e) { setErr(e); } }}>
        <Field label="Source virtual machine" required><Select value={f.vm} onChange={(_, d) => setF({ ...f, vm: d.value })} aria-label="Source virtual machine"><option value="">Select</option>{(vms.data || []).map((x) => <option key={x.id} value={x.id}>{x.name} ({locationLabel(x.location)})</option>)}</Select></Field>
        <Field label="Target region" required><Select value={f.loc} onChange={(_, d) => setF({ ...f, loc: d.value })} aria-label="Target region">{LOCATIONS.map(([id, l]) => <option key={id} value={id}>{l}</option>)}</Select></Field>
        <Field label="Target resource group" required><Select value={f.rg} onChange={(_, d) => setF({ ...f, rg: d.value })} aria-label="Target resource group"><option value="">Select</option>{(rgs.data || []).map((r) => <option key={r.name}>{r.name}</option>)}</Select></Field>
      </Dlg>
      <Dlg open={!!fo} title={fo?.label} okLabel={fo?.label} onClose={() => setFo(null)} onOk={async () => { await act(fo.it, fo.a, fo.label)(); setFo(null); }}>
        <Field label="Azure virtual network" required hint="The replica VM is created on this network in the target region."><Select value={net} onChange={(_, d) => setNet(d.value)} aria-label="Azure virtual network"><option value="">Select</option>{(vnets.data || []).map((n) => <option key={n.id} value={n.id}>{n.name} ({locationLabel(n.location)})</option>)}</Select></Field>
      </Dlg>
    </>
  );
}

function Properties({ v, reload }) {
  const notify = useNotify();
  const cfg = useAsync(() => api.vaultConfig(v), [v.id]);
  const st = useAsync(() => api.storageConfig(v), [v.id]);
  const soft = (cfg.data?.softDeleteFeatureState || "Enabled") !== "Disabled";
  const imm = v.properties?.securitySettings?.immutabilitySettings?.state || "Disabled";
  return (
    <>
      <div className="vy-panel-title">Properties</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 520 }}>
        <Field label="Backup storage redundancy" hint="Can only change while the vault has no protected items.">
          <Select value={st.data?.storageModelType || "GeoRedundant"} aria-label="Backup storage redundancy" onChange={async (_, d) => { try { await api.putStorageConfig(v, { storageModelType: d.value }); notify.success("Storage redundancy updated.", "Backup configuration"); st.reload(); } catch (e) { notify.error(e, "Could not change redundancy"); } }}>
            {["GeoRedundant", "LocallyRedundant", "ZoneRedundant", "ReadAccessGeoZoneRedundant"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Switch label="Soft delete (14 days)" checked={soft} onChange={async (_, d) => { try { await api.putVaultConfig(v, { softDeleteFeatureState: d.checked ? "Enabled" : "Disabled" }); cfg.reload(); } catch (e) { notify.error(e, "Could not change soft delete"); } }} />
        <Field label="Immutability" hint="Locked cannot be relaxed again.">
          <Select value={imm} aria-label="Immutability" onChange={async (_, d) => { try { await api.createVault(v.resourceGroup, v.name, { location: v.location, properties: { securitySettings: { immutabilitySettings: { state: d.value } } } }); notify.success("Immutability updated.", "Vault properties"); reload(); } catch (e) { notify.error(e, "Could not change immutability"); } }}>
            {["Disabled", "Unlocked", "Locked"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
      </div>
    </>
  );
}
