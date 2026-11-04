/* Network Watcher diagnostics reached from this NSG's "Diagnose and solve problems" blade
 * (the real portal's layout): IP flow verify, Next hop, VM connectivity issue (Connection
 * troubleshoot) and Network configuration diagnostics, all answered by the shared netsim
 * evaluator (core/azure_arm_core.py _network_watcher) through the real ARM actions
 * Microsoft.Network/networkWatchers/{nw}/ipFlowVerify|nextHop|connectivityCheck|
 * queryNetworkConfigurationDiagnostic — core/capabilities/azure/nsgs.json
 * azure.nsgs.network_watcher. All four tools pick from every VM in the subscription, same as
 * the real Network Watcher picker (it isn't scoped to this one NSG). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Radio, RadioGroup, Select, Spinner } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const vmNicIds = (vm) => (vm.properties?.networkProfile?.networkInterfaces || []).map((n) => n.id);
const nicById = (nics, id) => nics.find((n) => n.id.toLowerCase() === String(id || "").toLowerCase());
const nicIp = (nic) => nic?.properties?.ipConfigurations?.[0]?.properties?.privateIPAddress || "";

/** Shared VM/NIC picker state: choosing a VM resets to its first NIC and fills the IP field. */
function useTargetPicker(vms, nics, ipField) {
  const [vmId, setVmId] = useState("");
  const [nicId, setNicId] = useState("");
  const [fields, setFields] = useState({});
  const vm = (vms || []).find((v) => v.id === vmId);
  const vmNics = vm ? vmNicIds(vm) : [];
  const pickVm = (id) => {
    setVmId(id);
    const v = (vms || []).find((x) => x.id === id);
    const firstNic = v ? vmNicIds(v)[0] : "";
    setNicId(firstNic || "");
    setFields((f) => ({ ...f, [ipField]: nicIp(nicById(nics || [], firstNic)) }));
  };
  const pickNic = (id) => { setNicId(id); setFields((f) => ({ ...f, [ipField]: nicIp(nicById(nics || [], id)) })); };
  return { vm, vmId, pickVm, nicId, pickNic, vmNics, fields, setFields };
}

function IpFlowVerifyDialog({ open, onClose, vms, nics }) {
  const notify = useNotify();
  const p = useTargetPicker(vms, nics, "localIPAddress");
  const [direction, setDirection] = useState("Inbound");
  const [protocol, setProtocol] = useState("TCP");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const f = { localIPAddress: "", localPort: "", remoteIPAddress: "", remotePort: "", ...p.fields };
  const valid = p.vmId && p.nicId && f.localIPAddress && f.localPort && f.remoteIPAddress && f.remotePort;
  const run = async () => {
    setBusy(true); setResult(null);
    try {
      const r = await api.ipFlowVerify(p.vm.location, {
        targetResourceId: p.vmId, targetNicResourceId: p.nicId, direction, protocol,
        localPort: f.localPort, remotePort: f.remotePort, localIPAddress: f.localIPAddress, remoteIPAddress: f.remoteIPAddress,
      });
      setResult(r);
    } catch (e) { notify.error(e, "IP flow verify failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="IP flow verify">
        <DialogBody>
          <DialogTitle>IP flow verify</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 420 }}>
              <Field label="Virtual machine" required>
                <Select value={p.vmId} onChange={(_, d) => p.pickVm(d.value)} aria-label="Virtual machine">
                  <option value="">Select a virtual machine</option>
                  {(vms || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </Select>
              </Field>
              {p.vmNics.length > 1 && (
                <Field label="Network interface" required>
                  <Select value={p.nicId} onChange={(_, d) => p.pickNic(d.value)} aria-label="Network interface">
                    {p.vmNics.map((id) => <option key={id} value={id}>{nicById(nics, id)?.name || id}</option>)}
                  </Select>
                </Field>
              )}
              <Field label="Protocol"><RadioGroup layout="horizontal" value={protocol} onChange={(_, d) => setProtocol(d.value)} aria-label="Protocol">
                <Radio value="TCP" label="TCP" /><Radio value="UDP" label="UDP" />
              </RadioGroup></Field>
              <Field label="Direction"><RadioGroup layout="horizontal" value={direction} onChange={(_, d) => setDirection(d.value)} aria-label="Direction">
                <Radio value="Inbound" label="Inbound" /><Radio value="Outbound" label="Outbound" />
              </RadioGroup></Field>
              <Field label="Local IP address" required><Input value={f.localIPAddress} onChange={(_, d) => p.setFields({ ...f, localIPAddress: d.value })} aria-label="Local IP address" /></Field>
              <Field label="Local port" required><Input value={f.localPort} onChange={(_, d) => p.setFields({ ...f, localPort: d.value })} aria-label="Local port" /></Field>
              <Field label="Remote IP address" required><Input value={f.remoteIPAddress} onChange={(_, d) => p.setFields({ ...f, remoteIPAddress: d.value })} aria-label="Remote IP address" /></Field>
              <Field label="Remote port" required><Input value={f.remotePort} onChange={(_, d) => p.setFields({ ...f, remotePort: d.value })} aria-label="Remote port" /></Field>
              {busy && <Spinner size="tiny" label="Checking…" />}
              {result && (
                <section className="vy-section">
                  <b>Access: {result.access}</b>
                  {result.ruleName && <div>Security rule: {result.ruleName}</div>}
                </section>
              )}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={run}>Check</Button>
            <Button onClick={onClose}>Close</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function NextHopDialog({ open, onClose, vms, nics }) {
  const notify = useNotify();
  const p = useTargetPicker(vms, nics, "sourceIPAddress");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const f = { sourceIPAddress: "", destinationIPAddress: "", ...p.fields };
  const valid = p.vmId && p.nicId && f.sourceIPAddress && f.destinationIPAddress;
  const run = async () => {
    setBusy(true); setResult(null);
    try {
      const r = await api.nextHop(p.vm.location, {
        targetResourceId: p.vmId, targetNicResourceId: p.nicId,
        sourceIPAddress: f.sourceIPAddress, destinationIPAddress: f.destinationIPAddress,
      });
      setResult(r);
    } catch (e) { notify.error(e, "Next hop failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Next hop">
        <DialogBody>
          <DialogTitle>Next hop</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 420 }}>
              <Field label="Virtual machine" required>
                <Select value={p.vmId} onChange={(_, d) => p.pickVm(d.value)} aria-label="Virtual machine">
                  <option value="">Select a virtual machine</option>
                  {(vms || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </Select>
              </Field>
              {p.vmNics.length > 1 && (
                <Field label="Network interface" required>
                  <Select value={p.nicId} onChange={(_, d) => p.pickNic(d.value)} aria-label="Network interface">
                    {p.vmNics.map((id) => <option key={id} value={id}>{nicById(nics, id)?.name || id}</option>)}
                  </Select>
                </Field>
              )}
              <Field label="Source IP address" required><Input value={f.sourceIPAddress} onChange={(_, d) => p.setFields({ ...f, sourceIPAddress: d.value })} aria-label="Source IP address" /></Field>
              <Field label="Destination IP address" required><Input value={f.destinationIPAddress} onChange={(_, d) => p.setFields({ ...f, destinationIPAddress: d.value })} aria-label="Destination IP address" /></Field>
              {busy && <Spinner size="tiny" label="Checking…" />}
              {result && (
                <section className="vy-section">
                  <b>Next hop type: {result.nextHopType}</b>
                  {result.nextHopIpAddress && <div>Next hop IP address: {result.nextHopIpAddress}</div>}
                  <div>Route table ID: {result.routeTableId}</div>
                </section>
              )}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={run}>Next hop</Button>
            <Button onClick={onClose}>Close</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

/* VM connectivity issue: real Azure's source/destination connectivity check, answered by the
 * same netsim `reach()` evaluator the AWS Reachability Analyzer / GCP Connectivity Tests
 * analyzers use — see core/azure_arm_core.py _nw_connectivity_check. The real portal calls
 * this tile "VM connectivity issue" from the NSG's Diagnose and solve problems blade and
 * "Connection troubleshoot" from a standalone Network Watcher/vnet menu item; same action. */
function VmConnectivityDialog({ open, onClose, vms }) {
  const notify = useNotify();
  const [srcVmId, setSrcVmId] = useState("");
  const [destMode, setDestMode] = useState("resource");
  const [destVmId, setDestVmId] = useState("");
  const [address, setAddress] = useState("");
  const [port, setPort] = useState("80");
  const [protocol, setProtocol] = useState("TCP");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const srcVm = (vms || []).find((v) => v.id === srcVmId);
  const valid = srcVmId && port && (destMode === "resource" ? destVmId : address);
  const run = async () => {
    setBusy(true); setResult(null);
    try {
      const destination = destMode === "resource" ? { resourceId: destVmId, port: Number(port) } : { address, port: Number(port) };
      const r = await api.connectivityCheck(srcVm.location, { source: { resourceId: srcVmId }, destination, protocol });
      setResult(r);
    } catch (e) { notify.error(e, "VM connectivity issue check failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="VM connectivity issue">
        <DialogBody>
          <DialogTitle>VM connectivity issue</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 420 }}>
              <Field label="Source" required>
                <Select value={srcVmId} onChange={(_, d) => setSrcVmId(d.value)} aria-label="Source virtual machine">
                  <option value="">Select a virtual machine</option>
                  {(vms || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </Select>
              </Field>
              <Field label="Destination"><RadioGroup layout="horizontal" value={destMode} onChange={(_, d) => setDestMode(d.value)} aria-label="Destination">
                <Radio value="resource" label="Resource" /><Radio value="manual" label="Manual" />
              </RadioGroup></Field>
              {destMode === "resource" ? (
                <Field label="Destination resource" required>
                  <Select value={destVmId} onChange={(_, d) => setDestVmId(d.value)} aria-label="Destination virtual machine">
                    <option value="">Select a virtual machine</option>
                    {(vms || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                  </Select>
                </Field>
              ) : (
                <Field label="Destination IP address" required><Input value={address} onChange={(_, d) => setAddress(d.value)} aria-label="Destination IP address" /></Field>
              )}
              <Field label="Destination port" required><Input value={port} onChange={(_, d) => setPort(d.value)} aria-label="Destination port" /></Field>
              <Field label="Protocol"><RadioGroup layout="horizontal" value={protocol} onChange={(_, d) => setProtocol(d.value)} aria-label="Protocol">
                <Radio value="TCP" label="TCP" /><Radio value="UDP" label="UDP" />
              </RadioGroup></Field>
              {busy && <Spinner size="tiny" label="Checking…" />}
              {result && (
                <section className="vy-section">
                  <b>{result.connectionStatus}</b>
                  <div>Probes sent: {result.probesSent}, failed: {result.probesFailed}</div>
                  {result.hops?.length > 0 && (
                    <ul>{result.hops.map((h, i) => (
                      <li key={i}>{h.type}: {h.id}{h.issues?.length ? ` — ${h.issues[0].context?.[0]?.value}` : ""}</li>
                    ))}</ul>
                  )}
                </section>
              )}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={run}>Check</Button>
            <Button onClick={onClose}>Close</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

/* Network configuration diagnostics: real Azure's rule-by-rule trace — unlike IP flow verify
 * (one combined verdict), it reports EVERY network security group evaluated on the path (the
 * NIC's own NSG and/or its subnet's) with the rule that matched each — answered by the same
 * netsim `_layers` pass, see core/azure_arm_core.py _nw_config_diagnostic. */
function NetworkConfigDiagnosticDialog({ open, onClose, vms, nics }) {
  const notify = useNotify();
  const p = useTargetPicker(vms, nics, "sourceIPAddress");
  const [direction, setDirection] = useState("Inbound");
  const [protocol, setProtocol] = useState("TCP");
  const [destAddress, setDestAddress] = useState("");
  const [destPort, setDestPort] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const f = { sourceIPAddress: "", ...p.fields };
  const valid = p.vmId && p.nicId && destAddress && destPort;
  const run = async () => {
    setBusy(true); setResult(null);
    try {
      const profile = direction === "Inbound"
        ? { direction, protocol, source: destAddress, destination: f.sourceIPAddress, destinationPort: destPort }
        : { direction, protocol, source: f.sourceIPAddress, destination: destAddress, destinationPort: destPort };
      const r = await api.queryNetworkConfigurationDiagnostic(p.vm.location, {
        targetResourceId: p.vmId, targetNicResourceId: p.nicId, profiles: [profile],
      });
      setResult(r.results?.[0]);
    } catch (e) { notify.error(e, "Network configuration diagnostics failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Network configuration diagnostics">
        <DialogBody>
          <DialogTitle>Network configuration diagnostics</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 460 }}>
              <Field label="Virtual machine" required>
                <Select value={p.vmId} onChange={(_, d) => p.pickVm(d.value)} aria-label="Virtual machine">
                  <option value="">Select a virtual machine</option>
                  {(vms || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
                </Select>
              </Field>
              {p.vmNics.length > 1 && (
                <Field label="Network interface" required>
                  <Select value={p.nicId} onChange={(_, d) => p.pickNic(d.value)} aria-label="Network interface">
                    {p.vmNics.map((id) => <option key={id} value={id}>{nicById(nics, id)?.name || id}</option>)}
                  </Select>
                </Field>
              )}
              <Field label="Direction"><RadioGroup layout="horizontal" value={direction} onChange={(_, d) => setDirection(d.value)} aria-label="Direction">
                <Radio value="Inbound" label="Inbound" /><Radio value="Outbound" label="Outbound" />
              </RadioGroup></Field>
              <Field label="Protocol"><RadioGroup layout="horizontal" value={protocol} onChange={(_, d) => setProtocol(d.value)} aria-label="Protocol">
                <Radio value="TCP" label="TCP" /><Radio value="UDP" label="UDP" />
              </RadioGroup></Field>
              <Field label={direction === "Inbound" ? "Source IP address" : "Destination IP address"} required>
                <Input value={destAddress} onChange={(_, d) => setDestAddress(d.value)} aria-label="Remote IP address" />
              </Field>
              <Field label="Destination port" required><Input value={destPort} onChange={(_, d) => setDestPort(d.value)} aria-label="Destination port" /></Field>
              {busy && <Spinner size="tiny" label="Checking…" />}
              {result && (
                <section className="vy-section">
                  <b>Access: {result.networkSecurityGroupResult.securityRuleAccessResult}</b>
                  <ul>
                    {result.networkSecurityGroupResult.evaluatedNetworkSecurityGroups.map((g, i) => (
                      <li key={i}>{g.appliedTo === "networkInterface" ? "Network interface NSG" : "Subnet NSG"}: {g.matchedRule.action} — {g.matchedRule.name}</li>
                    ))}
                    {!result.networkSecurityGroupResult.evaluatedNetworkSecurityGroups.length && <li>No network security group applies to this interface.</li>}
                  </ul>
                </section>
              )}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={run}>Check</Button>
            <Button onClick={onClose}>Close</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

/** "Diagnose and solve problems" panel content: all four Network Watcher diagnostic tiles —
 *  see azure.nsgs.network_watcher. */
export default function NetworkWatcherTools() {
  const vms = useAsync(() => api.listVmsForDiagnostics(), []);
  const nics = useAsync(() => api.listNics(), []);
  const [tool, setTool] = useState(null);
  const loading = vms.loading || nics.loading;
  return (
    <CapabilityContainer id="azure.nsgs.network_watcher" title="Network Watcher">
      <p style={{ fontSize: 13, marginTop: 0 }}>Diagnostic tools that check IP connectivity and routing against this subscription's live network configuration.</p>
      {loading ? <Spinner size="tiny" /> : !vms.data?.length ? (
        <p>No virtual machines found. Create a virtual machine first to use these diagnostic tools.</p>
      ) : (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Button onClick={() => setTool("flow")}>IP flow verify</Button>
          <Button onClick={() => setTool("hop")}>Next hop</Button>
          <Button onClick={() => setTool("vmconn")}>VM connectivity issue</Button>
          <Button onClick={() => setTool("ncd")}>Network configuration diagnostics</Button>
        </div>
      )}
      <IpFlowVerifyDialog open={tool === "flow"} onClose={() => setTool(null)} vms={vms.data} nics={nics.data} />
      <NextHopDialog open={tool === "hop"} onClose={() => setTool(null)} vms={vms.data} nics={nics.data} />
      <VmConnectivityDialog open={tool === "vmconn"} onClose={() => setTool(null)} vms={vms.data} />
      <NetworkConfigDiagnosticDialog open={tool === "ncd"} onClose={() => setTool(null)} vms={vms.data} nics={nics.data} />
    </CapabilityContainer>
  );
}
