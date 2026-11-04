/* "Connect to instance": real shell access to an offline-appliance instance. Tabs: EC2 Instance Connect (an in-browser terminal that
 * runs commands inside the instance's container via the appliance's console exec endpoint) and SSH client (the real ssh command,
 * key download and host/port from the appliance's connect-info). On Nano the capability is not simulated (no sshd to reach), so
 * the CapabilityContainer shows the honest panel instead of this body. Capability id: ec2.instances.connect. */
import { useEffect, useRef, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Tabs from "@cloudscape-design/components/tabs";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { KeyValue } from "../../kit/common.jsx";

async function api(path, init) {
  const r = await fetch(path, init);
  const t = await r.text();
  let j = {}; try { j = JSON.parse(t); } catch { /* not JSON */ }
  if (!r.ok) throw new Error(j.detail?.hint || j.detail?.reason || (typeof j.detail === "string" ? j.detail : "") || j.message || `HTTP ${r.status}`);
  return j;
}

function Terminal({ instanceId }) {
  const [lines, setLines] = useState([{ k: "sys", t: `Connected to ${instanceId} (shell runs inside the instance's container).` }]);
  const [cmd, setCmd] = useState("");
  const [cwd, setCwd] = useState("~");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "nearest" }); }, [lines]);
  const run = async () => {
    const c = cmd; if (!c.trim() || busy) return;
    setCmd(""); setBusy(true);
    setLines((l) => [...l, { k: "cmd", t: `${cwd}$ ${c}` }]);
    try {
      const r = await api(`/api/ec2/instances/${instanceId}/console/exec`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ command: c }) });
      if (r.cwd) setCwd(r.cwd);
      setLines((l) => [...l, { k: r.exit_code ? "err" : "out", t: String(r.output ?? "").replace(/\n$/, "") }]);
    } catch (e) { setLines((l) => [...l, { k: "err", t: e.message }]); } finally { setBusy(false); }
  };
  return (
    <SpaceBetween size="s">
      <pre data-testid="connect-terminal" style={{ margin: 0, padding: 12, minHeight: 160, maxHeight: 320, overflow: "auto", background: "#16191f", color: "#d1d5db", whiteSpace: "pre-wrap", fontSize: 13 }}>
        {lines.map((l, i) => <div key={i} style={{ color: l.k === "err" ? "#ff8a80" : l.k === "cmd" ? "#9ecbff" : l.k === "sys" ? "#8d99a8" : undefined }}>{l.t}</div>)}<span ref={end} />
      </pre>
      <SpaceBetween direction="horizontal" size="xs">
        <div style={{ flex: 1, minWidth: 360 }}><Input value={cmd} ariaLabel="Terminal command" placeholder="Type a command and press Enter" disabled={busy}
          onChange={({ detail }) => setCmd(detail.value)} onKeyDown={({ detail }) => detail.key === "Enter" && run()} /></div>
        <Button variant="primary" loading={busy} onClick={run}>Run</Button>
      </SpaceBetween>
    </SpaceBetween>
  );
}

function Body({ instanceId }) {
  const info = useAsync(() => api(`/api/aws/ec2/instances/${instanceId}/connect-info`), [instanceId]);
  const [copied, setCopied] = useState(false);
  if (info.loading) return <StatusIndicator type="loading">Checking SSH reachability</StatusIndicator>;
  const i = info.data;
  const ssh = i?.ssh;
  return (
    <Tabs tabs={[
      { id: "eic", label: "EC2 Instance Connect", content: info.error ? <Alert type="warning">{info.error.message}</Alert> : <Terminal instanceId={instanceId} /> },
      { id: "ssh", label: "SSH client", content: info.error ? <Alert type="warning" header="SSH is not available for this instance">{info.error.message}</Alert> : (
        <SpaceBetween size="m">
          <KeyValue columns={3} items={[["Instance ID", instanceId], ["User name", ssh?.user], ["Host", ssh?.host], ["Port", ssh?.port], ["Private key", ssh?.key_local_filename]]} />
          <div>
            <Box variant="awsui-key-label">Example</Box>
            <pre data-testid="ssh-command" style={{ margin: "4px 0", whiteSpace: "pre-wrap" }}>{ssh?.command}</pre>
            <SpaceBetween direction="horizontal" size="xs">
              <Button iconName="copy" onClick={() => { navigator.clipboard?.writeText(ssh?.command || ""); setCopied(true); }}>{copied ? "Copied" : "Copy command"}</Button>
              {ssh?.key_download_url && <Button iconName="download" href={ssh.key_download_url}>Download private key (.pem)</Button>}
            </SpaceBetween>
          </div>
          {i?.lxc?.command && <Box color="text-body-secondary">On the appliance host you can also run <code>{i.lxc.command}</code>.</Box>}
        </SpaceBetween>) },
    ]} />
  );
}

export default function ConnectModalBody({ instanceId }) {
  return (
    <CapabilityContainer id="ec2.instances.connect" title="Connect">
      <Body instanceId={instanceId} />
    </CapabilityContainer>
  );
}
