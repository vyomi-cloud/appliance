/* Exact SSH connection strings for a VM, shared by the AWS / GCP / Azure consoles (offline appliance + Mesh).
 *
 * The strings come from the appliance itself (GET <cloud connect-info>): the same key, user, host and port the instance really has, so
 * what you paste runs as-is. Nothing here is templated in the browser. Shows:
 *   - Connect (one paste)   key download + chmod + ssh, joined with &&   (when the appliance gave a key command)
 *   - the individual steps  one-time setup (Codespaces jump host), save the key, ssh
 *   - other routes          alternatives the appliance listed, and `docker exec` on the appliance host
 * Plain React + inline styles on CSS variables with fallbacks, so it fits Cloudscape, MUI and Fluent pages alike. */
import { useEffect, useState } from "react";

export const connectInfoUrl = (cloud, id) => {
  const e = encodeURIComponent(id);
  return cloud === "aws" ? `/api/aws/ec2/instances/${e}/connect-info`
    : cloud === "gcp" ? `/api/gcp/compute/instances/${e}/connect-info`
    : `/api/azure/vm/${e}/connect-info`;
};

const BOX = { background: "var(--vy-code-bg, rgba(127,127,127,.14))", borderRadius: 4, padding: "8px 10px", margin: 0, fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", fontSize: 13, whiteSpace: "pre-wrap", wordBreak: "break-all", flex: 1, minWidth: 0 };
const BTN = { cursor: "pointer", border: "1px solid var(--vy-line, #8a94a3)", background: "transparent", color: "inherit", borderRadius: 4, padding: "4px 10px", fontSize: 12, whiteSpace: "nowrap", height: 28 };
const MUTED = { color: "var(--vy-sub, #5f6b7a)", fontSize: 12 };

/** Compose the one-paste line from the appliance's own pieces. */
export function oneLine(info) {
  const ssh = info?.ssh || {};
  return [ssh.setup_command, ssh.key_fetch_command, ssh.command].filter(Boolean).join(" && ");
}

function Cmd({ label, text, note, testid }) {
  const [copied, setCopied] = useState(false);
  if (!text) return null;
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); } catch { /* clipboard blocked: the text is selectable */ }
    setCopied(true); setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div style={{ margin: "10px 0" }}>
      {label && <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <pre data-testid={testid} style={BOX}>{text}</pre>
        <button type="button" style={BTN} onClick={copy} aria-label={`Copy ${label || "command"}`}>{copied ? "Copied" : "Copy"}</button>
      </div>
      {note && <div style={{ ...MUTED, marginTop: 4 }}>{note}</div>}
    </div>
  );
}

/** `cloud` aws|gcp|azure, `id` the instance id/name. */
export default function VmConnect({ cloud, id }) {
  const [st, setSt] = useState({ loading: true });
  useEffect(() => {
    let live = true;
    setSt({ loading: true });
    fetch(connectInfoUrl(cloud, id)).then(async (r) => {
      const t = await r.text(); let j = {}; try { j = JSON.parse(t); } catch { /* not JSON */ }
      if (!live) return;
      if (!r.ok) {
        const d = j.detail || {};
        setSt({ error: (typeof d === "string" ? d : d.hint || d.reason || d.error) || j.message || `HTTP ${r.status}` });
      } else setSt({ info: j });
    }).catch((e) => live && setSt({ error: e.message || "Could not reach the appliance" }));
    return () => { live = false; };
  }, [cloud, id]);

  if (st.loading) return <div style={MUTED}>Preparing SSH access…</div>;
  if (st.error) return <div role="alert" style={{ ...BOX, whiteSpace: "normal" }}>SSH is not available yet: {st.error}</div>;
  const info = st.info, ssh = info.ssh || {};
  const one = oneLine(info);
  const steps = [ssh.setup_command, ssh.key_fetch_command].filter(Boolean).length;
  return (
    <div data-testid="vm-connect">
      <Cmd label="Connect (paste in your terminal)" text={one} testid="vm-connect-oneline"
        note={`Signs in as ${ssh.user || "the instance user"}${ssh.port ? `, port ${ssh.port}` : ""}. Run it on the machine where you want the shell.`} />
      {steps > 0 && (
        <details style={{ margin: "8px 0" }}>
          <summary style={{ cursor: "pointer" }}>Run the steps one at a time</summary>
          <Cmd label="1. One-time setup (jump host)" text={ssh.setup_command} />
          <Cmd label={ssh.setup_command ? "2. Save the private key" : "1. Save the private key"} text={ssh.key_fetch_command} />
          <Cmd label="Then connect" text={ssh.command} />
        </details>
      )}
      {(info.alternatives || []).map((a, i) => <Cmd key={i} label={a.label || "Alternative"} text={a.command} />)}
      <Cmd label="On the machine running the appliance" text={info.lxc?.command} note={info.lxc?.note} />
      {info.note && <div style={{ ...MUTED, whiteSpace: "pre-wrap" }}>{info.note}</div>}
    </div>
  );
}
