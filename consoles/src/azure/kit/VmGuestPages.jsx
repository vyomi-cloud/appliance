/* VM Boot diagnostics, Serial console and Bastion connect.
 *   Boot diagnostics -> ARM retrieveBootDiagnosticsData (serial log + screenshot blobs, core/azure_dpbackup_core.py). On the offline appliance the
 *                       serial log is the container's real dmesg (GET /api/azure/vm/{id}/serial-console); the screenshot is an honest placeholder.
 *   Serial console   -> the appliance's docker-exec shell for the guest (/api/console/azurevm/instances/{id}/exec). Needs an instance runtime: on
 *                       Nano the panel says so instead of faking a terminal.
 *   Bastion          -> a Bastion host must exist in the VM's virtual network; POST /api/azure/vm/{id}/bastion/connect records the session and returns the ssh command. */
import { useEffect, useRef, useState } from "react";
import { Button, Field, Input, Link, Select, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { getSubscription, parseId } from "./arm.js";
import { ErrorBar, InfoBar, Loading } from "./common.jsx";
import { CapabilityContainer } from "./Capability.jsx";

async function host(path, init) {
  const r = await fetch(path, init);
  const t = await r.text();
  let j = null; try { j = JSON.parse(t); } catch { /* HTML or empty: the appliance routes are not served on this substrate */ }
  if (!j) throw new Error("This substrate has no guest runtime: the appliance's /api/azure routes are not served here (offline appliance only).");
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : j.detail?.hint || j.detail?.reason || j.detail?.error || `HTTP ${r.status}`);
  return j;
}
const GUEST_ERR = { NoSuchInstance: "No running guest container backs this VM.", InstanceNotRunning: "The VM is not running." };

export function BootDiagnostics({ a }) {
  const enabled = !!a.properties?.diagnosticsProfile?.bootDiagnostics?.enabled;
  const data = useAsync(async () => {
    if (!enabled) return null;
    const arm = await restJson("POST", `${a.id}/retrieveBootDiagnosticsData`, { query: { "api-version": "2023-09-01" }, body: {} });
    let live = null, liveErr = null;
    try { live = await host(`/api/azure/vm/${encodeURIComponent(a.name)}/serial-console`); } catch (e) { liveErr = e; }
    return { arm, live, liveErr };
  }, [a.id, enabled]);
  const d = data.data;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Boot diagnostics</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Boot diagnostics commands"><Button size="small" onClick={data.reload}>Refresh</Button><Link href={`#/vms/${a.resourceGroup}/${a.name}/configuration`}>Settings</Link></div>
      {!enabled && <InfoBar title="Boot diagnostics is disabled" intent="warning">Enable it under Configuration to capture the serial log and a screenshot.</InfoBar>}
      {enabled && (data.loading ? <Loading /> : data.error ? <ErrorBar error={data.error} title="Could not retrieve boot diagnostics" /> : d && <>
        <h3>Screenshot</h3>
        <InfoBar title="Placeholder image">Vyomi has no virtual display adapter, so the screenshot is a blank placeholder written to the diagnostics storage account, not a capture of the guest's screen.</InfoBar>
        <div style={{ width: 320, height: 240, background: "#181c24", border: "1px solid #444", margin: "8px 0" }} aria-label="Screenshot placeholder" />
        <p className="vy-muted" style={{ fontSize: 12, wordBreak: "break-all" }}>{d.arm.consoleScreenshotBlobUri}</p>
        <h3>Serial log</h3>
        {d.live ? <p className="vy-muted" style={{ fontSize: 12 }}>Source: the guest container's own kernel log (dmesg), read live from the appliance.</p>
          : <p className="vy-muted" style={{ fontSize: 12 }}>Source: Vyomi platform log. {d.liveErr ? "No guest runtime on this substrate, so this is the VM's lifecycle record, not the guest's serial output." : ""}</p>}
        <pre data-testid="serial-log" style={{ background: "#16191f", color: "#d1d5db", padding: 12, maxHeight: 320, overflow: "auto", whiteSpace: "pre-wrap", fontSize: 12 }}>
          {d.live?.log || (d.arm.properties?.serialLogSource === "platform" ? "(platform log is stored at the blob below)" : "")}
        </pre>
        <p className="vy-muted" style={{ fontSize: 12, wordBreak: "break-all" }}>{d.arm.serialConsoleLogBlobUri}</p>
      </>)}
    </>
  );
}

function Shell({ instanceId, banner }) {
  const [lines, setLines] = useState([{ k: "sys", t: banner }]);
  const [cmd, setCmd] = useState("");
  const [cwd, setCwd] = useState("~");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "nearest" }); }, [lines]);
  const run = async () => {
    const c = cmd; if (!c.trim() || busy) return;
    setCmd(""); setBusy(true); setLines((l) => [...l, { k: "cmd", t: `${cwd}$ ${c}` }]);
    try {
      const r = await host(`/api/console/azurevm/instances/${encodeURIComponent(instanceId)}/exec`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ command: c }) });
      if (r.cwd) setCwd(r.cwd);
      setLines((l) => [...l, { k: r.exit_code ? "err" : "out", t: String(r.output ?? "").replace(/\n$/, "") }]);
    } catch (e) { setLines((l) => [...l, { k: "err", t: GUEST_ERR[e.message] || e.message }]); } finally { setBusy(false); }
  };
  return (
    <>
      <pre data-testid="vm-terminal" style={{ margin: 0, padding: 12, minHeight: 200, maxHeight: 360, overflow: "auto", background: "#16191f", color: "#d1d5db", whiteSpace: "pre-wrap", fontSize: 13 }}>
        {lines.map((l, i) => <div key={i} style={{ color: l.k === "err" ? "#ff8a80" : l.k === "cmd" ? "#9ecbff" : l.k === "sys" ? "#8d99a8" : undefined }}>{l.t}</div>)}<span ref={end} />
      </pre>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <Input style={{ flex: 1 }} aria-label="Terminal command" placeholder="Type a command and press Enter" value={cmd} disabled={busy} onChange={(_, d) => setCmd(d.value)} onKeyDown={(e) => e.key === "Enter" && run()} />
        <Button appearance="primary" disabled={busy} onClick={run}>Run</Button>
      </div>
    </>
  );
}

export function SerialConsole({ a }) {
  const probe = useAsync(() => host(`/api/azure/vm/${encodeURIComponent(a.name)}/serial-console`), [a.name]);
  const bootDiag = !!a.properties?.diagnosticsProfile?.bootDiagnostics?.enabled;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Serial console</div>
      {!bootDiag && <InfoBar title="Boot diagnostics must be enabled" intent="warning">The serial console needs boot diagnostics, as in Azure. Enable it under Configuration.</InfoBar>}
      {probe.loading ? <Loading /> : probe.error ? <InfoBar title="Serial console is not available here" intent="warning">{GUEST_ERR[probe.error.message] || probe.error.message}</InfoBar> : (
        <>
          <InfoBar title="Docker-exec shell">{probe.data.note}</InfoBar>
          <Shell instanceId={probe.data.exec.split("/").slice(-2)[0]} banner={`Connected to the serial console of ${a.name}. Press Enter after a command; the shell runs inside the guest container.`} />
        </>)}
    </>
  );
}

export function BastionConnect({ a }) {
  const notify = useNotify();
  const nicId = a.properties?.networkProfile?.networkInterfaces?.[0]?.id;
  const sub = `/subscriptions/${getSubscription()}`;
  const ctx = useAsync(async () => {
    const nic = nicId ? await restJson("GET", nicId, { query: { "api-version": "2023-09-01" } }) : null;
    const subnetId = nic?.properties?.ipConfigurations?.[0]?.properties?.subnet?.id || "";
    const vnetId = subnetId.split("/subnets/")[0].toLowerCase();
    const hosts = (await restJson("GET", `${sub}/providers/Microsoft.Network/bastionHosts`, { query: { "api-version": "2023-09-01" } })).value || [];
    return { vnetId, bastion: hosts.find((h) => (h.properties?.ipConfigurations || []).some((c) => String(c.properties?.subnet?.id || "").toLowerCase().startsWith(vnetId + "/"))) };
  }, [a.id]);
  const [f, setF] = useState({ auth: "Password", user: a.properties?.osProfile?.adminUsername || "azureuser", secret: "" });
  const [sess, setSess] = useState(null);
  const [err, setErr] = useState(null);
  const connect = async () => {
    setErr(null);
    try { setSess(await host(`/api/azure/vm/${encodeURIComponent(a.name)}/bastion/connect`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username: f.user, auth_type: f.auth }) })); notify.success("Bastion session connected.", "Connect"); }
    catch (e) { setErr(new Error(GUEST_ERR[e.message] || e.message)); }
  };
  const b = ctx.data?.bastion;
  return (
    <>
      <div className="vy-panel-title">{a.name} | Bastion</div>
      {ctx.loading ? <Loading /> : ctx.error ? <ErrorBar error={ctx.error} title="Could not read the virtual network" /> : !b ? (
        <InfoBar title="No Bastion host in this virtual network" intent="warning">Deploy an Azure Bastion host into this VM's virtual network (an AzureBastionSubnet) to connect. <Link href="#/vnets">Open virtual networks</Link></InfoBar>
      ) : (
        <>
          <InfoBar title={`Bastion host ${b.name}`}>The session is recorded on the appliance and the shell runs inside the guest container; there is no real HTTPS tunnel through the Bastion host. Requires the offline appliance.</InfoBar>
          <div className="vy-props" style={{ maxWidth: 420 }}>
            <Field label="Authentication Type"><Select aria-label="Authentication Type" value={f.auth} onChange={(_, d) => setF({ ...f, auth: d.value })}><option>Password</option><option>SSH Private Key from Local File</option></Select></Field>
            <Field label="Username"><Input aria-label="Username" value={f.user} onChange={(_, d) => setF({ ...f, user: d.value })} /></Field>
            {f.auth === "Password" ? <Field label="Password"><Input type="password" aria-label="Password" value={f.secret} onChange={(_, d) => setF({ ...f, secret: d.value })} /></Field>
              : <Field label="SSH Private Key"><Textarea aria-label="SSH Private Key" value={f.secret} onChange={(_, d) => setF({ ...f, secret: d.value })} /></Field>}
            <Button appearance="primary" onClick={connect}>Connect</Button>
          </div>
          <ErrorBar error={err} title="Connect failed" />
          {sess && <div style={{ marginTop: 12 }}>
            <p className="vy-muted" style={{ fontSize: 12 }}>Session {sess.session_id} {sess.ssh_command ? `| ${sess.ssh_command}` : ""}</p>
            <Shell instanceId={sess.exec.split("/").slice(-2)[0]} banner={`Connected through Bastion '${b.name}' as ${f.user}.`} />
          </div>}
        </>)}
    </>
  );
}

// ── Inventory / Update Manager / Performance diagnostics: read from (or done to) the REAL guest container ──
// (core/ssh_access_core INVENTORY_CMD / PERF_CMD / updates_command via /api/azure/vm/{id}/guest/*). Offline appliance only;
// Nano has no guest runtime here and the page says so (host() throws the substrate message).
const guest = (a, what, init) => host(`/api/azure/vm/${encodeURIComponent(a.name)}/guest/${what}`, init);
const Tbl = ({ head, rows, empty }) => (
  <table className="vy-table" style={{ width: "100%", borderCollapse: "collapse" }}>
    <thead><tr>{head.map((h) => <th key={h} style={{ textAlign: "left" }}>{h}</th>)}</tr></thead>
    <tbody>{rows.length === 0 ? <tr><td colSpan={head.length}>{empty}</td></tr> : rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
  </table>
);

export function GuestInventory({ a }) {
  const d = useAsync(() => guest(a, "inventory"), [a.id]);
  const [filter, setFilter] = useState("");
  const x = d.data;
  const pk = (x?.packages || []).filter((p) => p.name.includes(filter.toLowerCase()));
  return (
    <CapabilityContainer id="azure.vms.guest_views" title="Inventory">
      <div className="vy-panel-title">{a.name} | Inventory</div>
      <div className="vy-cmdbar"><Button size="small" onClick={d.reload}>Refresh</Button></div>
      {d.loading && !x ? <Loading /> : d.error ? <ErrorBar error={d.error} title="Inventory is not available" /> : x && (
        <>
          <p>{x.os.name} - kernel {x.os.kernel} - host {x.os.hostname} - {x.packageCount} packages ({x.packageManager}), read from the running guest.</p>
          <Field label="Filter packages"><Input value={filter} onChange={(_, v) => setFilter(v.value)} /></Field>
          <Tbl head={["Package", "Version"]} rows={pk.slice(0, 500).map((p) => [p.name, p.version])} empty="No packages match." />
        </>
      )}
    </CapabilityContainer>
  );
}

export function GuestPerformance({ a }) {
  const d = useAsync(() => guest(a, "performance"), [a.id]);
  const x = d.data;
  return (
    <CapabilityContainer id="azure.vms.guest_views" title="Performance diagnostics">
      <div className="vy-panel-title">{a.name} | Performance diagnostics</div>
      <div className="vy-cmdbar"><Button size="small" onClick={d.reload}>Run diagnostics</Button></div>
      {d.loading && !x ? <Loading /> : d.error ? <ErrorBar error={d.error} title="Performance diagnostics are not available" /> : x && (
        <>
          <p>Sampled from the guest's /proc just now: load {x.loadAvg.join(" / ")} on {x.cpus} CPU(s), memory {x.memUsedPercent}% used, root disk {x.diskRootUsedPercent}% full, up {Math.round(x.uptimeSeconds / 60)} min.</p>
          <h3>Findings</h3>
          <Tbl head={["Severity", "Finding"]} rows={x.findings.map((f) => [f.severity, f.finding])} empty="No issues found." />
          <h3>Top processes by memory</h3>
          <Tbl head={["PID", "RSS (KB)", "Command"]} rows={x.topProcesses.map((p) => [p.pid, p.rssKb, p.command])} empty="No processes." />
        </>
      )}
    </CapabilityContainer>
  );
}

export function UpdateManager({ a }) {
  const notify = useNotify();
  const d = useAsync(() => guest(a, "updates"), [a.id]);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState("");
  const run = async (body) => {
    setBusy(true);
    try {
      const r = await guest(a, "updates", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      setLog(r.installLog || "");
      notify.success(body.install ? `Install finished; ${r.pendingCount} update(s) still pending.` : `Package index refreshed: ${r.pendingCount} update(s) pending.`, "Update Manager");
      d.reload();
    } catch (e) { notify.error(e, "Update Manager failed"); } finally { setBusy(false); }
  };
  const x = d.data;
  return (
    <CapabilityContainer id="azure.vms.guest_views" title="Updates">
      <div className="vy-panel-title">{a.name} | Updates</div>
      <div className="vy-cmdbar"><Button size="small" onClick={d.reload}>Refresh view</Button><Button size="small" disabled={busy} onClick={() => run({ refresh: true })}>Check for updates (refresh package index)</Button><Button size="small" appearance="primary" disabled={busy || !x?.pendingCount} onClick={() => run({ install: true })}>Install all pending updates</Button></div>
      {d.loading && !x ? <Loading /> : d.error ? <ErrorBar error={d.error} title="Update Manager is not available" /> : x && (
        <>
          <p>Package manager: {x.packageManager}. {x.supported ? `${x.pendingCount} update(s) pending (assessed from the guest's package index; refresh it to see newer ones).` : "No supported package manager in this guest."}</p>
          <Tbl head={["Package", "Installed", "Available"]} rows={x.pending.map((p) => [p.name, p.installed, p.available])} empty="Nothing pending." />
          {log && <pre>{log}</pre>}
        </>
      )}
    </CapabilityContainer>
  );
}
