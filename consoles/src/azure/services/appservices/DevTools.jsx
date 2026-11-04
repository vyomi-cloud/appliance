/* App Service Development Tools + Monitoring tools over the Kudu surface of the site
 * (Microsoft.Web/sites/{site}/kudu/api/..., core/azure_kudu_core.py): Console, Advanced Tools (Kudu), App Service Editor,
 * Process explorer, Log stream and Extensions. All of it reads/writes the site's REAL stored state (its files, app settings,
 * invocation/WebJob/deployment history); nothing is canned. */
import { useEffect, useRef, useState } from "react";
import { Button, Input, Select, Tab, TabList, Textarea } from "@fluentui/react-components";
import { ArrowClockwise20Regular, Delete20Regular, Save20Regular, Add20Regular, FolderAdd20Regular, Play20Regular, Pause20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading, fmtDate } from "../../kit/common.jsx";
import { SITES } from "./api.js";

const AV = { "api-version": "2023-12-01" };
const kudu = (rg, name, tail) => `${SITES.path(rg, name)}/kudu/api/${tail}`;
const call = (method, rg, name, tail, opts = {}) => restJson(method, kudu(rg, name, tail), { query: { ...AV, ...(opts.query || {}) }, body: opts.body });
const vfsUrl = (p) => "vfs" + p.replace(/^\/home/, "").split("/").map((s) => encodeURIComponent(s)).join("/");
const TITLE = (name, t) => <div className="vy-panel-title">{name} | {t}</div>;

// ── Console ──────────────────────────────────────────────────────────────────────────────
export function Console({ a, rg, name }) {
  const [cwd, setCwd] = useState("/home");
  const [lines, setLines] = useState([{ k: "sys", t: `Vyomi Kudu console for ${name}. Type "help" for the supported commands (this is not an OS shell).` }]);
  const [cmd, setCmd] = useState("");
  const [hist, setHist] = useState([]);
  const [hi, setHi] = useState(-1);
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [lines]);
  const run = async () => {
    const c = cmd.trim();
    if (!c || busy) return;
    setBusy(true); setCmd(""); setHist((h) => [...h, c]); setHi(-1);
    const add = [{ k: "cmd", t: `${cwd}> ${c}` }];
    try {
      const r = await call("POST", rg, name, "command", { body: { command: c, dir: cwd } });
      if (r.Output) add.push({ k: "out", t: r.Output.replace(/\n$/, "") });
      if (r.Error) add.push({ k: "err", t: r.Error.replace(/\n$/, "") });
      setCwd(r.Dir || cwd);
    } catch (e) { add.push({ k: "err", t: e.message }); }
    setLines((l) => [...l, ...add]); setBusy(false);
  };
  const onKey = (e) => {
    if (e.key === "Enter") run();
    else if (e.key === "ArrowUp" && hist.length) { const i = hi < 0 ? hist.length - 1 : Math.max(0, hi - 1); setHi(i); setCmd(hist[i]); e.preventDefault(); }
    else if (e.key === "ArrowDown" && hi >= 0) { const i = hi + 1; setHi(i >= hist.length ? -1 : i); setCmd(i >= hist.length ? "" : hist[i]); e.preventDefault(); }
  };
  return (
    <>
      {TITLE(name, "Console")}
      <CapabilityContainer id="azure.appservices.webapp.console" title="Console">
        <div data-testid="kudu-console" style={{ background: "#1e1e1e", color: "#d4d4d4", fontFamily: "Consolas, monospace", fontSize: 13, padding: 12, height: 360, overflow: "auto", borderRadius: 2 }}>
          {lines.map((l, i) => <pre key={i} style={{ margin: 0, whiteSpace: "pre-wrap", color: l.k === "err" ? "#f48771" : l.k === "cmd" ? "#9cdcfe" : l.k === "sys" ? "#6a9955" : undefined }}>{l.t}</pre>)}
          <div style={{ display: "flex", gap: 6 }}>
            <span style={{ color: "#9cdcfe" }}>{cwd}&gt;</span>
            <input aria-label="Console input" value={cmd} disabled={busy} autoFocus onChange={(e) => setCmd(e.target.value)} onKeyDown={onKey}
              style={{ flex: 1, background: "transparent", border: 0, outline: 0, color: "inherit", font: "inherit" }} />
          </div>
          <div ref={end} />
        </div>
      </CapabilityContainer>
    </>
  );
}

// ── Advanced Tools (Kudu dashboard) ───────────────────────────────────────────────────────
export function AdvancedTools({ a, rg, name }) {
  const notify = useNotify();
  const [tab, setTab] = useState("environment");
  const env = useAsync(() => call("GET", rg, name, "environment"), [rg, name]);
  const settings = useAsync(() => call("GET", rg, name, "settings"), [rg, name]);
  const deps = useAsync(() => call("GET", rg, name, "deployments"), [rg, name]);
  const [k, setK] = useState(""); const [v, setV] = useState("");
  const save = async () => {
    try { await call("POST", rg, name, "settings", { body: { [k]: v } }); notify.success(`Kudu setting ${k} saved.`); setK(""); setV(""); settings.reload(); }
    catch (e) { notify.error(e, "Save failed"); }
  };
  return (
    <>
      {TITLE(name, "Advanced Tools")}
      <CapabilityContainer id="azure.appservices.webapp.kudu" title="Kudu">
        <p style={{ fontSize: 13 }}>Kudu is the engine behind Git deployments, file browsing and diagnostics. Scm site: <code>{name}.scm.azurewebsites.net</code> (served here at <code>…/sites/{name}/kudu/api</code>).</p>
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} style={{ marginBottom: 8 }}>
          <Tab value="environment">Environment</Tab><Tab value="settings">Settings</Tab><Tab value="deployments">Deployments</Tab><Tab value="tools">Tools</Tab>
        </TabList>
        {tab === "environment" && (env.loading && !env.data ? <Loading /> : env.data && (
          <div className="vy-props">
            <KV label="Site" value={env.data.siteName} /><KV label="Operating system" value={env.data.os} /><KV label="Runtime" value={env.data.runtime} />
            <KV label="Instances" value={env.data.instances} /><KV label="Home" value={env.data.home} /><KV label="State" value={env.data.state} />
            <KV label="Kudu version" value={env.data.version} />
          </div>))}
        {tab === "settings" && (
          <>
            <ErrorBar error={settings.error} />
            <table className="vy-grid"><thead><tr><th>Setting</th><th>Value</th></tr></thead>
              <tbody>{Object.entries(settings.data || {}).map(([kk, vv]) => <tr key={kk}><td>{kk}</td><td>{String(vv)}</td></tr>)}</tbody></table>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Input placeholder="SCM_SETTING_NAME" value={k} onChange={(_, d) => setK(d.value)} aria-label="Kudu setting name" />
              <Input placeholder="value" value={v} onChange={(_, d) => setV(d.value)} aria-label="Kudu setting value" />
              <Button appearance="primary" disabled={!k} onClick={save}>Save</Button>
            </div>
          </>)}
        {tab === "deployments" && (
          <table className="vy-grid"><thead><tr><th>Status</th><th>Author</th><th>Message</th><th>Started</th><th>Active</th></tr></thead>
            <tbody>{(deps.data?.value || []).length ? deps.data.value.map((d) => <tr key={d.id}><td>{d.status_text}</td><td>{d.author}</td><td>{d.message}</td><td>{fmtDate(d.start_time)}</td><td>{d.active ? "Yes" : ""}</td></tr>)
              : <tr><td colSpan={5} className="vy-muted">No deployments yet. Configure Deployment Center and push or sync to create one.</td></tr>}</tbody></table>)}
        {tab === "tools" && (
          <ul style={{ fontSize: 13 }}>
            <li><a href={`#/appservices/${rg}/${name}/console`}>Debug console</a> — browse and run commands over the site's files.</li>
            <li><a href={`#/appservices/${rg}/${name}/processexplorer`}>Process explorer</a></li>
            <li><a href={`#/appservices/${rg}/${name}/logstream`}>Log stream</a></li>
            <li><a href={`#/appservices/${rg}/${name}/extensions`}>Site extensions</a></li>
            <li><a href={`#/appservices/${rg}/${name}/appeditor`}>App Service Editor</a></li>
          </ul>)}
      </CapabilityContainer>
    </>
  );
}

// ── App Service Editor ────────────────────────────────────────────────────────────────────
export function AppEditor({ a, rg, name }) {
  const notify = useNotify();
  const [dir, setDir] = useState("/home/site/wwwroot");
  const [file, setFile] = useState(null);
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);
  const list = useAsync(() => call("GET", rg, name, vfsUrl(dir)), [rg, name, dir]);
  const open = async (p) => {
    try { const r = await call("GET", rg, name, vfsUrl(p)); setFile(p); setText(r.content); setDirty(false); }
    catch (e) { notify.error(e, "Open failed"); }
  };
  const save = async () => {
    try { await call("PUT", rg, name, vfsUrl(file), { body: { content: text } }); setDirty(false); notify.success(`${file.split("/").pop()} saved.`); list.reload(); }
    catch (e) { notify.error(e, "Save failed"); }
  };
  const newFile = async () => {
    const n = window.prompt("New file name"); if (!n) return;
    const p = `${dir}/${n}`;
    try { await call("PUT", rg, name, vfsUrl(p), { body: { content: "" } }); list.reload(); open(p); } catch (e) { notify.error(e, "Create failed"); }
  };
  const newDir = async () => {
    const n = window.prompt("New folder name"); if (!n) return;
    try { await call("PUT", rg, name, vfsUrl(`${dir}/${n}`), { query: { mkdir: "true" } }); list.reload(); } catch (e) { notify.error(e, "Create failed"); }
  };
  const del = async () => {
    try { await call("DELETE", rg, name, vfsUrl(file)); notify.success("Deleted."); setFile(null); setText(""); list.reload(); } catch (e) { notify.error(e, "Delete failed"); }
  };
  const up = dir.replace(/\/[^/]+$/, "") || "/home";
  return (
    <>
      {TITLE(name, "App Service Editor (Preview)")}
      <CapabilityContainer id="azure.appservices.webapp.appeditor" title="App Service Editor">
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <Button size="small" icon={<Add20Regular />} onClick={newFile}>New file</Button>
          <Button size="small" icon={<FolderAdd20Regular />} onClick={newDir}>New folder</Button>
          <Button size="small" icon={<Save20Regular />} disabled={!file || !dirty} onClick={save}>Save</Button>
          <Button size="small" icon={<Delete20Regular />} disabled={!file} onClick={del}>Delete</Button>
          <Button size="small" icon={<ArrowClockwise20Regular />} onClick={list.reload}>Refresh</Button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 12 }}>
          <div data-testid="editor-tree" style={{ border: "1px solid var(--colorNeutralStroke2, #ddd)", minHeight: 320, padding: 8, fontSize: 13 }}>
            <div className="vy-muted" style={{ marginBottom: 6 }}>{dir}</div>
            {dir !== "/home" && <div><a href="#" onClick={(e) => { e.preventDefault(); setDir(up); }}>..</a></div>}
            <ErrorBar error={list.error} />
            {(Array.isArray(list.data) ? list.data : []).map((e) => (
              <div key={e.path}><a href="#" onClick={(ev) => { ev.preventDefault(); e.mime === "inode/directory" ? setDir(e.path) : open(e.path); }}>{e.mime === "inode/directory" ? "📁 " : "📄 "}{e.name}</a></div>
            ))}
          </div>
          <div>
            <div className="vy-muted" style={{ fontSize: 12, marginBottom: 4 }}>{file ? file + (dirty ? " (unsaved)" : "") : "Select a file to edit"}</div>
            <Textarea aria-label="File editor" resize="vertical" disabled={!file} value={text} onChange={(_, d) => { setText(d.value); setDirty(true); }}
              style={{ width: "100%", fontFamily: "Consolas, monospace" }} textarea={{ style: { minHeight: 300 } }} />
          </div>
        </div>
      </CapabilityContainer>
    </>
  );
}

// ── Process explorer ──────────────────────────────────────────────────────────────────────
export function ProcessExplorer({ a, rg, name }) {
  const { data, loading, error, reload } = useAsync(() => call("GET", rg, name, "processes"), [rg, name]);
  return (
    <>
      {TITLE(name, "Process explorer")}
      <CapabilityContainer id="azure.appservices.webapp.processes" title="Processes" actions={<Button size="small" icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</Button>}>
        <ErrorBar error={error} />
        {data?.note && <InfoBar>{data.note}</InfoBar>}
        {loading && !data ? <Loading /> : (
          <table className="vy-grid" aria-label="Processes"><thead><tr><th>PID</th><th>Name</th><th>Kind</th><th>Instance</th><th>CPU time (ms)</th><th>Working set (MB)</th><th>Threads</th><th>Handles</th></tr></thead>
            <tbody>{(data?.value || []).length ? data.value.map((p) => <tr key={p.id}><td>{p.id}</td><td>{p.name}</td><td>{p.kind}</td><td>{p.instance}</td><td>{p.cpuTimeMs}</td><td>{p.workingSetMb}</td><td>{p.threads}</td><td>{p.handles}</td></tr>)
              : <tr><td colSpan={8} className="vy-muted">The app is stopped; no worker process is running.</td></tr>}</tbody></table>)}
      </CapabilityContainer>
    </>
  );
}

// ── Log stream ────────────────────────────────────────────────────────────────────────────
export function LogStream({ a, rg, name }) {
  const [type, setType] = useState("all");
  const [on, setOn] = useState(true);
  const [lines, setLines] = useState([]);
  const [lvl, setLvl] = useState(null);
  const cur = useRef("");
  useEffect(() => { cur.current = ""; setLines([]); }, [type]);
  useEffect(() => {
    if (!on) return undefined;
    let dead = false;
    const tick = async () => {
      try {
        const r = await call("GET", rg, name, "logstream", { query: { since: cur.current, type } });
        if (dead) return;
        setLvl(r.applicationLogging);
        if (r.lines.length) { cur.current = r.cursor; setLines((l) => [...l, ...r.lines].slice(-500)); }
      } catch { /* transient */ }
    };
    tick();
    const t = setInterval(tick, 2000);
    return () => { dead = true; clearInterval(t); };
  }, [on, type, rg, name]);
  return (
    <>
      {TITLE(name, "Log stream")}
      <CapabilityContainer id="azure.appservices.webapp.logstream" title="Log stream"
        actions={<Button size="small" icon={on ? <Pause20Regular /> : <Play20Regular />} onClick={() => setOn(!on)}>{on ? "Pause" : "Start"}</Button>}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
          <Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Log type"><option value="all">All logs</option><option value="Application">Application logs</option><option value="Platform">Platform logs</option></Select>
          <Button size="small" onClick={() => setLines([])}>Clear</Button>
          {lvl === "Off" && type === "Application" && <span className="vy-muted" style={{ fontSize: 12 }}>Application logging is Off in App Service logs; invocation and WebJob lines are still tailed.</span>}
        </div>
        <pre data-testid="log-stream" style={{ background: "#1e1e1e", color: "#d4d4d4", padding: 12, height: 320, overflow: "auto", fontSize: 12, margin: 0 }}>
          {lines.length ? lines.map((l) => `${l.time}  [${l.source}] ${l.text}`).join("\n") : "Connected. Waiting for log lines..."}
        </pre>
      </CapabilityContainer>
    </>
  );
}

// ── Extensions ────────────────────────────────────────────────────────────────────────────
export function Extensions({ a, rg, name }) {
  const notify = useNotify();
  const [scope, setScope] = useState("installed");
  const { data, loading, error, reload } = useAsync(() => call("GET", rg, name, "siteextensions", { query: { scope } }), [rg, name, scope]);
  const act = async (id, del) => {
    try { await call(del ? "DELETE" : "PUT", rg, name, `siteextensions/${encodeURIComponent(id)}`); notify.success(`${id} ${del ? "uninstalled" : "installed"}.`); reload(); }
    catch (e) { notify.error(e, del ? "Uninstall failed" : "Install failed"); }
  };
  return (
    <>
      {TITLE(name, "Extensions")}
      <CapabilityContainer id="azure.appservices.webapp.extensions" title="Extensions">
        <TabList selectedValue={scope} onTabSelect={(_, d) => setScope(d.value)} style={{ marginBottom: 8 }}>
          <Tab value="installed">Installed extensions</Tab><Tab value="gallery">Gallery</Tab>
        </TabList>
        <ErrorBar error={error} title={error?.status === 400 ? "Extensions unavailable" : "Failed to load extensions"} />
        {loading && !data ? <Loading /> : !error && (
          <table className="vy-grid" aria-label="Extensions"><thead><tr><th>Name</th><th>Version</th><th>Description</th><th></th></tr></thead>
            <tbody>{(data?.value || []).length ? data.value.map((e) => (
              <tr key={e.id}><td>{e.title}<div className="vy-muted" style={{ fontSize: 11 }}>{e.id}</div></td><td>{e.installedVersion || e.version}</td><td>{e.description}</td>
                <td>{e.installed ? <Button size="small" onClick={() => act(e.id, true)}>Delete</Button> : <Button size="small" appearance="primary" onClick={() => act(e.id, false)}>Add</Button>}</td></tr>))
              : <tr><td colSpan={4} className="vy-muted">No extensions installed.</td></tr>}</tbody></table>)}
      </CapabilityContainer>
    </>
  );
}
