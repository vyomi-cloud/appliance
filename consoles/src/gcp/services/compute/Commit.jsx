/* Committed use discounts, Capacity advisor, Migrate to Virtual Machines, TPUs, VM Manager inventory + reports
 * over core/gcp_commit_core + core/gcp_capacity_core + core/gcp_osconfig_core. Capacity is SIMULATED (no Google fleet data);
 * replication is record-only; TPU nodes are records (no accelerator). */
import { useEffect, useState } from "react";
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { fmtDate, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";
import { FormDialog, ListPage, ZONE_OPTS } from "./Ext.jsx";

const last = (v) => String(v || "").split("/").pop();
const REGION_OPTS = api.REGIONS.map(([v, l]) => [v, l]);
const usd = (n) => `$${Number(n || 0).toFixed(2)}`;
const COLORS = { ACTIVE: "success", READY: "success", SUCCEEDED: "success", FINALIZED: "success", CUTOVER: "success", HEALTHY: "success", RUNNING: "info", FIRST_SYNC: "info", CREATING: "info", PAUSED: "default", STOPPED: "default", EXPIRED: "default", FAILED: "error", UNAVAILABLE: "error", PARTIAL: "warning", AVAILABLE: "success", GUARANTEED: "success", HIGH_PROBABILITY: "success", LOW_PROBABILITY: "warning", ZONE_RESOURCE_POOL_EXHAUSTED: "error" };
const Chp = ({ s }) => <Chip size="small" label={s} color={COLORS[s] || "default"} />;
const Honest = ({ children }) => <Alert severity="info" sx={{ mb: 2 }}>{children}</Alert>;

/* ── Committed use discounts ───────────────────────────────────────────── */
export function CommittedUseDiscounts() {
  const { data: sav, reload } = useAsync(api.commitmentSavings, [useProject()]);
  return (
    <ListPage title="Committed use discounts" capId="gcp.compute.committed-use-discounts" resourceName="commitments" load={api.listCommitments}
      rowKey={(c) => c.selfLink} emptyText="No commitments. Purchase one to see utilisation against your running VMs."
      create={{ label: "Purchase commitment", fields: [
        { key: "name", label: "Name", required: true }, { key: "region", label: "Region", options: REGION_OPTS, default: api.DEFAULT_REGION },
        { key: "category", label: "Commitment type", options: [["MACHINE", "Resource-based (vCPU + memory)"], ["SPEND_BASED", "Spend-based (flexible)"]], default: "MACHINE" },
        { key: "plan", label: "Term", options: [["TWELVE_MONTH", "1 year"], ["THIRTY_SIX_MONTH", "3 years"]], default: "TWELVE_MONTH" },
        { key: "type", label: "Machine series", options: [["GENERAL_PURPOSE_E2", "E2"], ["GENERAL_PURPOSE_N2", "N2"], ["GENERAL_PURPOSE_N2D", "N2D"], ["GENERAL_PURPOSE", "N1"], ["COMPUTE_OPTIMIZED", "C2"], ["MEMORY_OPTIMIZED", "M1"]], default: "GENERAL_PURPOSE_E2", show: (v) => v.category === "MACHINE" },
        { key: "vcpu", label: "vCPUs", type: "number", default: 8, show: (v) => v.category === "MACHINE" },
        { key: "mem", label: "Memory (GB)", type: "number", default: 32, show: (v) => v.category === "MACHINE" },
        { key: "hourly", label: "Hourly commitment (USD)", type: "number", default: 1, show: (v) => v.category === "SPEND_BASED" },
      ], submit: async (v) => { await api.insertCommitment(v.region, v.category === "SPEND_BASED"
          ? { name: v.name, plan: v.plan, category: "SPEND_BASED", vyomiSpend: { hourlyCommitmentUsd: Number(v.hourly) } }
          : { name: v.name, plan: v.plan, type: v.type, resources: [{ type: "VCPU", amount: String(v.vcpu) }, { type: "MEMORY", amount: String(Math.round(Number(v.mem) * 1024)) }] }); reload(); },
        done: (v) => `Purchased commitment "${v.name}"` }}
      extraActions={() => null}
      columns={[
        { id: "n", header: "Name", sortField: "name", cell: (c) => c.name },
        { id: "st", header: "Status", cell: (c) => <Chp s={c.status} /> },
        { id: "r", header: "Region", cell: (c) => last(c.region) },
        { id: "t", header: "Type", cell: (c) => c.type },
        { id: "p", header: "Term", cell: (c) => (c.plan === "TWELVE_MONTH" ? "1 year" : "3 years") },
        { id: "c", header: "Committed", cell: (c) => (c.category === "SPEND_BASED" ? `${usd(c.vyomiSpend.hourlyCommitmentUsd)}/hour` : `${c.resources[0].amount} vCPU, ${(c.resources[1].amount / 1024).toFixed(0)} GB`) },
        { id: "u", header: "Utilisation", cell: (c) => `${c.vyomiUtilisation?.utilisationPercent ?? 0}%` },
        { id: "d", header: "Discount", cell: (c) => `${c.vyomiUtilisation?.discountPercent ?? "—"}%` },
        { id: "s", header: "Net savings / month", cell: (c) => usd(c.vyomiUtilisation?.netSavingsUsdPerMonth) },
        { id: "e", header: "Ends", cell: (c) => fmtDate(c.endTimestamp) },
      ]}>
      {() => sav && <Honest>Net savings across commitments: <b data-testid="cud-net">{usd(sav.netSavingsUsdPerMonth)}</b> per month, computed from your running VMs at GCP list prices (the cost meter). Commitments cannot be cancelled; nothing is billed.</Honest>}
    </ListPage>
  );
}

/* ── Capacity advisor ──────────────────────────────────────────────────── */
export function CapacityAdvisor() {
  const notify = useNotify();
  const project = useProject();
  const [region, setRegion] = useState(api.DEFAULT_REGION);
  const [mt, setMt] = useState("e2-standard-4");
  const [size, setSize] = useState(1);
  const [advice, setAdvice] = useState(null);
  const [pool, setPool] = useState(false);
  const { data = [], loading, error, reload } = useAsync(() => api.capacityPools(region), [project, region]);
  useEffect(() => { const t = setInterval(reload, 3000); return () => clearInterval(t); }, [reload]);
  const rows = data.filter((p) => p.usedVcpus > 0 || p.family === mt.split("-")[0]);
  const ask = async () => { try { setAdvice(await api.capacityAdvice(region, mt, size)); } catch (e) { notify.error?.(e.message); } };
  return (
    <Box sx={{ pt: 2 }}>
      <PageHeader title="Capacity advisor" actions={<>
        <Button onClick={() => setPool(true)}>Configure pool</Button>
        <Button startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <CapabilityContainer id="gcp.compute.capacity-advisor" title="Capacity advisor">
        <Honest>Simulated fleet, no Google fleet data. Tier 1 checks project quota, tier 2 looks for an unutilised reservation (guaranteed), tier 3 dry-runs an allocation on a simulated fleet of hosts whose background load fluctuates. Probing never consumes capacity; running VMs and reservations do draw from the zonal pools below, and a full pool fails VM starts with ZONE_RESOURCE_POOL_EXHAUSTED.</Honest>
        <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
          <TextField select size="small" label="Region" value={region} onChange={(e) => setRegion(e.target.value)} sx={{ minWidth: 220 }}>
            {REGION_OPTS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </TextField>
          <TextField size="small" label="Machine type" value={mt} onChange={(e) => setMt(e.target.value)} />
          <TextField size="small" label="VM count" type="number" value={size} onChange={(e) => setSize(e.target.value)} sx={{ width: 110 }} />
          <Button variant="contained" onClick={ask}>Check availability</Button>
        </Stack>
        {advice && (
          <Box sx={{ mb: 3 }} data-testid="advice">
            <Typography variant="subtitle1" sx={{ mb: 1 }}>Overall: <Chp s={advice.state} /> {advice.reason ? `(${advice.reason})` : `via ${advice.tier.toLowerCase()}`}</Typography>
            {advice.message && <Alert severity="error" sx={{ mb: 1 }}>{advice.message}</Alert>}
            <ResourceTable resourceName="zones" items={advice.recommendations} rowKey={(r) => r.zone} columns={[
              { id: "z", header: "Zone", cell: (r) => r.zone }, { id: "o", header: "State", cell: (r) => <Chp s={r.state} /> },
              { id: "t", header: "Tier", cell: (r) => r.tier }, { id: "n", header: "Obtainable VMs", cell: (r) => r.obtainableSize },
              { id: "b", header: "Background load", cell: (r) => (r.backgroundUtilisationPercent != null ? `${r.backgroundUtilisationPercent}%` : "-") },
              { id: "w", header: "Why", cell: (r) => r.reason }]} />
            {advice.alternativeShapes.length > 0 && <Typography variant="body2" sx={{ mt: 1 }}>Other shapes with the same vCPU count that still have room: {advice.alternativeShapes.map((a) => `${a.machineType} (${a.zone}, ${a.state})`).join(", ")}</Typography>}
            {advice.otherZonesInRegion.length > 0 && <Typography variant="body2">Other zones in the region with room: {advice.otherZonesInRegion.map((z) => `${z.zone} (${z.state})`).join(", ")}</Typography>}
          </Box>
        )}
        <Typography variant="subtitle1" sx={{ mb: 1 }}>Zonal capacity pools (live)</Typography>
        <ResourceTable resourceName="capacity pools" items={rows} loading={loading && !data.length} error={error} rowKey={(p) => `${p.zone}/${p.family}`} columns={[
          { id: "z", header: "Zone", sortField: "zone", cell: (p) => p.zone }, { id: "f", header: "Machine family", cell: (p) => p.family.toUpperCase() },
          { id: "l", header: "Pool (vCPUs)", cell: (p) => p.limitVcpus }, { id: "r", header: "Running", cell: (p) => p.runningVcpus },
          { id: "res", header: "Reserved", cell: (p) => p.reservedVcpus }, { id: "fr", header: "Free", cell: (p) => p.freeVcpus },
          { id: "u", header: "Utilisation", sortValue: (p) => p.utilisationPercent, cell: (p) => <Chip size="small" label={`${p.utilisationPercent}%`} color={p.utilisationPercent >= 100 ? "error" : p.utilisationPercent >= 80 ? "warning" : "success"} /> }]} />
      </CapabilityContainer>
      <FormDialog open={pool} title="Configure simulated capacity pool" onClose={() => setPool(false)} submitLabel="Apply" fields={[
        { key: "zone", label: "Zone", options: ZONE_OPTS, default: api.DEFAULT_ZONE }, { key: "family", label: "Machine family", options: ["e2", "n2", "n2d", "c2", "a2"].map((f) => [f, f]), default: "e2" },
        { key: "vcpus", label: "Pool size (vCPUs)", type: "number", default: 64 }]}
        onSubmit={async (v) => { await api.setCapacityPool(v.zone, v.family, v.vcpus); notify.success("Pool updated"); reload(); }} />
    </Box>
  );
}

/* ── Migrate to Virtual Machines ───────────────────────────────────────── */
const INV_HELP = "One VM per line: id,name,cpus,memoryMb,diskGb (e.g. vm-101,legacy-web,2,4096,20)";
const parseInv = (txt) => String(txt || "").split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [vmId, name, cpus, memoryMb, diskGb] = l.split(",").map((s) => s.trim()); return { vmId, name, cpus: Number(cpus || 2), memoryMb: Number(memoryMb || 4096), diskGb: Number(diskGb || 10) }; });

function MigrationDetail({ loc, src, vm, onClose }) {
  const notify = useNotify();
  const { data: cyc = [], reload: r1 } = useAsync(() => api.listCycles(loc, src, vm), [vm]);
  const { data: clones = [], reload: r2 } = useAsync(() => api.listVmmJobs(loc, src, vm, "cloneJobs"), [vm]);
  const { data: cuts = [], reload: r3 } = useAsync(() => api.listVmmJobs(loc, src, vm, "cutoverJobs"), [vm]);
  const run = (kind) => async () => { try { await api.createVmmJob(loc, src, vm, kind, `${kind === "cloneJobs" ? "clone" : "cutover"}-${Date.now().toString(36)}`); notify.success("Job completed"); r1(); r2(); r3(); } catch (e) { notify.error?.(e.message); } };
  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Migration {vm}</DialogTitle>
      <DialogContent>
        <Honest>Replication is record-only: cycles are tracked but no disk bytes are copied. Clone and cutover create a real Compute Engine instance from a stock image.</Honest>
        <Typography variant="subtitle2">Replication cycles</Typography>
        <ResourceTable resourceName="replication cycles" items={cyc} rowKey={(c) => c.name} columns={[
          { id: "n", header: "#", cell: (c) => c.cycleNumber }, { id: "s", header: "State", cell: (c) => <Chp s={c.state} /> },
          { id: "t", header: "Started", cell: (c) => fmtDate(c.startTime) }, { id: "p", header: "Progress", cell: (c) => `${c.progressPercent}%` }]} />
        <Stack direction="row" spacing={1} sx={{ my: 2 }}>
          <Button onClick={run("cloneJobs")}>Test clone</Button><Button variant="contained" onClick={run("cutoverJobs")}>Cut over</Button>
        </Stack>
        <Typography variant="subtitle2">Clone and cutover jobs</Typography>
        <ResourceTable resourceName="jobs" items={[...clones.map((j) => ({ ...j, kind: "Clone" })), ...cuts.map((j) => ({ ...j, kind: "Cutover" }))]} rowKey={(j) => j.name} columns={[
          { id: "k", header: "Type", cell: (j) => j.kind }, { id: "n", header: "Job", cell: (j) => last(j.name) }, { id: "s", header: "State", cell: (j) => <Chp s={j.state} /> },
          { id: "v", header: "Compute Engine VM", cell: (j) => j.computeEngineVmDetails?.vmName }]} />
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}

export function MigrateToVms() {
  const notify = useNotify();
  const project = useProject();
  const loc = "us-central1";
  const [tab, setTab] = useState("sources");
  const [src, setSrc] = useState("");
  const [detail, setDetail] = useState(null);
  const { data: sources = [], reload: rs } = useAsync(() => api.listVmmSources(loc), [project, tab]);
  useEffect(() => { if (!src && sources.length) setSrc(last(sources[0].name)); }, [sources, src]);
  const act = (fn, msg, reload) => async () => { try { await fn(); notify.success(msg); reload(); } catch (e) { notify.error?.(e.message); } };
  return (
    <Box sx={{ pt: 2 }}>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 1 }} aria-label="Migrate tabs">
        <Tab value="sources" label="Sources" /><Tab value="migrations" label="Migrations" />
      </Tabs>
      {tab === "sources" ? (
        <ListPage title="Migrate to Virtual Machines" capId="gcp.compute.migrate-to-vms" sectionTitle="Sources" resourceName="sources" load={() => api.listVmmSources(loc)} rowKey={(s) => s.name}
          deleteFn={(s) => api.deleteVmmSource(loc, last(s.name))} deleteTitle={() => "Delete source?"}
          extraActions={({ sel, reload }) => <Button disabled={sel.length !== 1} onClick={act(() => api.createVmmConnector(loc, last(sel[0]), `dc-${Date.now().toString(36)}`), "Datacenter connector deployed", reload)}>Add datacenter connector</Button>}
          create={{ label: "Add source", fields: [
            { key: "id", label: "Source ID", required: true }, { key: "kind", label: "Source type", options: [["vmware", "VMware vCenter"], ["aws", "AWS"], ["azure", "Azure"]], default: "vmware" },
            { key: "host", label: "vCenter IP / AWS region / Azure subscription", required: true }, { key: "user", label: "Username", default: "administrator" },
            { key: "inv", label: `Source VM inventory. ${INV_HELP}`, multiline: true, default: "vm-101,legacy-web,2,4096,20" }],
            submit: async (v) => { await api.createVmmSource(loc, v.id, { [v.kind]: v.kind === "vmware" ? { vcenterIp: v.host, username: v.user } : v.kind === "aws" ? { awsRegion: v.host } : { subscriptionId: v.host }, vyomiInventory: parseInv(v.inv) }); rs(); },
            done: (v) => `Added source "${v.id}"` }}
          columns={[
            { id: "n", header: "Source", cell: (s) => last(s.name) }, { id: "t", header: "Type", cell: (s) => (s.vmware ? "VMware" : s.aws ? "AWS" : "Azure") },
            { id: "i", header: "Declared VMs", cell: (s) => (s.vyomiInventory || []).length }, { id: "c", header: "Created", cell: (s) => fmtDate(s.createTime) }]}>
          {() => <Honest>Vyomi has no source hypervisors to scan: the VM inventory is what you declare on the source.</Honest>}
        </ListPage>
      ) : (
        <>
          <TextField select size="small" label="Source" value={src} onChange={(e) => setSrc(e.target.value)} sx={{ minWidth: 240, mb: 1 }}>
            {sources.map((s) => <MenuItem key={s.name} value={last(s.name)}>{last(s.name)}</MenuItem>)}
          </TextField>
          {src && <ListPage key={src} title="Migrating VMs" capId="gcp.compute.migrate-to-vms" sectionTitle="Migrating VMs" resourceName="migrating VMs" load={() => api.listMigratingVms(loc, src)} rowKey={(m) => m.name}
            deleteFn={(m) => api.deleteMigratingVm(loc, src, last(m.name))} deleteTitle={() => "Delete migration?"}
            extraActions={({ sel, data, reload }) => {
              const m = sel.length === 1 ? data.find((x) => x.name === sel[0]) : null;
              const v = (verb, msg) => act(() => api.migratingVmVerb(loc, src, last(m.name), verb), msg, reload);
              return <>
                <Button disabled={!m || m.state !== "READY"} onClick={m && v("startMigration", "Replication started")}>Start replication</Button>
                <Button disabled={!m || !["FIRST_SYNC", "ACTIVE"].includes(m.state)} onClick={m && v("pauseMigration", "Paused")}>Pause</Button>
                <Button disabled={!m || m.state !== "PAUSED"} onClick={m && v("resumeMigration", "Resumed")}>Resume</Button>
                <Button disabled={!m || m.state !== "CUTOVER"} onClick={m && v("finalizeMigration", "Finalized")}>Finalize</Button>
                <Button disabled={!m} onClick={() => setDetail(last(m.name))}>Cycles and jobs</Button>
              </>;
            }}
            create={{ label: "Add migration", fields: [
              { key: "id", label: "Migration ID", required: true }, { key: "vm", label: "Source VM ID", required: true },
              { key: "name", label: "Target VM name" }, { key: "zone", label: "Target zone", options: ZONE_OPTS, default: api.DEFAULT_ZONE }],
              submit: (v) => api.createMigratingVm(loc, src, v.id, { sourceVmId: v.vm, computeEngineTargetDefaults: { vmName: v.name || undefined, zone: v.zone } }),
              done: (v) => `Added migration "${v.id}"` }}
            columns={[
              { id: "n", header: "Migration", cell: (m) => last(m.name) }, { id: "v", header: "Source VM", cell: (m) => m.sourceVmId },
              { id: "s", header: "State", cell: (m) => <Chp s={m.state} /> }, { id: "t", header: "Target", cell: (m) => `${m.computeEngineTargetDefaults.vmName} (${m.computeEngineTargetDefaults.machineType})` },
              { id: "l", header: "Last sync", cell: (m) => (m.lastSync ? fmtDate(m.lastSync.lastSyncTime) : "—") }]} />}
          {detail && <MigrationDetail loc={loc} src={src} vm={detail} onClose={() => setDetail(null)} />}
        </>
      )}
    </Box>
  );
}

/* ── TPUs ──────────────────────────────────────────────────────────────── */
const TPU_ZONES = ["us-central1-b", "us-central1-a", "europe-west4-a", "asia-east1-c"];
export function Tpus() {
  const [zone, setZone] = useState("us-central1-b");
  const notify = useNotify();
  const { data: types = [] } = useAsync(() => api.listTpuTypes(zone), [zone]);
  const { data: rts = [] } = useAsync(() => api.listTpuRuntimes(zone), [zone]);
  return (
    <Box sx={{ pt: 0 }}>
      <TextField select size="small" label="Zone" value={zone} onChange={(e) => setZone(e.target.value)} sx={{ minWidth: 200, mt: 2, mb: 1 }}>
        {TPU_ZONES.map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
      </TextField>
      <ListPage key={zone} title="TPUs" capId="gcp.compute.tpus" resourceName="TPU nodes" load={() => api.listTpuNodes(zone)} rowKey={(n) => n.name}
        deleteFn={(n) => api.deleteTpuNode(zone, last(n.name))} deleteTitle={() => "Delete TPU node?"}
        extraActions={({ sel, data, reload }) => {
          const n = sel.length === 1 ? data.find((x) => x.name === sel[0]) : null;
          const go = (verb) => async () => { try { await api.tpuNodeVerb(zone, last(n.name), verb); notify.success(`TPU node ${verb} requested`); reload(); } catch (e) { notify.error?.(e.message); } };
          return <><Button disabled={!n || n.state !== "READY"} onClick={n && go("stop")}>Stop</Button><Button disabled={!n || n.state !== "STOPPED"} onClick={n && go("start")}>Start</Button></>;
        }}
        create={{ label: "Create TPU node", fields: [
          { key: "id", label: "Name", required: true }, { key: "at", label: "TPU type", options: types.map((t) => [last(t.name), last(t.name)]), default: last(types[0]?.name) || "v2-8" },
          { key: "rv", label: "Software version", options: rts.map((r) => [r.version, r.version]), default: "tpu-vm-tf-2.16.1" },
          { key: "spot", label: "Provisioning", options: [["false", "Standard"], ["true", "Spot"]], default: "false" }],
          submit: (v) => api.createTpuNode(zone, v.id, { acceleratorType: v.at, runtimeVersion: v.rv, schedulingConfig: { spot: v.spot === "true" } }), done: (v) => `Created TPU node "${v.id}"` }}
        columns={[
          { id: "n", header: "Name", cell: (n) => last(n.name) }, { id: "s", header: "State", cell: (n) => <Chp s={n.state} /> }, { id: "h", header: "Health", cell: (n) => <Chp s={n.health} /> },
          { id: "t", header: "TPU type", cell: (n) => n.acceleratorType }, { id: "r", header: "Software", cell: (n) => n.runtimeVersion },
          { id: "ip", header: "Internal IP", cell: (n) => n.networkEndpoints?.[0]?.ipAddress }, { id: "c", header: "Created", cell: (n) => fmtDate(n.createTime) }]}>
        {() => <Honest>Node records only: no accelerator exists in this simulator, so nothing can run on a TPU node. The state machine, catalogue and quota checks are real.</Honest>}
      </ListPage>
    </Box>
  );
}

/* ── VM Manager: Inventory + Reports ───────────────────────────────────── */
export function VmInventory() {
  return (
    <ListPage title="OS inventory" capId="gcp.compute.vm-manager" sectionTitle="OS inventory" resourceName="inventories" load={api.listInventories} rowKey={(i) => i.name}
      emptyText="No VM instances."
      columns={[
        { id: "n", header: "Instance", cell: (i) => i.name.split("/")[5] }, { id: "z", header: "Zone", cell: (i) => i.name.split("/")[3] },
        { id: "os", header: "Operating system", cell: (i) => i.osInfo?.longName || "—" }, { id: "k", header: "Kernel", cell: (i) => i.osInfo?.kernelVersion || "—" },
        { id: "p", header: "Packages", cell: (i) => (i.vyomiSource === "GUEST" ? i.packageCount : "n/a") },
        { id: "src", header: "Source", cell: (i) => <Chip size="small" label={i.vyomiSource === "GUEST" ? "Live guest" : "Image declared"} color={i.vyomiSource === "GUEST" ? "success" : "default"} /> },
        { id: "a", header: "Agent", cell: (i) => (i.agentEnabled ? "Enabled" : "Not enabled") }]}>
      {() => <Honest>Offline, a running VM is inspected inside its container (dpkg, rpm or apk). On Nano, or when the VM is stopped, only the OS declared by the boot image is shown.</Honest>}
    </ListPage>
  );
}

export function VmReports() {
  const project = useProject();
  const { data, loading, error } = useAsync(api.patchReport, [project]);
  const rows = data?.instances || [];
  return (
    <Box sx={{ pt: 2 }}>
      <PageHeader title="VM Manager reports" />
      <CapabilityContainer id="gcp.compute.vm-manager" title="Reports">
        {data && <Typography sx={{ mb: 2 }} data-testid="vmm-report-summary">{data.total} VMs, {data.withAgent} with the OS Config agent enabled, {data.patched} patched successfully, {data.policyAssignments} OS policy assignments.</Typography>}
        <ResourceTable resourceName="VM patch status" items={rows} loading={loading} error={error} rowKey={(r) => `${r.zone}/${r.instance}`} columns={[
          { id: "n", header: "Instance", cell: (r) => r.instance }, { id: "z", header: "Zone", cell: (r) => r.zone }, { id: "s", header: "Status", cell: (r) => r.status },
          { id: "a", header: "Agent", cell: (r) => (r.agentEnabled ? "Enabled" : "Not enabled") },
          { id: "l", header: "Last patch", cell: (r) => (r.lastPatch ? <Chp s={r.lastPatch.state} /> : "Never") }]} />
      </CapabilityContainer>
    </Box>
  );
}
