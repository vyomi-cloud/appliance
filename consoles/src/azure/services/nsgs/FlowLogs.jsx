/* NSG flow logs: Microsoft.Network/networkWatchers/{nw}/flowLogs targeting this NSG (core/azure_netsvc_core.py).
 * Real ARM resource with real validation; no flow tuples are produced (no packet-level data plane). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, ToolbarButton, Checkbox } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as ns from "../vnets/netsvc.js";
import { armType } from "../../kit/arm.js";

const WS = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");

export default function FlowLogsPanel({ a }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => ns.listFlowLogs(a.id), [a.id]);
  const [add, setAdd] = useState(false);
  return (
    <CapabilityContainer id="azure.nsgs.flow_logs" title={`${a.name} | NSG flow logs`}>
      <BrowseGrid
        resourceName="flow log" rowKey={(r) => r.id} filterPlaceholder="Search flow logs"
        items={data || []} loading={loading} error={error} onRefresh={reload} csvName="flow-logs.csv"
        extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create</ToolbarButton>}
        onDelete={async (sel) => { for (const r of sel) await ns.deleteFlowLog(r); notify.success(`Deleted ${sel.length} flow log(s).`, "Delete succeeded"); reload(); }}
        columns={[
          { key: "name", label: "Flow log name" },
          { key: "enabled", label: "Status", value: (r) => (r.properties?.enabled ? "Enabled" : "Disabled") },
          { key: "storage", label: "Storage account", value: (r) => (r.properties?.storageId || "").split("/").pop() },
          { key: "retention", label: "Retention (days)", value: (r) => r.properties?.retentionPolicy?.days ?? 0 },
          { key: "version", label: "Version", value: (r) => r.properties?.format?.version },
          { key: "ta", label: "Traffic Analytics", value: (r) => (r.properties?.flowAnalyticsConfiguration?.networkWatcherFlowAnalyticsConfiguration?.enabled ? "Enabled" : "Disabled") },
          { key: "nw", label: "Network Watcher", value: (r) => r.networkWatcher },
        ]}
      />
      {add && <CreateFlowLog a={a} onClose={() => setAdd(false)} onDone={reload} />}
    </CapabilityContainer>
  );
}

function CreateFlowLog({ a, onClose, onDone }) {
  const notify = useNotify();
  const storage = useAsync(() => ns.listStorage(), []);
  const workspaces = useAsync(() => WS.list(), []);
  const [f, setF] = useState({ name: `${a.name}-flowlog`, storage: "", days: 7, version: 2, ta: false, ws: "", interval: 10 });
  const [busy, setBusy] = useState(false);
  const stId = f.storage || storage.data?.[0]?.id || "";
  const wsId = f.ws || workspaces.data?.[0]?.id || "";
  const go = async () => {
    setBusy(true);
    try {
      const props = { storageId: stId, enabled: true, retentionPolicy: { days: Number(f.days), enabled: Number(f.days) > 0 }, format: { type: "JSON", version: Number(f.version) } };
      if (f.ta) props.flowAnalyticsConfiguration = { networkWatcherFlowAnalyticsConfiguration: { enabled: true, workspaceResourceId: wsId, trafficAnalyticsInterval: Number(f.interval) } };
      await ns.putFlowLog(a, f.name, props);
      notify.success(`Flow log '${f.name}' was created.`, "Flow log created");
      onDone(); onClose();
    } catch (e) { notify.error(e, "Failed to create flow log"); } finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create a flow log">
        <DialogBody>
          <DialogTitle>Create a flow log</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Flow log name" required><Input value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} aria-label="Flow log name" /></Field>
              <Field label="Storage account" required>
                <Select value={stId} onChange={(_, d) => setF({ ...f, storage: d.value })} aria-label="Storage account">{(storage.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
              </Field>
              <Field label="Retention (days)" hint="0 keeps logs forever"><Input type="number" min={0} max={365} value={String(f.days)} onChange={(_, d) => setF({ ...f, days: d.value })} aria-label="Retention days" /></Field>
              <Field label="Flow Logs version"><Select value={String(f.version)} onChange={(_, d) => setF({ ...f, version: d.value })} aria-label="Flow Logs version"><option value="1">Version 1</option><option value="2">Version 2</option></Select></Field>
              <Checkbox checked={f.ta} onChange={(_, d) => setF({ ...f, ta: !!d.checked })} label="Enable Traffic Analytics" />
              {f.ta && <>
                <Field label="Log Analytics workspace"><Select value={wsId} onChange={(_, d) => setF({ ...f, ws: d.value })} aria-label="Log Analytics workspace">{(workspaces.data || []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</Select></Field>
                <Field label="Processing interval"><Select value={String(f.interval)} onChange={(_, d) => setF({ ...f, interval: d.value })} aria-label="Processing interval"><option value="10">Every 10 mins</option><option value="60">Every 1 hour</option></Select></Field>
              </>}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || !f.name || !stId} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
