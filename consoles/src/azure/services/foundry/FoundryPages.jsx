/* Foundry hub pages built on engines that already exist: Agents (Assistants API, core/azure_openai_agents_core.py) and Content filters
 * (Microsoft.CognitiveServices raiPolicies, enforced on deployments by core/ai_models_core.py over the guardrails engine).
 * NotInScope is the explicit, reasoned panel for the Foundry products Vyomi does not simulate (never a bare "Coming soon"). */
import { useEffect, useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select, Tab, TabList, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular } from "@fluentui/react-icons";
import { restJson } from "../../../common/wire.js";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorBar, InfoBar, Loading } from "../../kit/common.jsx";
import { ARM, listDeployments, MODEL_KINDS, putDeployment } from "../cognitiveservices/api.js";
import * as hub from "./api.js";
import { RichMessage, RunSteps, ToolBadges, ToolToggles, VectorStoresPanel, buildToolsPayload, toolsApi } from "./AgentTools.jsx";

const AV = "2024-05-01-preview";
const e = encodeURIComponent;
const FKIND = { OpenAI: "Azure OpenAI", AIServices: "Foundry" };

/** Account picker over the model-serving accounts (OpenAI / AIServices). */
function useModelAccounts() {
  const q = useAsync(async () => (await hub.listAccounts()).filter((a) => MODEL_KINDS.includes(a.kind)), []);
  const [sel, setSel] = useState("");
  const list = q.data || [];
  useEffect(() => { if (!sel && list.length) setSel(`${list[0].resourceGroup}/${list[0].name}`); }, [list.length]);
  const [rg, name] = sel.split("/");
  const picker = (
    <Field label="Resource" style={{ maxWidth: 420, marginBottom: 12 }}>
      <Select value={sel} onChange={(_, d) => setSel(d.value)} aria-label="Resource">
        {!list.length && <option value="">No Azure OpenAI or Foundry resource</option>}
        {list.map((a) => <option key={a.id} value={`${a.resourceGroup}/${a.name}`}>{a.name} ({FKIND[a.kind]})</option>)}
      </Select>
    </Field>
  );
  return { loading: q.loading && !q.data, empty: !q.loading && !list.length, rg, name, picker };
}
const NoAccount = () => <InfoBar>Create an <Link href="#/cognitiveservices/create">Azure OpenAI or Foundry resource</Link> first. This page works on a resource that serves models.</InfoBar>;

// ── Agents (Assistants API) ────────────────────────────────────────────────────────────
const agents = {
  list: () => restJson("GET", "/openai/assistants", { query: { "api-version": AV, limit: 100 }, headers: { "api-key": "console" } }).then((r) => r.data || []),
  create: (body) => restJson("POST", "/openai/assistants", { query: { "api-version": AV }, body, headers: { "api-key": "console" } }),
  remove: (id) => restJson("DELETE", `/openai/assistants/${e(id)}`, { query: { "api-version": AV }, headers: { "api-key": "console" } }),
  post: (path, body) => restJson("POST", `/openai${path}`, { query: { "api-version": AV }, body, headers: { "api-key": "console" } }),
  get: (path, query = {}) => restJson("GET", `/openai${path}`, { query: { "api-version": AV, ...query }, headers: { "api-key": "console" } }),
};

export function AgentsPage() {
  const notify = useNotify();
  const acct = useModelAccounts();
  const list = useAsync(() => agents.list(), []);
  const deps = useAsync(async () => (acct.name ? (await listDeployments(acct.rg, acct.name)).map((d) => d.name) : []), [acct.rg, acct.name]);
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ name: "", model: "", instructions: "You are a helpful assistant." });
  const [tv, setTv] = useState({ ci: false, fs: false, ciFiles: [], vs: "", newVs: "", fsFiles: [] });
  const [tab, setTab] = useState("agents");
  const stores = useAsync(() => toolsApi.stores().catch(() => []), [adding]);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState(null);
  const create = async () => {
    setErr(null);
    setCreating(true);
    try {
      const extra = await buildToolsPayload(tv);
      await agents.create({ name: f.name, model: f.model, instructions: f.instructions, tools: [], ...extra });
      notify.success(`Agent '${f.name}' was created.`, "Create succeeded"); setAdding(false); setTv({ ci: false, fs: false, ciFiles: [], vs: "", newVs: "", fsFiles: [] }); list.reload();
    } catch (x) { setErr(x); } finally { setCreating(false); }
  };
  if (acct.loading) return <Loading />;
  return (
    <div className="vy-page" data-testid="foundry-agents">
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} style={{ marginBottom: 8 }}><Tab value="agents">Agents</Tab><Tab value="stores">Vector stores</Tab></TabList>
      {tab === "stores" ? <VectorStoresPanel /> : <>
      {acct.empty ? <NoAccount /> : acct.picker}
      <div className="vy-cmdbar" role="toolbar" aria-label="Agent commands">
        <Button appearance="primary" icon={<Add20Regular />} disabled={acct.empty} onClick={() => { setF({ ...f, model: (deps.data || [])[0] || "" }); setAdding(true); }}>New agent</Button>
        <Button appearance="subtle" icon={<ArrowClockwise20Regular />} onClick={list.reload}>Refresh</Button>
      </div>
      <ErrorBar error={list.error} />
      <Table size="small" aria-label="Agents"><TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>ID</TableHeaderCell><TableHeaderCell>Model</TableHeaderCell><TableHeaderCell>Tools</TableHeaderCell><TableHeaderCell style={{ width: 60 }} /></TableRow></TableHeader>
        <TableBody>{(list.data || []).map((a) => (
          <TableRow key={a.id}><TableCell><Link as="button" onClick={() => setOpen(a)}>{a.name || "(unnamed)"}</Link></TableCell><TableCell>{a.id}</TableCell><TableCell>{a.model}</TableCell><TableCell><ToolBadges agent={a} /></TableCell>
            <TableCell><Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${a.name}`} onClick={async () => { try { await agents.remove(a.id); if (open?.id === a.id) setOpen(null); notify.success(`Deleted agent '${a.name}'.`, "Delete succeeded"); } catch (x) { notify.error(x, "Delete failed"); } list.reload(); }} /></TableCell></TableRow>))}
          {!list.loading && !(list.data || []).length && <TableRow><TableCell colSpan={5}>No agents yet. An agent is an assistant (instructions + a model deployment) you can chat with, or call through the Assistants API of the openai SDK.</TableCell></TableRow>}</TableBody></Table>
      {open && <AgentChat agent={open} />}
      </>}
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="New agent"><DialogBody><DialogTitle>New agent</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Field label="Agent name" required><Input value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} aria-label="Agent name" /></Field>
            <Field label="Deployment" required><Select value={f.model} onChange={(_, d) => setF({ ...f, model: d.value })} aria-label="Deployment">
              {(deps.data || []).length ? deps.data.map((n) => <option key={n} value={n}>{n}</option>) : <option value="">Deploy a model on the resource first</option>}</Select></Field>
            <Field label="Instructions"><Textarea rows={4} value={f.instructions} onChange={(_, d) => setF({ ...f, instructions: d.value })} aria-label="Instructions" /></Field>
            <ToolToggles value={tv} onChange={setTv} stores={stores.data || []} />
            <ErrorBar error={err} title="Failed to create the agent" /></div></DialogContent>
          <DialogActions><Button appearance="primary" disabled={!f.name || !f.model || creating || (tv.fs && !tv.vs && !(tv.fsFiles || []).length)} onClick={create}>{creating ? "Creating..." : "Create"}</Button><Button onClick={() => setAdding(false)}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>
    </div>
  );
}

/** Chat with an agent: thread + message + run + messages, exactly the SDK calls. */
function AgentChat({ agent }) {
  const [thread, setThread] = useState(null);
  const [log, setLog] = useState([]);
  const [steps, setSteps] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  useEffect(() => { setThread(null); setLog([]); setSteps([]); setErr(null); }, [agent.id]);
  const send = async () => {
    setBusy(true); setErr(null);
    try {
      const t = thread || (await agents.post("/threads", {})).id; setThread(t);
      await agents.post(`/threads/${t}/messages`, { role: "user", content: text });
      let run = await agents.post(`/threads/${t}/runs`, { assistant_id: agent.id });
      for (let i = 0; i < 60 && ["queued", "in_progress"].includes(run.status); i++) { await new Promise((r) => setTimeout(r, 700)); run = await agents.get(`/threads/${t}/runs/${run.id}`); }
      const msgs = (await agents.get(`/threads/${t}/messages`, { order: "asc" })).data || [];
      setLog(msgs);
      setSteps(await toolsApi.steps(t, run.id).catch(() => []));
      if (run.status !== "completed") setErr({ message: `Run ${run.status}${run.last_error ? `: ${run.last_error.message}` : ""}` });
      setText("");
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <section style={{ marginTop: 20, border: "1px solid var(--colorNeutralStroke2, #ddd)", padding: 16 }} data-testid="agent-chat">
      <h3 style={{ marginTop: 0 }}>Agent playground: {agent.name} <span style={{ fontWeight: 400, fontSize: 12 }}>({agent.model})</span></h3>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
        {log.map((m, i) => <div key={m.id || i} style={{ background: m.role === "user" ? "var(--colorBrandBackground2, #eef)" : "var(--colorNeutralBackground3, #f5f5f5)", padding: 8 }}><b>{m.role}</b>: <RichMessage m={m} /></div>)}
        <RunSteps steps={steps} />
      </div>
      <ErrorBar error={err} title="Run failed" />
      <div style={{ display: "flex", gap: 8 }}>
        <Input style={{ flex: 1 }} value={text} onChange={(_, d) => setText(d.value)} aria-label="Message" placeholder="Ask the agent" onKeyDown={(k) => k.key === "Enter" && text && !busy && send()} />
        <Button appearance="primary" disabled={!text || busy} onClick={send}>{busy ? "Running..." : "Send"}</Button>
      </div>
    </section>
  );
}

// ── Content filters (raiPolicies) ──────────────────────────────────────────────────────
const FILTERS = [["Hate", true], ["Sexual", true], ["Violence", true], ["Jailbreak", false]];
const LEVELS = ["Low", "Medium", "High"];
const rai = (rg, name) => `${ARM.path(rg, name)}/raiPolicies`;

export function ContentFiltersPage() {
  const notify = useNotify();
  const acct = useModelAccounts();
  const list = useAsync(async () => (acct.name ? (await restJson("GET", rai(acct.rg, acct.name), { query: { "api-version": ARM.apiVersion } })).value || [] : []), [acct.rg, acct.name]);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [lv, setLv] = useState({ Hate: "Medium", Sexual: "Medium", Violence: "Medium", Jailbreak: "Medium" });
  const [on, setOn] = useState({ Hate: true, Sexual: true, Violence: true, Jailbreak: true });
  const [err, setErr] = useState(null);
  const deps = useAsync(async () => (acct.name ? await listDeployments(acct.rg, acct.name) : []), [acct.rg, acct.name]);
  const [assign, setAssign] = useState(null);   // {policy, dep}
  const doAssign = async () => {
    try {
      const d = (deps.data || []).find((x) => x.name === assign.dep);
      await putDeployment(acct.rg, acct.name, d.name, { sku: d.sku, properties: { model: d.properties.model, raiPolicyName: assign.policy } });
      notify.success(`Deployment '${d.name}' now uses the content filter '${assign.policy}'.`, "Assignment succeeded"); setAssign(null); deps.reload();
    } catch (x) { notify.error(x, "Assignment failed"); }
  };
  const create = async () => {
    setErr(null);
    const contentFilters = FILTERS.flatMap(([n, both]) => (on[n] ? [{ name: n, severityThreshold: lv[n], blocking: true, enabled: true, source: "Prompt" }, ...(both ? [{ name: n, severityThreshold: lv[n], blocking: true, enabled: true, source: "Completion" }] : [])] : []));
    try {
      await restJson("PUT", `${rai(acct.rg, acct.name)}/${e(name)}`, { query: { "api-version": ARM.apiVersion }, body: { properties: { mode: "Blocking", basePolicyName: "Microsoft.Default", contentFilters } } });
      notify.success(`Content filter '${name}' was created. Assign it to a deployment to enforce it.`, "Create succeeded"); setAdding(false); setName(""); list.reload();
    } catch (x) { setErr(x); }
  };
  if (acct.loading) return <Loading />;
  return (
    <div className="vy-page" data-testid="foundry-filters">
      {acct.empty ? <NoAccount /> : acct.picker}
      <div className="vy-cmdbar" role="toolbar" aria-label="Content filter commands">
        <Button appearance="primary" icon={<Add20Regular />} disabled={acct.empty} onClick={() => setAdding(true)}>Create content filter</Button>
        <Button appearance="subtle" icon={<ArrowClockwise20Regular />} onClick={list.reload}>Refresh</Button>
      </div>
      <ErrorBar error={list.error} />
      <Table size="small" aria-label="Content filters"><TableHeader><TableRow><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell><TableHeaderCell>Filters</TableHeaderCell><TableHeaderCell style={{ width: 110 }} /></TableRow></TableHeader>
        <TableBody>{(list.data || []).map((p) => {
          const sys = p.properties?.type === "SystemManaged"; const cf = p.properties?.contentFilters || [];
          return (
            <TableRow key={p.name}><TableCell>{p.name}</TableCell><TableCell>{sys ? "Microsoft default (not enforced by Vyomi)" : "Custom (enforced)"}</TableCell>
              <TableCell>{sys ? "-" : [...new Set(cf.map((f) => `${f.name}: ${f.severityThreshold || "on"}`))].join(", ") || "none"}</TableCell>
              <TableCell style={{ whiteSpace: "nowrap" }}>{!sys && <Button size="small" appearance="subtle" onClick={() => setAssign({ policy: p.name, dep: (deps.data || [])[0]?.name || "" })}>Assign</Button>}{!sys && <Button size="small" appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${p.name}`} onClick={async () => { try { await restJson("DELETE", `${rai(acct.rg, acct.name)}/${e(p.name)}`, { query: { "api-version": ARM.apiVersion } }); notify.success(`Deleted '${p.name}'.`, "Delete succeeded"); } catch (x) { notify.error(x, "Delete failed"); } list.reload(); }} />}</TableCell></TableRow>);
        })}</TableBody></Table>
      <InfoBar>A custom content filter is enforced on every deployment that names it (set the filter on the deployment, or call the deployments API with raiPolicyName). Blocked prompts return HTTP 400 content_filter; blocked completions return finish_reason content_filter. Self-harm and protected-material filters are not modelled; the engine matches keyword lists and the local embedding model, so treat it as a development stand-in, not a safety guarantee.</InfoBar>
      <Dialog open={!!assign} onOpenChange={(_, d) => !d.open && setAssign(null)}>
        <DialogSurface aria-label="Assign content filter"><DialogBody><DialogTitle>Assign content filter {assign?.policy}</DialogTitle>
          <DialogContent><Field label="Deployment"><Select value={assign?.dep || ""} onChange={(_, d) => setAssign({ ...assign, dep: d.value })} aria-label="Deployment">
            {(deps.data || []).length ? deps.data.map((d) => <option key={d.name} value={d.name}>{d.name} ({d.properties?.raiPolicyName || "default"})</option>) : <option value="">No deployments on this resource</option>}</Select></Field></DialogContent>
          <DialogActions><Button appearance="primary" disabled={!assign?.dep} onClick={doAssign}>Assign</Button><Button onClick={() => setAssign(null)}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Create content filter"><DialogBody><DialogTitle>Create content filter</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Field label="Filter name" required><Input value={name} onChange={(_, d) => setName(d.value)} aria-label="Filter name" /></Field>
            {FILTERS.map(([n, both]) => (
              <div key={n} style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <Checkbox checked={on[n]} onChange={(_, d) => setOn({ ...on, [n]: !!d.checked })} label={`${n}${both ? "" : " (prompt shield)"}`} />
                <Select disabled={!on[n]} value={lv[n]} onChange={(_, d) => setLv({ ...lv, [n]: d.value })} aria-label={`${n} threshold`}>{LEVELS.map((l) => <option key={l}>{l}</option>)}</Select>
              </div>))}
            <ErrorBar error={err} title="Failed to create the content filter" /></div></DialogContent>
          <DialogActions><Button appearance="primary" disabled={!name} onClick={create}>Create</Button><Button onClick={() => setAdding(false)}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>
    </div>
  );
}

// ── Explicit, reasoned out-of-scope panel ──────────────────────────────────────────────
export function NotInScope({ title, reason, instead }) {
  return (
    <div className="vy-page" data-testid="not-in-scope" data-vyomi-not-in-scope={title}>
      <section style={{ border: "1px solid var(--colorNeutralStroke2, #ddd)", padding: 20, maxWidth: 720 }}>
        <h2 style={{ marginTop: 0 }}>{title}: not in scope for Vyomi</h2>
        <p>{reason}</p>
        {instead && <p><b>Use instead:</b> {instead}</p>}
      </section>
    </div>
  );
}
