/* Real container tools for Container Apps (offline appliance with the Docker backend): Log stream, Console (docker exec),
 * Events, Diagnose and solve problems, Environment logs. Every panel calls the engine (core/azure_app_core.py); when there is
 * no container runtime (Nano / no Docker) the engine answers 409 RuntimeUnavailable and the panel shows that reason - no fake output. */
import { useEffect, useRef, useState } from "react";
import { Button, Field, Input, Switch } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { restJson } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import { API_VERSION } from "./api.js";

const call = (method, path, body) => restJson(method, path, { query: { "api-version": API_VERSION }, body });
const mono = { fontFamily: "Consolas, monospace", fontSize: 12, background: "#111", color: "#ddd", padding: 8, minHeight: 240, maxHeight: 420, overflow: "auto", whiteSpace: "pre-wrap" };

function Wrap({ cap, title, children }) {
  return <CapabilityContainer id={cap} title={title}>{children}</CapabilityContainer>;
}

export function LogStream({ path, cap, title, execution }) {
  const [auto, setAuto] = useState(true);
  const [lines, setLines] = useState([]);
  const [err, setErr] = useState(null);
  const box = useRef(null);
  const load = async () => {
    try {
      const url = execution ? `${path}/executions/${encodeURIComponent(execution)}/logs` : `${path}/logstream`;
      const r = await call("GET", url);
      setLines(r.lines || []); setErr(null);
    } catch (e) { setErr(e); }
  };
  useEffect(() => { load(); if (!auto) return undefined; const t = setInterval(load, 2000); return () => clearInterval(t); }, [path, auto, execution]);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [lines]);
  return (
    <Wrap cap={cap} title={title}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 8 }}>
        <Switch checked={auto} onChange={(_, d) => setAuto(d.checked)} label="Follow (poll every 2s)" />
        <Button icon={<ArrowClockwise20Regular />} onClick={load}>Refresh</Button>
      </div>
      {err ? <ErrorBar error={err} title="Log stream unavailable" /> : <div ref={box} style={mono} aria-label="Log output">{lines.length ? lines.join("\n") : "No output yet."}</div>}
    </Wrap>
  );
}

export function Console({ path, cap }) {
  const [cmd, setCmd] = useState("uname -a");
  const [out, setOut] = useState([]);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const r = await call("POST", `${path}/exec`, { command: cmd });
      setOut((o) => [...o, `$ ${cmd}`, r.output || "", `[exit ${r.exitCode}]`]);
    } catch (e) { setOut((o) => [...o, `$ ${cmd}`, `error: ${e.message || e}`]); }
    setBusy(false);
  };
  return (
    <Wrap cap={cap} title="Console">
      <p style={{ fontSize: 13 }}>Runs the command inside the app's running container (docker exec).</p>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <Input style={{ flex: 1 }} value={cmd} aria-label="Command" onChange={(_, d) => setCmd(d.value)} onKeyDown={(e) => { if (e.key === "Enter" && !busy) run(); }} />
        <Button appearance="primary" disabled={busy || !cmd} onClick={run}>Run</Button>
      </div>
      <div style={mono} aria-label="Console output">{out.join("\n")}</div>
    </Wrap>
  );
}

export function Events({ path, cap, title = "Events" }) {
  const ev = useAsync(async () => (await call("GET", `${path}/events`)).value || [], [path]);
  if (ev.loading && !ev.data) return <Loading />;
  return (
    <Wrap cap={cap} title={title}>
      <Button icon={<ArrowClockwise20Regular />} onClick={ev.reload}>Refresh</Button>
      {ev.error ? <ErrorBar error={ev.error} title="Events unavailable" /> : (
        <table style={{ width: "100%", marginTop: 8, fontSize: 13 }}>
          <thead><tr><th align="left">Time</th><th align="left">Type</th><th align="left">Reason</th><th align="left">Message</th></tr></thead>
          <tbody>{(ev.data || []).map((e, i) => <tr key={i}><td>{e.timestamp}</td><td>{e.type}</td><td>{e.reason}</td><td>{e.message}</td></tr>)}</tbody>
        </table>)}
      {!ev.error && !(ev.data || []).length ? <p>No events recorded.</p> : null}
    </Wrap>
  );
}

export function Diagnose({ path, cap, title = "Diagnose and solve problems" }) {
  const d = useAsync(async () => (await call("GET", `${path}/diagnose`)).value || [], [path]);
  if (d.loading && !d.data) return <Loading />;
  const color = { Healthy: "#107c10", Warning: "#b36b00", Critical: "#c50f1f", Info: "#555" };
  return (
    <Wrap cap={cap} title={title}>
      <Button icon={<ArrowClockwise20Regular />} onClick={d.reload}>Run detectors</Button>
      {d.error ? <ErrorBar error={d.error} title="Diagnostics unavailable" /> : (d.data || []).map((x, i) => (
        <div key={i} style={{ borderLeft: `4px solid ${color[x.status] || "#555"}`, padding: "6px 10px", margin: "8px 0" }}>
          <b>{x.name}</b> <span style={{ color: color[x.status] }}>{x.status}</span><div style={{ fontSize: 13 }}>{x.detail}</div>
        </div>))}
    </Wrap>
  );
}

export function EnvLogs({ path, cap }) {
  const [q, setQ] = useState("");
  const r = useAsync(async () => (await call("POST", `${path}/logs`, { tail: 100, contains: q })).value || [], [path, q]);
  return (
    <Wrap cap={cap} title="Logs">
      <Field label="Filter (substring)"><Input value={q} onChange={(_, d) => setQ(d.value)} aria-label="Log filter" /></Field>
      {r.loading && !r.data ? <Loading /> : r.error ? <ErrorBar error={r.error} title="Environment logs unavailable" /> : (
        <div style={mono} aria-label="Environment logs">{(r.data || []).map((x) => `${x.app}  ${x.log}`).join("\n") || "No log lines."}</div>)}
    </Wrap>
  );
}
