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
import Textarea from "@cloudscape-design/components/textarea";
import FormField from "@cloudscape-design/components/form-field";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { KeyValue } from "../../kit/common.jsx";
import NanoVmPanel, { isNano } from "../../../common/NanoVmPanel.jsx";

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

/* EC2 Instance Connect: SendSSHPublicKey through the appliance's instance-connect route (the key is authorised in the guest for 60 s). */
function PushKey({ instanceId }) {
  const [user, setUser] = useState("ubuntu");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const send = async () => {
    setBusy(true); setErr(null); setRes(null);
    try { setRes(await api(`/api/aws/ec2/instances/${instanceId}/instance-connect`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ os_user: user, public_key: key.trim() }) })); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <SpaceBetween size="m">
      <FormField label="OS user name"><Input value={user} ariaLabel="OS user name" onChange={({ detail }) => setUser(detail.value)} /></FormField>
      <FormField label="SSH public key" description="Authorised in the instance for 60 seconds (EC2 Instance Connect SendSSHPublicKey)."><Textarea rows={3} ariaLabel="SSH public key" value={key} placeholder="ssh-ed25519 AAAA... you@host" onChange={({ detail }) => setKey(detail.value)} /></FormField>
      <div><Button variant="primary" loading={busy} onClick={send}>Send public key</Button></div>
      {err && <Alert type="error" header="Could not push the key">{err.message}</Alert>}
      {res && <Alert type="success" header="Public key sent" data-testid="eic-result">
        <SpaceBetween size="xs"><span>{res.delivered ? "Key authorised in the instance" : "Key recorded but no running guest received it"} - valid for {res.expires_in_seconds} s for new connections.</span>
          {res.ssh_command && <pre data-testid="eic-command" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{res.ssh_command}</pre>}</SpaceBetween></Alert>}
    </SpaceBetween>
  );
}

/* SSM Session Manager: StartSession/TerminateSession record real sessions; commands run in the target's container. */
function SsmSession({ instanceId }) {
  const [sess, setSess] = useState(null);
  const [lines, setLines] = useState([]);
  const [cmd, setCmd] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const start = async () => {
    setErr(null); setBusy(true);
    try { const r = await api("/api/ssm/sessions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ target: instanceId }) }); setSess(r); setLines([{ t: `Session ${r.SessionId} started.` }]); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const run = async () => {
    const c = cmd; if (!c.trim() || !sess) return; setCmd("");
    setLines((l) => [...l, { t: `$ ${c}` }]);
    try { const r = await api(`/api/ssm/sessions/${sess.SessionId}/exec`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ command: c }) }); setLines((l) => [...l, { t: String(r.output ?? "").replace(/\n$/, "") }]); }
    catch (e) { setLines((l) => [...l, { t: e.message }]); }
  };
  const stop = async () => { try { await api(`/api/ssm/sessions/${sess.SessionId}/terminate`, { method: "POST" }); } catch (e) { setErr(e); } setSess(null); setLines([]); };
  return (
    <SpaceBetween size="m">
      {err && <Alert type="error" header="Session Manager">{err.message}</Alert>}
      {!sess ? <div><Button variant="primary" loading={busy} onClick={start}>Start session</Button></div> : (<>
        <KeyValue columns={3} items={[["Session ID", sess.SessionId], ["Target", sess.Target || instanceId], ["Status", sess.Status || "Connected"]]} />
        <pre data-testid="ssm-terminal" style={{ margin: 0, padding: 12, minHeight: 120, maxHeight: 280, overflow: "auto", background: "#16191f", color: "#d1d5db", whiteSpace: "pre-wrap", fontSize: 13 }}>{lines.map((l, i) => <div key={i}>{l.t}</div>)}</pre>
        <SpaceBetween direction="horizontal" size="xs">
          <div style={{ flex: 1, minWidth: 360 }}><Input value={cmd} ariaLabel="Session command" onChange={({ detail }) => setCmd(detail.value)} onKeyDown={({ detail }) => detail.key === "Enter" && run()} /></div>
          <Button onClick={run}>Run</Button><Button onClick={stop}>Terminate session</Button></SpaceBetween></>)}
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
      { id: "push", label: "Send SSH public key", content: <PushKey instanceId={instanceId} /> },
      { id: "ssm", label: "Session Manager", content: <SsmSession instanceId={instanceId} /> },
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
  // Nano: the instance is a real v86 VM in this browser tab; the host paints boot state, the vyomi-tunnel ssh command and an xterm shell.
  return (
    <CapabilityContainer id="ec2.instances.connect" title="Connect">
      {isNano() ? (
        <SpaceBetween size="l">
          <NanoVmPanel cloud="aws" vmRef={instanceId} />
          <CapabilityContainer id="ssm.session-manager" title="Session Manager">
            <Box color="text-body-secondary" variant="small">Runs a command-at-a-time shell in this instance's in-browser VM (it must be running). No ssmmessages data channel, so the AWS CLI session-manager-plugin cannot attach.</Box>
            <SsmSession instanceId={instanceId} />
          </CapabilityContainer>
        </SpaceBetween>
      ) : <Body instanceId={instanceId} />}
    </CapabilityContainer>
  );
}
