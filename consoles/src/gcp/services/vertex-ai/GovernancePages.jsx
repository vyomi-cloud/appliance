/* Agent Platform governance pages: Gateways, MCP Servers, Policies, Security (Model Armor) and Provisioned Throughput.
 * Every list / create / delete / test here is a real call on the wire (core/gcp_agentgov_core over the AgentCore gateway, Cedar policy and
 * Bedrock-guardrails engines); nothing is made up. Google publishes no API for Agent Gateway / registry / policies, so those three are Vyomi's own
 * resources and every page says so. */
import { useState } from "react";
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { restJson } from "../../../common/wire.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { useProject } from "../../project.js";
import { PageHeader, Section, ErrorAlert, KeyValue } from "../../kit/common.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { Link } from "../../link.jsx";
import ResourceList, { StateChip, Tabbed } from "./ResourceList.jsx";
import Crumbs from "./Crumbs.jsx";
import * as api from "./api.js";

const AP = { text: "Agent Platform", href: "#/vertex-ai" };
const Page = ({ title, group, groupHref, children, actions }) => (
  <Box>
    <Crumbs trail={[AP, { text: group, href: groupHref }, { text: title }]} />
    <PageHeader title={title} actions={actions} />
    {children}
  </Box>
);
const json = (method, path, body, query) => restJson(method, path, { body, query });
const EXT = "Vyomi resource: Google publishes no API for this, so the shape is Vyomi's own, backed by a real engine.";

function Modal({ title, onClose, children, actions, wide }) {
  return (
    <Dialog open onClose={() => onClose(false)} fullWidth maxWidth={wide ? "md" : "sm"} aria-label={title}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>{children}</Stack></DialogContent>
      <DialogActions>{actions}<Button onClick={() => onClose(false)}>Close</Button></DialogActions>
    </Dialog>
  );
}

const ToolsTable = ({ tools }) => (
  <ResourceTable resourceName="tools" items={tools} rowKey={(t) => t.name} filterPlaceholder="Filter tools"
    columns={[{ id: "n", header: "Tool", cell: (t) => <code>{t.name}</code> }, { id: "d", header: "Description", cell: (t) => t.description || "—" },
      { id: "s", header: "Inputs", cell: (t) => Object.keys(t.inputSchema?.properties || {}).join(", ") || "—" }]}
    empty={<Typography variant="body2" color="text.secondary">The server exposes no tools.</Typography>} />
);

/* ───────────────────────────── MCP servers (registry) ───────────────────────────── */
function ToolsDialog({ item, onClose, verb = "listTools" }) {
  const t = useAsync(() => json("POST", `/v1/${item.name}:${verb}`, {}).then((r) => r.tools || []), [item.name]);
  return (
    <Modal title={`Tools of ${item.displayName || api.shortId(item.name)}`} onClose={onClose} wide>
      <Typography variant="body2" color="text.secondary">Discovered live: an MCP initialize handshake and tools/list against {item.endpoint || "the gateway"}.</Typography>
      <ErrorAlert error={t.error} title="Could not list tools" />
      {t.loading ? <Typography variant="body2">Connecting...</Typography> : !t.error && <ToolsTable tools={t.data || []} />}
    </Modal>
  );
}

export function McpServers() {
  return (
    <Page title="MCP Servers" group="Agents" groupHref="#/vertex-ai/agent-garden">
      <Stack spacing={1.5}>
        <Alert severity="info" data-testid="gov-note">Register the MCP servers your agents may use (any streamable-HTTP MCP server). Attach one to a Gateway to expose its tools behind the gateway's auth and policy. {EXT} Calling a server needs network: direct on Mesh, through the allow-listed egress relay on Nano.</Alert>
        <ResourceList coll="mcpServers" title="MCP servers" singular="MCP server" regionScoped hideId cap="gcp.vertex-ai.agent-gateway"
          fields={[{ key: "id", label: "Server ID", helper: "Lowercase letters, digits, hyphens" }, { key: "displayName", label: "Display name" }, { key: "endpoint", label: "Endpoint URL", helper: "https://host/mcp" },
            { key: "description", label: "Description" }, { key: "header", label: "Auth header (optional)", helper: "e.g. Authorization or X-Api-Key" }, { key: "value", label: "Auth header value (optional)", helper: "Stored, never shown again" }]}
          build={(v) => ({ idKey: "mcpServerId", id: v.id || undefined, body: { displayName: v.displayName || v.id, endpoint: v.endpoint, description: v.description,
            ...(v.value ? { authentication: { apiKey: { header: v.header || "Authorization", value: v.value } } } : {}) } })}
          columns={[{ id: "ep", header: "Endpoint", cell: (i) => <code>{i.endpoint}</code> }, { id: "auth", header: "Auth", cell: (i) => (i.authentication?.apiKey ? `Header ${i.authentication.apiKey.header}` : "None") },
            { id: "st", header: "State", cell: (i) => <StateChip s={i.state} /> }]}
          actions={[{ label: "List tools", dialog: ({ item, onClose }) => <ToolsDialog item={item} onClose={onClose} /> }]} />
      </Stack>
    </Page>
  );
}

/* ───────────────────────────── Gateways ───────────────────────────── */
export function Gateways() {
  return (
    <Page title="Gateways" group="Govern" groupHref="#/vertex-ai/agent-registry">
      <Stack spacing={1.5}>
        <Alert severity="info" data-testid="gov-note">A gateway is one MCP endpoint in front of your tool servers, with its own auth and an optional Cedar policy. It runs on the AgentCore gateway engine, so the same endpoint also shows in the AWS console of this account (prefixed gcp-). {EXT}</Alert>
        <ResourceList coll="agentGateways" title="Gateways" singular="gateway" regionScoped hideId cap="gcp.vertex-ai.agent-gateway"
          fields={[{ key: "id", label: "Gateway ID", helper: "Lowercase letters, digits, hyphens" }, { key: "displayName", label: "Display name" }, { key: "description", label: "Description" },
            { key: "auth", label: "Authorization", options: [{ value: "NONE", label: "None (open)" }, { value: "JWT", label: "JWT (OIDC issuer)" }], default: "NONE" },
            { key: "discoveryUrl", label: "OIDC discovery URL (JWT only)", helper: "https://issuer/.well-known/openid-configuration" }, { key: "audiences", label: "Allowed audiences (comma separated, JWT only)" }]}
          build={(v) => ({ idKey: "agentGatewayId", id: v.id || undefined, body: { displayName: v.displayName || v.id, description: v.description,
            authorization: v.auth === "JWT" ? { type: "JWT", jwt: { discoveryUrl: v.discoveryUrl, ...(v.audiences ? { allowedAudiences: v.audiences.split(",").map((x) => x.trim()).filter(Boolean) } : {}) } } : { type: "NONE" } } })}
          href={(i) => `#/vertex-ai/gateways/${api.pname(i.name).location}/${api.shortId(i.name)}`}
          columns={[{ id: "st", header: "State", cell: (i) => <StateChip s={i.state} /> }, { id: "auth", header: "Authorization", cell: (i) => i.authorization?.type || "NONE" },
            { id: "srv", header: "MCP servers", cell: (i) => (i.attachedMcpServers || []).length }, { id: "pol", header: "Policy", cell: (i) => (i.attachedPolicy ? api.shortId(i.attachedPolicy) : "—") }]} />
      </Stack>
    </Page>
  );
}

function CallTool({ gwName, tools }) {
  const [tool, setTool] = useState(""), [args, setArgs] = useState("{}"), [res, setRes] = useState(null), [err, setErr] = useState(null);
  const go = async () => { setErr(null); setRes(null); try { setRes(await json("POST", `/v1/${gwName}:callTool`, { tool, arguments: JSON.parse(args || "{}") })); } catch (e) { setErr(e); } };
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
        {tools.length
          ? <TextField select size="small" label="Tool" value={tool} onChange={(e) => setTool(e.target.value)} sx={{ minWidth: 280 }}>{tools.map((t) => <MenuItem key={t.name} value={t.name}>{t.name}</MenuItem>)}</TextField>
          : <TextField size="small" label="Tool" value={tool} onChange={(e) => setTool(e.target.value)} sx={{ minWidth: 280 }} helperText="No tool is listed (none attached, or the policy hides them): type server___tool" />}
        <TextField size="small" label="Arguments (JSON)" value={args} onChange={(e) => setArgs(e.target.value)} sx={{ minWidth: 300 }} />
        <Button variant="outlined" disabled={!tool} onClick={go}>Call tool</Button>
      </Stack>
      <ErrorAlert error={err} />
      {res && <Alert severity={res.isError ? "warning" : "success"} data-testid="call-result"><b>{res.denied ? "Denied by policy" : res.isError ? "Tool error" : "Result"}</b>: {(res.content || []).map((c) => c.text).join("\n")}</Alert>}
    </Stack>
  );
}

export function GatewayDetail({ params }) {
  const project = useProject(), notify = useNotify();
  const name = `projects/${project}/locations/${params.location}/agentGateways/${params.id}`;
  const g = useAsync(() => api.get(name), [name]);
  const servers = useAsync(() => api.list("mcpServers", { loc: params.location }), [project, params.location]);
  const policies = useAsync(() => api.list("agentPolicies", { loc: params.location }), [project, params.location]);
  const tools = useAsync(() => json("POST", `/v1/${name}:listTools`, {}).then((r) => r.tools || []), [name, g.data?.attachedMcpServers?.length]);
  const [srv, setSrv] = useState(""), [pol, setPol] = useState(""), [copied, setCopied] = useState(false);
  const act = async (verb, body, msg) => { try { await api.verb(name, verb, body); notify.success(msg); g.reload(); } catch (e) { notify.error(e); } };
  const d = g.data;
  const free = (servers.data || []).filter((s) => !(d?.attachedMcpServers || []).includes(s.name));
  return (
    <Box>
      <Crumbs trail={[AP, { text: "Govern", href: "#/vertex-ai/agent-registry" }, { text: "Gateways", href: "#/vertex-ai/gateways" }, { text: params.id }]} />
      <PageHeader title={d?.displayName || params.id} actions={<><CapabilityBadge id="gcp.vertex-ai.agent-gateway" /><Button startIcon={<RefreshIcon />} onClick={() => { g.reload(); tools.reload(); }}>Refresh</Button></>} />
      <ErrorAlert error={g.error} title="Failed to load gateway" />
      {d && (
        <Stack spacing={2.5}>
          <Section title="Details">
            <KeyValue items={[["State", <StateChip s={d.state} />], ["Protocol", (d.protocols || []).join(", ")], ["Authorization", d.authorization?.type === "JWT" ? `JWT (${d.authorization.jwt?.discoveryUrl})` : "None (open)"],
              ["MCP endpoint", <code data-testid="mcp-endpoint">{d.mcpEndpoint}</code>, <Button size="small" onClick={() => { try { navigator.clipboard.writeText(d.mcpEndpoint); } catch (_) { /* clipboard unavailable */ } setCopied(true); }}>{copied ? "Copied" : "Copy"}</Button>],
              ["AgentCore gateway", d.agentCoreGatewayId], ["Created", d.createTime]]} />
          </Section>
          <Tabbed tabs={[
            { id: "servers", label: "MCP servers", render: () => (
              <Section title="Attached MCP servers" description="Each attached server becomes a gateway target; its tools appear as <server>___<tool>.">
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1}>
                    <TextField select size="small" label="MCP server" value={srv} onChange={(e) => setSrv(e.target.value)} sx={{ minWidth: 300 }}>{free.map((s) => <MenuItem key={s.name} value={s.name}>{s.displayName} ({s.endpoint})</MenuItem>)}</TextField>
                    <Button variant="contained" disabled={!srv} onClick={async () => { await act("attachMcpServer", { mcpServer: srv }, "Attached MCP server"); setSrv(""); }}>Attach</Button>
                  </Stack>
                  {!servers.loading && !free.length && !(d.attachedMcpServers || []).length && <Alert severity="info">Register a server under <Link href="#/vertex-ai/mcp-servers">MCP Servers</Link> first.</Alert>}
                  <ResourceTable resourceName="attached servers" items={(d.attachedMcpServers || []).map((n) => ({ name: n }))} rowKey={(x) => x.name} filterPlaceholder="Filter"
                    columns={[{ id: "n", header: "MCP server", cell: (x) => api.shortId(x.name) }, { id: "a", header: "Actions", cell: (x) => <Button size="small" onClick={() => act("detachMcpServer", { mcpServer: x.name }, "Detached MCP server")}>Detach</Button> }]}
                    empty={<Typography variant="body2" color="text.secondary">No MCP server attached.</Typography>} />
                </Stack>
              </Section>) },
            { id: "tools", label: "Tools", render: () => (
              <Section title="Tool catalog" description="Live from the gateway's MCP endpoint (tools/list). Policy is applied to the calls below.">
                <Stack spacing={2}><ErrorAlert error={tools.error} />{tools.loading ? <Typography variant="body2">Loading...</Typography> : <ToolsTable tools={tools.data || []} />}<CallTool gwName={name} tools={tools.data || []} /></Stack>
              </Section>) },
            { id: "policy", label: "Policy", render: () => (
              <Section title="Policy" description="A Cedar policy decides every tool call. ENFORCE denies what no policy permits; LOG_ONLY allows and audits.">
                <Stack spacing={1.5}>
                  <Typography variant="body2">Attached: {d.attachedPolicy ? <b data-testid="attached-policy">{api.shortId(d.attachedPolicy)}</b> : "none (every call is allowed)"}</Typography>
                  <Stack direction="row" spacing={1}>
                    <TextField select size="small" label="Policy" value={pol} onChange={(e) => setPol(e.target.value)} sx={{ minWidth: 300 }}>{(policies.data || []).map((p) => <MenuItem key={p.name} value={p.name}>{p.displayName} ({p.enforcementMode})</MenuItem>)}</TextField>
                    <Button variant="contained" disabled={!pol} onClick={() => act("attachPolicy", { policy: pol }, "Attached policy")}>Attach</Button>
                    <Button disabled={!d.attachedPolicy} onClick={() => act("detachPolicy", {}, "Detached policy")}>Detach</Button>
                  </Stack>
                </Stack>
              </Section>) },
            { id: "connect", label: "Connect", render: () => (
              <Section title="Connect an MCP client" description="Any streamable-HTTP MCP client works. JSON-RPC over POST:">
                <Box component="pre" sx={{ m: 0, p: 1.5, bgcolor: "action.hover", borderRadius: 1, overflow: "auto", fontSize: 13 }} data-testid="connect-snippet">{`curl -s ${d.mcpEndpoint} \\\n  -H 'content-type: application/json' \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`}</Box>
                {d.authorization?.type === "JWT" && <Typography variant="body2" sx={{ mt: 1 }}>Add <code>-H 'authorization: Bearer &lt;id token&gt;'</code>; the token is verified against the issuer's keys.</Typography>}
              </Section>) },
          ]} />
        </Stack>)}
    </Box>
  );
}

/* ───────────────────────────── Policies ───────────────────────────── */
const SAMPLE = 'permit(principal, action == AgentCore::Action::"<server>___<tool>", resource);';

function TestPolicyDialog({ item, onClose }) {
  const [principal, setPrincipal] = useState("alice"), [tool, setTool] = useState(""), [args, setArgs] = useState("{}"), [res, setRes] = useState(null), [err, setErr] = useState(null);
  const go = async () => { setErr(null); setRes(null); try { setRes(await json("POST", `/v1/${item.name}:test`, { principal, tool, arguments: JSON.parse(args || "{}") })); } catch (e) { setErr(e); } };
  return (
    <Modal title={`Test policy ${item.displayName}`} onClose={onClose} actions={<Button variant="contained" disabled={!tool} onClick={go}>Evaluate</Button>}>
      <Typography variant="body2" color="text.secondary">Evaluates this policy with the real Cedar engine as if the principal called the tool.</Typography>
      <TextField size="small" label="Principal (JWT subject)" value={principal} onChange={(e) => setPrincipal(e.target.value)} />
      <TextField size="small" label="Tool (server___tool)" value={tool} onChange={(e) => setTool(e.target.value)} />
      <TextField size="small" label="Arguments (JSON, context.input)" value={args} onChange={(e) => setArgs(e.target.value)} />
      <ErrorAlert error={err} />
      {res && <Alert severity={res.decision === "ALLOW" ? "success" : "warning"} data-testid="policy-decision"><b>{res.decision}</b>: {res.reason}</Alert>}
    </Modal>
  );
}

function AttachPolicyDialog({ item, onClose }) {
  const notify = useNotify();
  const gws = useAsync(() => api.list("agentGateways", { loc: api.pname(item.name).location }), [item.name]);
  const [gw, setGw] = useState(""), [err, setErr] = useState(null);
  const go = async () => { try { await api.verb(gw, "attachPolicy", { policy: item.name }); notify.success("Attached policy to the gateway"); onClose(true); } catch (e) { setErr(e); } };
  return (
    <Modal title={`Attach ${item.displayName} to a gateway`} onClose={onClose} actions={<Button variant="contained" disabled={!gw} onClick={go}>Attach</Button>}>
      <Typography variant="body2" color="text.secondary">A gateway has one policy; attaching replaces the current one.</Typography>
      <TextField select size="small" label="Gateway" value={gw} onChange={(e) => setGw(e.target.value)}>{(gws.data || []).map((g) => <MenuItem key={g.name} value={g.name}>{g.displayName}</MenuItem>)}</TextField>
      <ErrorAlert error={err} />
    </Modal>
  );
}

export function Policies() {
  return (
    <Page title="Policies" group="Govern" groupHref="#/vertex-ai/agent-registry">
      <Stack spacing={1.5}>
        <Alert severity="info" data-testid="gov-note">A policy is a Cedar policy that decides which agents and users may call which gateway tools, evaluated by the real Cedar engine on every call. {EXT} Cedar runs as cedarpy on Mesh and the offline appliance and as the same Cedar core compiled to WebAssembly on Nano; if the evaluator is not loaded an ENFORCE gateway denies every call (fail closed).</Alert>
        <ResourceList coll="agentPolicies" title="Policies" singular="policy" regionScoped hideId cap="gcp.vertex-ai.agent-policies"
          fields={[{ key: "id", label: "Policy ID", helper: "Lowercase letters, digits, hyphens" }, { key: "displayName", label: "Display name" }, { key: "description", label: "Description" },
            { key: "mode", label: "Enforcement", options: ["ENFORCE", "LOG_ONLY"], default: "ENFORCE" }, { key: "cedar", label: "Cedar policy", multiline: true, default: SAMPLE, helper: "Action is AgentCore::Action::\"<server>___<tool>\"; claims are principal tags; arguments are context.input" }]}
          build={(v) => ({ idKey: "agentPolicyId", id: v.id || undefined, body: { displayName: v.displayName || v.id, description: v.description, enforcementMode: v.mode, cedarPolicy: v.cedar } })}
          columns={[{ id: "mode", header: "Enforcement", cell: (i) => <Chip size="small" variant="outlined" label={i.enforcementMode} /> }, { id: "gw", header: "Attached gateways", cell: (i) => (i.attachedGateways || []).map(api.shortId).join(", ") || "—" },
            { id: "st", header: "State", cell: (i) => <StateChip s={i.state} /> }, { id: "c", header: "Cedar", cell: (i) => <code>{String(i.cedarPolicy).slice(0, 70)}{String(i.cedarPolicy).length > 70 ? "..." : ""}</code> }]}
          actions={[{ label: "Test", dialog: ({ item, onClose }) => <TestPolicyDialog item={item} onClose={onClose} /> },
            { label: "Attach to gateway", dialog: ({ item, onClose }) => <AttachPolicyDialog item={item} onClose={onClose} /> },
            { label: "Toggle ENFORCE / LOG_ONLY", run: async (item, { notify }) => { const m = item.enforcementMode === "ENFORCE" ? "LOG_ONLY" : "ENFORCE"; await json("PATCH", `/v1/${item.name}`, { enforcementMode: m }); notify.success(`Policy is now ${m}`); } }]} />
      </Stack>
    </Page>
  );
}

/* ───────────────────────────── Security: Model Armor ───────────────────────────── */
const LEVELS = [{ value: "LOW_AND_ABOVE", label: "Low and above" }, { value: "MEDIUM_AND_ABOVE", label: "Medium and above" }, { value: "HIGH", label: "High" }];
const RAI = [["DANGEROUS", "Dangerous content"], ["HATE_SPEECH", "Hate speech"], ["HARASSMENT", "Harassment"], ["SEXUALLY_EXPLICIT", "Sexually explicit"]];

function filtersOf(fc) {
  const out = [];
  (fc?.raiSettings?.raiFilters || []).forEach((f) => out.push(RAI.find((r) => r[0] === f.filterType)?.[1] || f.filterType));
  if (fc?.piAndJailbreakFilterSettings?.filterEnforcement === "ENABLED") out.push("Prompt injection and jailbreak");
  if (fc?.sdpSettings?.basicConfig?.filterEnforcement === "ENABLED") out.push("Sensitive data");
  if (fc?.maliciousUriFilterSettings?.filterEnforcement === "ENABLED") out.push("Malicious URIs");
  return out;
}

function SanitizeDialog({ item, onClose }) {
  const [kind, setKind] = useState("prompt"), [text, setText] = useState(""), [res, setRes] = useState(null), [err, setErr] = useState(null);
  const go = async () => {
    setErr(null); setRes(null);
    try {
      const r = kind === "prompt" ? await json("POST", `/v1/${item.name}:sanitizeUserPrompt`, { userPromptData: { text } }) : await json("POST", `/v1/${item.name}:sanitizeModelResponse`, { modelResponseData: { text } });
      setRes(r.sanitizationResult);
    } catch (e) { setErr(e); }
  };
  const rows = Object.entries(res?.filterResults || {}).map(([k, v]) => { const r = Object.values(v)[0]; const inner = r.inspectResult || r; return { id: k, state: inner.executionState, match: inner.matchState, detail: inner.raiFilterTypeResults ? Object.entries(inner.raiFilterTypeResults).filter(([, x]) => x.matchState === "MATCH_FOUND").map(([t, x]) => `${t} (${x.confidenceLevel})`).join(", ") : (inner.findings || []).map((f) => f.infoType).join(", ") || (inner.messageItems || []).map((m) => m.message).join(" ") }; });
  return (
    <Modal title={`Test template ${api.shortId(item.name)}`} onClose={onClose} wide actions={<Button variant="contained" disabled={!text.trim()} onClick={go}>Sanitize</Button>}>
      <Typography variant="body2" color="text.secondary">Runs the template's filters on the text (sanitizeUserPrompt / sanitizeModelResponse).</Typography>
      <TextField select size="small" label="Check as" value={kind} onChange={(e) => setKind(e.target.value)}><MenuItem value="prompt">User prompt</MenuItem><MenuItem value="response">Model response</MenuItem></TextField>
      <TextField size="small" label="Text" multiline minRows={3} value={text} onChange={(e) => setText(e.target.value)} />
      <ErrorAlert error={err} />
      {res && (
        <Stack spacing={1} data-testid="sanitize-result">
          <Alert severity={res.filterMatchState === "MATCH_FOUND" ? "warning" : "success"}><b data-testid="match-state">{res.filterMatchState === "MATCH_FOUND" ? "Match found" : "No match found"}</b></Alert>
          <ResourceTable resourceName="filter results" items={rows} rowKey={(r) => r.id} filterPlaceholder="Filter"
            columns={[{ id: "f", header: "Filter", cell: (r) => r.id }, { id: "e", header: "Execution", cell: (r) => r.state }, { id: "m", header: "Match", cell: (r) => <Chip size="small" color={r.match === "MATCH_FOUND" ? "warning" : "default"} variant="outlined" label={r.match} /> }, { id: "d", header: "Detail", cell: (r) => r.detail || "—" }]} />
        </Stack>)}
    </Modal>
  );
}

function Findings() {
  const project = useProject();
  const t = useAsync(() => api.list("templates", { loc: "-" }), [project]);
  const [sel, setSel] = useState("");
  const name = sel || t.data?.[0]?.name || "";
  const f = useAsync(() => (name ? json("POST", `/v1/${name}:recentFindings`, {}).then((r) => r.findings || []) : Promise.resolve([])), [name]);
  return (
    <Section title="Recent findings" description="The last sanitize results this simulator served for a template (Google writes these to Cloud Logging and Security Command Center; Vyomi keeps the latest 200 here).">
      <Stack spacing={1.5}>
        <Stack direction="row" spacing={1}><TextField select size="small" label="Template" value={name} onChange={(e) => setSel(e.target.value)} sx={{ minWidth: 280 }}>{(t.data || []).map((x) => <MenuItem key={x.name} value={x.name}>{api.shortId(x.name)}</MenuItem>)}</TextField><Button startIcon={<RefreshIcon />} onClick={() => { t.reload(); f.reload(); }}>Refresh</Button></Stack>
        <ResourceTable resourceName="findings" items={f.data || []} rowKey={(x) => x.time + x.kind} loading={f.loading} filterPlaceholder="Filter"
          columns={[{ id: "t", header: "Time", cell: (x) => x.time }, { id: "k", header: "Checked", cell: (x) => (x.kind === "userPrompt" ? "User prompt" : "Model response") }, { id: "m", header: "Result", cell: (x) => <Chip size="small" variant="outlined" color={x.matchState === "MATCH_FOUND" ? "warning" : "default"} label={x.matchState === "MATCH_FOUND" ? "Match found" : "No match"} /> }, { id: "f", header: "Filters matched", cell: (x) => (x.matched || []).join(", ") || "—" }]}
          empty={<Typography variant="body2" color="text.secondary">Nothing sanitized yet. Use Test on a template.</Typography>} />
      </Stack>
    </Section>
  );
}

export function Security() {
  const rai = Object.fromEntries(RAI.map(([k]) => [k, { key: "rai_" + k, label: RAI.find((r) => r[0] === k)[1], type: "bool", default: k === "DANGEROUS" }]));
  return (
    <Page title="Security" group="Govern" groupHref="#/vertex-ai/agent-registry">
      <Stack spacing={2}>
        <Alert severity="info" data-testid="gov-note">Model Armor templates screen prompts and responses (modelarmor.googleapis.com templates, sanitizeUserPrompt, sanitizeModelResponse). Detection runs on the Bedrock Guardrails engine - keyword and local-embedding scoring and regex PII - so it is toy-grade, not Google's models. Malicious-URI detection (Safe Browsing) and Cloud DLP templates are not simulated and report EXECUTION_SKIPPED.</Alert>
        <ResourceList coll="templates" title="Model Armor templates" singular="template" regionScoped hideId cap="gcp.vertex-ai.model-armor"
          fields={[{ key: "id", label: "Template ID", helper: "Lowercase letters, digits, hyphens" }, ...Object.values(rai), { key: "raiLevel", label: "Responsible AI confidence", options: LEVELS, default: "MEDIUM_AND_ABOVE" },
            { key: "pi", label: "Prompt injection and jailbreak detection", type: "bool", default: true }, { key: "piLevel", label: "Prompt injection confidence", options: LEVELS, default: "MEDIUM_AND_ABOVE" },
            { key: "sdp", label: "Sensitive data protection (basic)", type: "bool", default: true }, { key: "uri", label: "Malicious URI detection", type: "bool", default: false }]}
          build={(v) => ({ idKey: "templateId", id: v.id || undefined, body: { filterConfig: {
            ...(RAI.some(([k]) => v["rai_" + k]) ? { raiSettings: { raiFilters: RAI.filter(([k]) => v["rai_" + k]).map(([k]) => ({ filterType: k, confidenceLevel: v.raiLevel })) } } : {}),
            ...(v.pi ? { piAndJailbreakFilterSettings: { filterEnforcement: "ENABLED", confidenceLevel: v.piLevel } } : {}),
            ...(v.sdp ? { sdpSettings: { basicConfig: { filterEnforcement: "ENABLED" } } } : {}),
            ...(v.uri ? { maliciousUriFilterSettings: { filterEnforcement: "ENABLED" } } : {}) } } })}
          nameOf={(i) => api.shortId(i.name)}
          columns={[{ id: "f", header: "Filters", cell: (i) => filtersOf(i.filterConfig).join(", ") || "—" }]}
          actions={[{ label: "Test", dialog: ({ item, onClose }) => <SanitizeDialog item={item} onClose={onClose} /> }]} />
        <Findings />
      </Stack>
    </Page>
  );
}

/* ───────────────────────────── Provisioned Throughput ───────────────────────────── */
const TERMS = [["ONE_WEEK", "1 week"], ["ONE_MONTH", "1 month"], ["THREE_MONTHS", "3 months"], ["ONE_YEAR", "1 year"]];
export function ProvisionedThroughput() {
  return (
    <Page title="Provisioned Throughput" group="Models" groupHref="#/vertex-ai/model-garden">
      <Stack spacing={1.5}>
        <Alert severity="warning" data-testid="pt-note"><b>Bookkeeping only.</b> An order records a model, generative model units and a commitment term. Nothing is reserved, enforced or billed: a local model has no shared serving capacity to commit. Use it to rehearse the purchase flow and to keep your own plan next to your resources. {EXT}</Alert>
        <ResourceList coll="provisionedThroughputs" title="Provisioned Throughput orders" singular="order" regionScoped hideId cap="gcp.vertex-ai.provisioned-throughput" createLabel="Purchase Provisioned Throughput"
          fields={[{ key: "id", label: "Order ID", helper: "Lowercase letters, digits, hyphens" }, { key: "displayName", label: "Display name" }, { key: "model", label: "Model", default: "publishers/google/models/gemini-2.0-flash", helper: "A publisher model or a tuned model resource name" },
            { key: "units", label: "Generative model units", default: "1" }, { key: "term", label: "Commitment term", options: TERMS.map(([value, label]) => ({ value, label })), default: "ONE_MONTH" }]}
          build={(v) => ({ idKey: "provisionedThroughputId", id: v.id || undefined, body: { displayName: v.displayName || v.id, model: v.model, generativeModelUnits: Number(v.units) || 1, commitmentTerm: v.term } })}
          columns={[{ id: "m", header: "Model", cell: (i) => String(i.model).split("/").pop() }, { id: "u", header: "Units", cell: (i) => i.generativeModelUnits }, { id: "t", header: "Term", cell: (i) => TERMS.find((t) => t[0] === i.commitmentTerm)?.[1] || i.commitmentTerm },
            { id: "s", header: "State", cell: (i) => <StateChip s={i.state} /> }, { id: "e", header: "Ends", cell: (i) => api.when(i.endTime) }]} />
      </Stack>
    </Page>
  );
}
