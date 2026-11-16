/* Agent Platform pages (Vertex AI renamed): Overview, Agent Studio, Agent Garden, Tutorials, Deployments.
 * Layout follows the native console captures; resources come from the real aiplatform REST wire. */
import { useState } from "react";
import { Alert, Box, Button, Card, CardContent, Chip, Grid, IconButton, InputAdornment, Menu, MenuItem, Stack, TextField, Tooltip, Typography } from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/esm/AutoAwesome.js";
import SendIcon from "@mui/icons-material/esm/Send.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import SearchIcon from "@mui/icons-material/esm/Search.js";
import RocketLaunchIcon from "@mui/icons-material/esm/RocketLaunchOutlined.js";
import BuildIcon from "@mui/icons-material/esm/BuildOutlined.js";
import WidgetsIcon from "@mui/icons-material/esm/WidgetsOutlined.js";
import GridViewIcon from "@mui/icons-material/esm/GridViewOutlined.js";
import SettingsIcon from "@mui/icons-material/esm/SettingsOutlined.js";
import ArticleIcon from "@mui/icons-material/esm/ArticleOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import { useProject } from "../../project.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { Link } from "../../link.jsx";
import Crumbs from "./Crumbs.jsx";
import ResourceList from "./ResourceList.jsx";
import { AI_CHAT, DEFAULT_CHAT } from "../../../common/aiModels.js";
import { GARDEN, USE_CASES, TOOLS, CAPS, TUTORIAL_VIDEOS, TUTORIAL_DOCS, OVERVIEW_GROUPS } from "./content.js";
import * as api from "./api.js";

const SNIPPET = `from google import genai
from google.genai.types import HttpOptions

client = genai.Client(http_options=HttpOptions(api_version="v1"))
response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents='How does AI work?',
)
print(response.text)`;

const Page = ({ crumbs, children, flush }) => (
  <Box><Crumbs trail={crumbs} /><Box sx={{ ...(flush ? {} : { maxWidth: 1000, mx: "auto", pt: 4 }) }}>{children}</Box></Box>
);

/* ── Overview (landing) ── */
export function Overview() {
  const project = useProject();
  const counts = useAsync(() => Promise.all(api.COLLECTIONS.map(async ([c]) => { try { return (await api.list(c)).length; } catch { return 0; } })), [project]);
  return (
    <Page crumbs={[{ text: "Agent Platform" }]}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
        <AutoAwesomeIcon sx={{ color: "#4285f4" }} /><Typography fontSize={20}>Gemini Enterprise</Typography>
        <Box sx={{ flex: 1 }} /><Link href="#/vertex-ai/tutorials">Video tutorial</Link>
      </Stack>
      <Typography variant="h1" component="h1" sx={{ fontSize: 36, fontWeight: 400, mb: 1 }}>Welcome to Agent Platform</Typography>
      <Typography variant="body2" sx={{ mb: 4 }}>Vertex AI is now Agent Platform. Build enterprise-grade agents with the latest models.</Typography>
      <Card variant="outlined" sx={{ borderRadius: 4, mb: 4 }}><CardContent sx={{ p: 4 }}>
        <Typography variant="h2" sx={{ fontSize: 22, fontWeight: 400, mb: 1 }}>Get started with Generative AI</Typography>
        <Typography variant="body2" sx={{ mb: 2, maxWidth: 340 }}>Access multimodal capabilities to generate text, code, and images with Gemini or your chosen model.</Typography>
        <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}><Button variant="contained" disabled sx={{ borderRadius: 5 }}>Enable APIs</Button><Link href="#/vertex-ai/tutorials">View setup docs</Link></Stack>
        <Typography variant="caption">Python</Typography>
        <Box component="pre" data-testid="overview-snippet" sx={{ m: 0, mt: 1, fontSize: 13, whiteSpace: "pre-wrap" }}>{SNIPPET}</Box>
      </CardContent></Card>
      {OVERVIEW_GROUPS.map(([group, items]) => (
        <Box key={group} sx={{ mb: 4 }}>
          <Typography variant="h2" sx={{ fontSize: 20, fontWeight: 400, mb: 1.5 }}>{group}</Typography>
          <Grid container spacing={2}>{items.map(([t, d, href]) => (
            <Grid item xs={12} sm={6} md={4} key={t}><Card variant="outlined" component="a" href={href} sx={{ display: "block", height: "100%", textDecoration: "none", color: "inherit", borderRadius: 3, bgcolor: "action.hover" }}>
              <CardContent><Typography fontWeight={500}>{t}</Typography><Typography variant="body2" color="text.secondary">{d}</Typography></CardContent></Card></Grid>))}</Grid>
        </Box>))}
      <Typography variant="h2" sx={{ fontSize: 20, fontWeight: 400, mb: 1.5 }}>Resources in this project</Typography>
      <Grid container spacing={2} sx={{ mb: 4 }}>
        {api.COLLECTIONS.map(([c, label, href], i) => (
          <Grid item xs={6} md={3} key={c}><Card variant="outlined" component="a" href={`#/vertex-ai/${href}`} data-testid={`count-${c}`} sx={{ display: "block", textDecoration: "none", color: "inherit" }}>
            <CardContent><Typography variant="h2" component="div">{counts.data ? counts.data[i] : "…"}</Typography><Typography variant="body2" color="text.secondary">{label}</Typography></CardContent></Card></Grid>))}
      </Grid>
    </Page>
  );
}

/* ── Agent Studio landing ── */
export function AgentStudio() {
  const [prompt, setPrompt] = useState("");
  const [tab, setTab] = useState("models");
  const [menu, setMenu] = useState(null);
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const project = useProject();
  const engines = useAsync(() => api.list("reasoningEngines", { loc: "us-central1" }).catch(() => []), [project]);
  const models = AI_CHAT.slice(0, 2);
  const submit = async () => {
    setBusy(true); setError(null); setOut(null);
    try { const r = await api.generate(DEFAULT_CHAT, prompt); setOut((r.candidates?.[0]?.content?.parts || []).map((p) => p.text).join("")); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const rail = (icon, text, href) => <Button component="a" href={href} startIcon={icon} sx={{ justifyContent: "flex-start", color: "text.primary", textTransform: "none", py: 1 }}>{text}</Button>;
  return (
    <Box>
      <Crumbs trail={[{ text: "Agent Platform", href: "#/vertex-ai" }, { text: "Studio" }]} />
      <Box sx={{ display: "flex", minHeight: 560 }}>
        <Stack sx={{ width: 240, p: 2, borderRight: 1, borderColor: "divider" }} data-testid="studio-rail">
          <div><Button variant="contained" color="inherit" startIcon={<AddIcon />} onClick={(e) => setMenu(e.currentTarget)} sx={{ borderRadius: 5, bgcolor: "chrome.active", boxShadow: "none", textTransform: "none", mb: 2 }}>New</Button></div>
          <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)}>
            <MenuItem component="a" href="#/vertex-ai/studio/prompt">Freeform prompt</MenuItem>
            <MenuItem component="a" href="#/vertex-ai/studio/prompt">Chat</MenuItem>
            <MenuItem component="a" href="#/vertex-ai/agent-garden">Agent from blueprint</MenuItem>
          </Menu>
          {rail(<RocketLaunchIcon />, "Agents", "#/vertex-ai/deployments")}
          {rail(<BuildIcon />, "App builder", "#/vertex-ai/app-builder")}
          {rail(<GridViewIcon />, "Gallery", "#/vertex-ai/agent-garden")}
          <Box sx={{ flex: 1 }} />
          {rail(<ArticleIcon />, "Documentation", "#/vertex-ai/tutorials")}
          {rail(<SettingsIcon />, "Settings", "#/vertex-ai/studio/prompt")}
        </Stack>
        <Stack sx={{ flex: 1, alignItems: "center", justifyContent: "center", px: 3, py: 6 }} spacing={1}>
          <Typography variant="h1" sx={{ fontSize: 36, fontWeight: 400 }}>Start building with Agent Studio</Typography>
          <Typography fontSize={20} sx={{ mb: 4 }}>Build agents and applications with the most advanced models</Typography>
          <Box sx={{ width: "100%", maxWidth: 800 }}>
            <Stack direction="row" alignItems="center" sx={{ mb: 1 }}><Typography variant="body2" sx={{ flex: 1 }}>Explore models</Typography>
              {["models", "agents"].map((t) => <Chip key={t} label={t === "models" ? "Models" : "Agents"} onClick={() => setTab(t)} color={tab === t ? "primary" : "default"} variant={tab === t ? "filled" : "outlined"} sx={{ ml: 1, border: 0 }} />)}</Stack>
            <TextField fullWidth multiline minRows={2} placeholder="Type a prompt to see what our models can do" value={prompt} onChange={(e) => setPrompt(e.target.value)}
              sx={{ "& .MuiOutlinedInput-root": { borderRadius: 4, "& fieldset": { borderColor: "primary.main", borderWidth: 2 } } }}
              InputProps={{ endAdornment: <InputAdornment position="end" sx={{ alignSelf: "flex-end" }}><Tooltip title="Submit"><span><IconButton aria-label="Submit prompt" disabled={!prompt.trim() || busy} onClick={submit}><SendIcon /></IconButton></span></Tooltip></InputAdornment> }} />
            <Typography variant="caption" color="text.secondary">Answered by {DEFAULT_CHAT} through generateContent</Typography>
            {error && <Alert severity="error" sx={{ mt: 1 }}>{error.message}</Alert>}
            {out != null && <Alert severity="success" icon={false} sx={{ mt: 1 }}><Typography data-testid="studio-output" sx={{ whiteSpace: "pre-wrap" }}>{out}</Typography></Alert>}
            {tab === "models" ? (
              <Grid container spacing={2} sx={{ mt: 1 }}>{models.map((m) => (
                <Grid item xs={12} sm={6} key={m.id}><Card variant="outlined" component="a" href={`#/vertex-ai/model-garden/${m.publisher || "google"}/${m.id}`} sx={{ display: "block", textDecoration: "none", color: "inherit", borderRadius: 4, bgcolor: "action.hover", border: 0 }}>
                  <CardContent><Stack direction="row" spacing={1} alignItems="center"><Typography fontWeight={500}>{m.name}</Typography></Stack><Typography variant="body2" color="text.secondary">{m.id}</Typography></CardContent></Card></Grid>))}</Grid>
            ) : (
              <Box sx={{ mt: 2 }}>{engines.data?.length ? engines.data.map((e) => <Chip key={e.name} label={e.displayName || api.shortId(e.name)} sx={{ mr: 1 }} />) : <Typography variant="body2" color="text.secondary">No agents deployed yet. Browse the Agent Garden for blueprints.</Typography>}</Box>
            )}
            <Box sx={{ textAlign: "center", mt: 3 }}><Button variant="outlined" href="#/vertex-ai/model-garden" sx={{ borderRadius: 5, textTransform: "none" }}>Browse Gallery</Button></Box>
          </Box>
        </Stack>
      </Box>
    </Box>
  );
}

/* ── Agent Garden ── */
export function AgentGarden() {
  const [sel, setSel] = useState({});
  const [q, setQ] = useState("");
  const toggle = (k) => setSel((s) => ({ ...s, [k]: !s[k] }));
  const active = Object.keys(sel).filter((k) => sel[k]);
  const uc = USE_CASES.filter((u) => sel[u]);
  const shown = GARDEN.filter((g) => (!q || `${g.title} ${g.desc}`.toLowerCase().includes(q.toLowerCase()))
    && (!uc.length || uc.includes(g.useCase)) && [...TOOLS, ...CAPS].filter((t) => sel[t]).every((t) => g.tags.includes(t) || g.lang === t));
  const group = (title, list) => (
    <Box sx={{ mb: 2 }}><Typography fontWeight={500} sx={{ py: 1, borderTop: 1, borderColor: "divider" }}>{title}</Typography>
      {list.map((t) => <Box key={t} role="checkbox" aria-checked={!!sel[t]} tabIndex={0} onClick={() => toggle(t)} onKeyDown={(e) => e.key === "Enter" && toggle(t)}
        sx={{ py: 0.75, pl: 1, cursor: "pointer", fontSize: 14, fontWeight: sel[t] ? 600 : 400, "&:hover": { bgcolor: "action.hover" } }}>{t}</Box>)}</Box>);
  return (
    <Box>
      <Crumbs trail={[{ text: "Agent Platform", href: "#/vertex-ai" }, { text: "Agents", href: "#/vertex-ai/agent-garden" }, { text: "Agent Garden" }]} />
      <Stack direction="row" alignItems="center" spacing={3} sx={{ borderBottom: 1, borderColor: "divider", pb: 1.5, mb: 2 }}>
        <Typography variant="h1" component="h1" sx={{ fontSize: 22, fontWeight: 400 }}>Agent Garden</Typography>
        <Link href="#/vertex-ai/deployments" underline="hover" color="text.secondary">Your deployed agents</Link>
      </Stack>
      <Typography variant="body2" sx={{ mb: 2 }}>Pre-built, customizable blueprints with source code, configuration files and best practice examples.</Typography>
      <Box sx={{ display: "flex", gap: 3 }}>
        <Box sx={{ width: 256, flexShrink: 0, p: 2, borderRadius: 4, bgcolor: "action.hover", alignSelf: "flex-start" }} data-testid="garden-filters">
          <Typography fontWeight={500} sx={{ mb: 1 }}>Filters{active.length ? ` (${active.length})` : ""}</Typography>
          {group("Use cases", USE_CASES)}{group("Data Sources and Tools", TOOLS)}{group("Core Capabilities", CAPS)}
        </Box>
        <Box sx={{ flex: 1 }}>
          <TextField size="small" placeholder="Search blueprints" value={q} onChange={(e) => setQ(e.target.value)} sx={{ mb: 2, minWidth: 300 }} InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
          <Grid container spacing={2}>{shown.map((g) => (
            <Grid item xs={12} md={6} lg={4} key={g.title}><Card variant="outlined" data-testid="agent-card" sx={{ height: "100%", borderRadius: 4, bgcolor: "action.hover", border: 0 }}><CardContent>
              <Typography fontWeight={500}>{g.title}</Typography><Typography variant="caption" color="text.secondary">{g.fw} · {g.lang}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ my: 1, display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{g.desc}</Typography>
              <Chip size="small" label={g.useCase} sx={{ borderRadius: 0.5 }} /></CardContent></Card></Grid>))}</Grid>
          {!shown.length && <Typography variant="body2" color="text.secondary">No blueprints match these filters.</Typography>}
        </Box>
      </Box>
    </Box>
  );
}

/* ── Tutorials ── */
export function Tutorials() {
  const [q, setQ] = useState("");
  const hit = (t) => !q || t.join(" ").toLowerCase().includes(q.toLowerCase());
  return (
    <Page crumbs={[{ text: "Agent Platform", href: "#/vertex-ai" }, { text: "Tutorials" }]}>
      <Stack alignItems="center" spacing={2} sx={{ mb: 4 }}>
        <Typography variant="h1" sx={{ fontSize: 56, fontWeight: 400 }}>Tutorials</Typography>
        <Typography fontSize={22}>Video &amp; interactive help for developers</Typography>
        <TextField size="small" placeholder="Search tutorials" value={q} onChange={(e) => setQ(e.target.value)} sx={{ width: 510, "& .MuiOutlinedInput-root": { borderRadius: 6 } }} InputProps={{ endAdornment: <InputAdornment position="end"><SearchIcon /></InputAdornment> }} />
        <Stack direction="row" spacing={1}>{["Agents", "Agent Studio", "Model Garden"].map((c) => <Chip key={c} label={c} onClick={() => setQ(c === "Agent Studio" ? "agent" : c)} sx={{ bgcolor: "chrome.active", color: "primary.main", borderRadius: 1 }} />)}</Stack>
      </Stack>
      <Typography variant="h2" sx={{ fontSize: 22, fontWeight: 400, mb: 1.5 }}>Videos</Typography>
      <Grid container spacing={2} sx={{ mb: 4 }}>{TUTORIAL_VIDEOS.filter(([t]) => hit([t])).map(([t, m]) => (
        <Grid item xs={12} sm={6} md={3} key={t}><Card variant="outlined" sx={{ height: "100%" }}><Box sx={{ height: 130, bgcolor: "action.selected" }} /><CardContent><Typography fontWeight={500}>{t}</Typography><Typography variant="caption" color="text.secondary">{m}</Typography></CardContent></Card></Grid>))}</Grid>
      <Typography variant="h2" sx={{ fontSize: 22, fontWeight: 400, mb: 1.5 }}>Documentation</Typography>
      <Grid container spacing={2}>{TUTORIAL_DOCS.filter(([t, d]) => hit([t, d])).map(([t, d, m]) => (
        <Grid item xs={12} sm={6} md={3} key={t}><Card variant="outlined" sx={{ height: "100%" }}><CardContent><Typography fontWeight={500}>{t}</Typography><Typography variant="body2" color="text.secondary">{d}</Typography><Typography variant="caption" color="text.secondary">{m}</Typography></CardContent></Card></Grid>))}</Grid>
    </Page>
  );
}

/* ── Deployments (Agent Engine reasoningEngines) ── */
export function Deployments() {
  return (
    <Box>
      <Crumbs trail={[{ text: "Agent Platform", href: "#/vertex-ai" }, { text: "Agents", href: "#/vertex-ai/agent-garden" }, { text: "Deployments" }]} />
      <Typography variant="h1" component="h1" sx={{ fontSize: 22, fontWeight: 400, mb: 2 }}>Deployments</Typography>
      <ResourceList coll="reasoningEngines" title="Agent deployments" singular="agent deployment" regionScoped
        build={null} columns={[{ id: "desc", header: "Description", cell: (i) => i.description || "—" }]} />
    </Box>
  );
}
