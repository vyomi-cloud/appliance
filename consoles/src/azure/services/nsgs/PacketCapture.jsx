/* Network Watcher packet capture: Microsoft.Network/networkWatchers/{nw}/packetCaptures (core/azure_pcap_core.py).
 * Shared by the VM blade (Help > Packet capture, target fixed) and the NSG blade's Network Watcher tools (target picked).
 * Real ARM create/start, stop, queryStatus and delete. The captured file is a libpcap .cap written to the
 * network-watcher-logs container of the chosen storage account. Honest scope (registry azure.nsgs.packet_capture): the
 * simulator has no packet data plane, so the file is rebuilt from the flows it really observes while a capture runs. */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Spinner, ToolbarButton,
} from "@fluentui/react-components";
import { Add20Regular, Stop20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { armType, getSubscription } from "../../kit/arm.js";
import * as ns from "../vnets/netsvc.js";

const V = "2023-11-01";
const VM = armType("Microsoft.Compute", "virtualMachines", "2023-09-01");
const same = (a, b) => String(a || "").toLowerCase() === String(b || "").toLowerCase();
const rgOf = ns.rgOf;
const pcPath = (nw, name, verb) => `${ns.NW.path(nw.rg, nw.name)}/packetCaptures${name ? `/${encodeURIComponent(name)}` : ""}${verb ? `/${verb}` : ""}`;

async function listCaptures(vmId) {
  const out = [];
  for (const nw of await ns.NW.list()) {
    const rg = rgOf(nw.id);
    const rows = (await restJson("GET", `${ns.NW.path(rg, nw.name)}/packetCaptures`, { query: { "api-version": V } })).value || [];
    for (const c of rows.filter((r) => !vmId || same(r.properties?.target, vmId))) {
      let st = {};
      try { st = await restJson("POST", pcPath({ rg, name: nw.name }, c.name, "queryStatus"), { query: { "api-version": V }, body: {} }); } catch { /* status best-effort */ }
      out.push({ ...c, nw: { rg, name: nw.name }, status: st });
    }
  }
  return out;
}

async function ensureWatcher(location) {
  let nw = (await ns.NW.list()).find((w) => same(w.location, location));
  if (!nw) {
    const rg = "NetworkWatcherRG";
    try { await restJson("PUT", `/subscriptions/${getSubscription()}/resourceGroups/${rg}`, { query: { "api-version": "2021-04-01" }, body: { location } }); } catch { /* exists */ }
    nw = await ns.NW.put(rg, `NetworkWatcher_${location}`, { location });
  }
  return { rg: rgOf(nw.id), name: nw.name };
}

const lastOf = (id) => String(id || "").split("/").pop();

export default function PacketCapturePanel({ vm }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => listCaptures(vm?.id), [vm?.id]);
  const [add, setAdd] = useState(false);
  const stop = async (sel) => {
    for (const c of sel) await restJson("POST", pcPath(c.nw, c.name, "stop"), { query: { "api-version": V }, body: {} });
    notify.success(`Stopped ${sel.length} packet capture(s).`, "Packet capture stopped");
    reload();
  };
  return (
    <CapabilityContainer id="azure.nsgs.packet_capture" title={vm ? `${vm.name} | Packet capture` : "Packet capture"}>
      <BrowseGrid
        resourceName="packet capture" rowKey={(r) => r.id} filterPlaceholder="Search packet captures"
        items={data || []} loading={loading} error={error} onRefresh={reload} csvName="packet-captures.csv"
        extraCommands={(sel) => <>
          <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Add</ToolbarButton>
          <ToolbarButton icon={<Stop20Regular />} disabled={!sel.length} onClick={() => stop(sel).catch((e) => notify.error(e, "Stop failed"))}>Stop</ToolbarButton>
        </>}
        onDelete={async (sel) => {
          for (const c of sel) await restJson("DELETE", pcPath(c.nw, c.name), { query: { "api-version": V } });
          notify.success(`Deleted ${sel.length} packet capture(s).`, "Delete succeeded"); reload();
        }}
        columns={[
          { key: "name", label: "Name" },
          { key: "status", label: "Status", value: (r) => r.status?.packetCaptureStatus || "-" },
          { key: "stop", label: "Stop reason", value: (r) => r.status?.stopReason || "" },
          { key: "target", label: "Target", value: (r) => lastOf(r.properties?.target) },
          { key: "pk", label: "Packets", value: (r) => r.status?.vyomiSummary?.packets ?? 0 },
          { key: "bytes", label: "Bytes", value: (r) => r.status?.vyomiSummary?.bytes ?? 0 },
          { key: "filters", label: "Filters", value: (r) => (r.properties?.filters || []).length },
          { key: "start", label: "Started", value: (r) => r.status?.captureStartTime || "" },
          { key: "path", label: "Capture file", value: (r) => r.properties?.storageLocation?.storagePath || r.properties?.storageLocation?.filePath || "" },
        ]}
      />
      <p className="vy-muted" style={{ fontSize: 12, marginTop: 8 }}>
        The capture file is a libpcap .cap in the network-watcher-logs container of the storage account. It is rebuilt from the flows Vyomi observes
        while the capture runs (header-only packets, no payload); denied flows are never captured.
      </p>
      {add && <CreateCapture vm={vm} onClose={() => setAdd(false)} onDone={reload} />}
    </CapabilityContainer>
  );
}

function CreateCapture({ vm, onClose, onDone }) {
  const notify = useNotify();
  const vms = useAsync(() => (vm ? Promise.resolve([vm]) : VM.list()), [vm?.id]);
  const storage = useAsync(() => ns.listStorage(), []);
  const [f, setF] = useState({ name: "", vm: "", storage: "", limit: 18000, bytes: 1073741824, perPacket: 0, proto: "Any", lip: "", rip: "", lport: "", rport: "" });
  const [busy, setBusy] = useState(false);
  const target = (vms.data || []).find((v) => v.id === (f.vm || vm?.id)) || (vms.data || [])[0];
  const stId = f.storage || storage.data?.[0]?.id || "";
  const go = async () => {
    setBusy(true);
    try {
      const nw = await ensureWatcher(String(target.location).toLowerCase());
      const flt = { protocol: f.proto, localIPAddress: f.lip, remoteIPAddress: f.rip, localPort: f.lport, remotePort: f.rport };
      const hasFilter = f.proto !== "Any" || f.lip || f.rip || f.lport || f.rport;
      await restJson("PUT", pcPath(nw, f.name), { query: { "api-version": V }, body: { properties: {
        target: target.id, bytesToCapturePerPacket: Number(f.perPacket), totalBytesPerSession: Number(f.bytes), timeLimitInSeconds: Number(f.limit),
        storageLocation: { storageId: stId }, filters: hasFilter ? [Object.fromEntries(Object.entries(flt).filter(([, v]) => v))] : [],
      } } });
      notify.success(`Packet capture '${f.name}' is running.`, "Packet capture started");
      onDone(); onClose();
    } catch (e) { notify.error(e, "Failed to start the packet capture"); } finally { setBusy(false); }
  };
  const set = (k) => (_, d) => setF({ ...f, [k]: d.value });
  return (
    <Dialog open onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Add packet capture">
        <DialogBody>
          <DialogTitle>Add packet capture</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 10, minWidth: 460 }}>
              <Field label="Packet capture name" required><Input value={f.name} onChange={set("name")} aria-label="Packet capture name" /></Field>
              {!vm && (
                <Field label="Target virtual machine" required>
                  <Select value={target?.id || ""} onChange={set("vm")} aria-label="Target virtual machine">{(vms.data || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</Select>
                </Field>
              )}
              <Field label="Storage account" required>
                {storage.loading ? <Spinner size="tiny" /> : <Select value={stId} onChange={set("storage")} aria-label="Storage account">{(storage.data || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>}
              </Field>
              <Field label="Maximum bytes per packet (0 = entire packet)"><Input type="number" min={0} value={String(f.perPacket)} onChange={set("perPacket")} aria-label="Bytes per packet" /></Field>
              <Field label="Maximum bytes per session"><Input type="number" min={1} value={String(f.bytes)} onChange={set("bytes")} aria-label="Bytes per session" /></Field>
              <Field label="Time limit (seconds, max 18000)"><Input type="number" min={1} max={18000} value={String(f.limit)} onChange={set("limit")} aria-label="Time limit" /></Field>
              <b style={{ fontSize: 13 }}>Filter (optional)</b>
              <Field label="Protocol"><Select value={f.proto} onChange={set("proto")} aria-label="Filter protocol"><option>Any</option><option>TCP</option><option>UDP</option></Select></Field>
              <Field label="Local IP address" hint="a;b, a-b or CIDR"><Input value={f.lip} onChange={set("lip")} aria-label="Local IP address" /></Field>
              <Field label="Local port" hint="80;443 or 8000-8100"><Input value={f.lport} onChange={set("lport")} aria-label="Local port" /></Field>
              <Field label="Remote IP address"><Input value={f.rip} onChange={set("rip")} aria-label="Remote IP address" /></Field>
              <Field label="Remote port"><Input value={f.rport} onChange={set("rport")} aria-label="Remote port" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || !f.name || !stId || !target} onClick={go}>Start</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
