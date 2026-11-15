/* Model Garden (collections/tasks/providers filter rail, sectioned cards) and the model detail page (Latest / Overview / Documentation),
 * laid out like the native console (captures 005/017) over the publisher-model REST API. */
import { useState } from "react";
import { Box, Button, Card, Chip, Divider, IconButton, InputAdornment, MenuItem, Stack, Tab, Tabs, TextField, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import SearchIcon from "@mui/icons-material/esm/Search.js";
import AutoAwesomeIcon from "@mui/icons-material/esm/AutoAwesome.js";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import FormDialog from "../../kit/FormDialog.jsx";
import { Link } from "../../link.jsx";
import Crumbs from "./Crumbs.jsx";
import { availText, byId } from "../../../common/aiModels.js";
import * as api from "./api.js";

const pubOf = (m) => m.name.split("/")[1];
const idOf = (m) => api.shortId(m.name);
const pubLabel = (p) => (p === "google" ? "Google" : p.replace(/(^|[-_])(\w)/g, (_, s, c) => (s ? " " : "") + c.toUpperCase()));
const isGoogle = (m) => pubOf(m) === "google";
const isOpen = (m) => m.openSourceCategory !== "PROPRIETARY";
const taskOf = (m) => (byId(idOf(m))?.kind === "embed" ? "Text embeddings" : "Text generation");
const serverless = (m) => !!m.servedByVyomi;
const selfDeployed = (m) => !!m.supportedActions?.deploy;
const route = (m) => `#/vertex-ai/model-garden/${pubOf(m)}/${idOf(m)}`;

function ModelCard({ m, list }) {
  return (
    <Card variant="outlined" component="a" href={route(m)} data-testid="garden-card" sx={{ display: "flex", gap: 1.5, p: 1.5, textDecoration: "none", color: "inherit", border: 0, borderRadius: 3, "&:hover": { bgcolor: "action.hover" }, ...(list ? { width: "100%" } : {}) }}>
      <Box sx={{ width: 48, height: 48, borderRadius: 2, bgcolor: "action.hover", display: "grid", placeItems: "center", flexShrink: 0 }}><AutoAwesomeIcon sx={{ color: "#4285f4" }} /></Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography fontSize={16} noWrap>{m.displayName}</Typography>
        <Typography variant="body2" color="text.secondary">{pubLabel(pubOf(m))}</Typography>
        <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: "wrap" }} useFlexGap>
          {serverless(m) && <Chip size="small" label="Serverless" sx={{ borderRadius: 0.5, bgcolor: "#e8f0fe", color: "#1a73e8" }} />}
          {selfDeployed(m) && <Chip size="small" label="Self-deployed" sx={{ borderRadius: 0.5, bgcolor: "#e8f0fe", color: "#1a73e8" }} />}
          <Chip size="small" data-testid="garden-availability" label={m.vyomiAvailability?.label || availText(null, idOf(m))} color={m.vyomiAvailability?.available ? "success" : "default"} variant="outlined" />
        </Stack>
      </Box>
    </Card>
  );
}

export function ModelGarden() {
  const [q, setQ] = useState("");
  const [view, setView] = useState("grid");
  const [sort, setSort] = useState("trending");
  const [flags, setFlags] = useState({});
  const [facet, setFacet] = useState(null);   // {kind, value}
  const { data = [], loading, error } = useAsync(() => api.listModelGarden(), []);
  const count = (fn) => data.filter(fn).length;
  const tasks = [...new Set(data.map(taskOf))];
  const providers = [...new Set(data.map(pubOf))];
  const inFacet = (m) => !facet || (facet.kind === "col" ? facet.value(m) : facet.kind === "task" ? taskOf(m) === facet.value : pubOf(m) === facet.value);
  const shown = data.filter((m) => inFacet(m) && (!q || `${m.displayName} ${m.description} ${m.name}`.toLowerCase().includes(q.toLowerCase()))
    && (!flags.serverless || serverless(m)) && (!flags.self || selfDeployed(m)))
    .sort((a, b) => (sort === "name" ? a.displayName.localeCompare(b.displayName) : 0));
  const pick = (kind, value) => setFacet((f) => (f && f.kind === kind && String(f.value) === String(value) ? null : { kind, value }));
  const row = (label, n, kind, value) => (
    <Stack key={label} direction="row" role="button" tabIndex={0} onClick={() => pick(kind, value)} onKeyDown={(e) => e.key === "Enter" && pick(kind, value)}
      sx={{ py: 0.75, px: 2, cursor: "pointer", fontSize: 15, fontWeight: facet && String(facet.value) === String(value) ? 600 : 400, bgcolor: facet && String(facet.value) === String(value) ? "chrome.active" : "transparent", "&:hover": { bgcolor: "action.hover" } }}>
      <Box sx={{ flex: 1 }}>{label}</Box><Box>{n}</Box></Stack>);
  const head = (t) => <Typography fontWeight={500} sx={{ px: 2, pt: 2, pb: 1, mt: 1, borderTop: 1, borderColor: "divider" }}>{t}</Typography>;
  const section = (title, list) => !!list.length && (
    <Box sx={{ mb: 3 }} data-testid={`section-${title}`}>
      <Stack direction="row" alignItems="center" sx={{ mb: 1 }}><Typography variant="h2" sx={{ fontSize: 22, fontWeight: 400, flex: 1 }}>{title}</Typography><Typography color="primary" fontSize={14}>Show all ({list.length})</Typography></Stack>
      <Box sx={{ display: "grid", gridTemplateColumns: view === "grid" ? "repeat(auto-fill, minmax(320px, 1fr))" : "1fr", gap: 1 }}>{list.map((m) => <ModelCard key={m.name} m={m} list={view === "list"} />)}</Box>
    </Box>);
  return (
    <Box>
      <Crumbs trail={[{ text: "Agent Platform", href: "#/vertex-ai" }, { text: "Models", href: "#/vertex-ai/model-garden" }, { text: "Model Garden" }]} />
      <Stack direction="row" alignItems="center" spacing={4} sx={{ borderBottom: 1, borderColor: "divider", pb: 1.5, mb: 1 }} useFlexGap flexWrap="wrap">
        <Typography variant="h1" component="h1" sx={{ fontSize: 22, fontWeight: 400 }}>Model Garden</Typography>
        <Link href="#/vertex-ai/studio">Explore Generative AI</Link><Link href="#/vertex-ai/endpoints">View my endpoints &amp; models</Link>
        <Link href="#/vertex-ai/models">Deploy model</Link><Link href="#/vertex-ai/tutorials">Learn more about Model Garden</Link>
      </Stack>
      <ErrorAlert error={error} />
      <Box sx={{ display: "flex", gap: 2 }}>
        <Box sx={{ width: 290, flexShrink: 0 }} data-testid="garden-rail">
          {head("Model Collections")}
          {row("Google models", count(isGoogle), "col", isGoogle)}{row("Partner models", count((m) => !isGoogle(m) && !isOpen(m)), "col", (m) => !isGoogle(m) && !isOpen(m))}{row("Self-deploy models", count(selfDeployed), "col", selfDeployed)}
          {head("Tasks")}{tasks.map((t) => row(t, count((m) => taskOf(m) === t), "task", t))}
          {head("Providers")}{providers.map((p) => row(pubLabel(p), count((m) => pubOf(m) === p), "prov", p))}
          {head("Features")}{row("Open source", count(isOpen), "col", isOpen)}{row("One-click deployment", count(selfDeployed), "col", selfDeployed)}
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Stack direction="row" spacing={1} sx={{ mb: 3 }}>
            <TextField fullWidth size="small" placeholder="Search models" value={q} onChange={(e) => setQ(e.target.value)} InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
            <ToggleButtonGroup exclusive size="small" value={view} onChange={(_, v) => v && setView(v)} aria-label="View"><ToggleButton value="grid" aria-label="Grid view">▦</ToggleButton><ToggleButton value="list" aria-label="List view">☰</ToggleButton></ToggleButtonGroup>
          </Stack>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 3 }}>
            <TextField select size="small" value={sort} onChange={(e) => setSort(e.target.value)} sx={{ minWidth: 190 }} aria-label="Sorting"><MenuItem value="trending">Sorting: Trending</MenuItem><MenuItem value="name">Sorting: Name</MenuItem></TextField>
            <Chip label="Serverless" variant={flags.serverless ? "filled" : "outlined"} color={flags.serverless ? "primary" : "default"} onClick={() => setFlags((f) => ({ ...f, serverless: !f.serverless }))} />
            <Chip label="Self-deployed" variant={flags.self ? "filled" : "outlined"} color={flags.self ? "primary" : "default"} onClick={() => setFlags((f) => ({ ...f, self: !f.self }))} />
          </Stack>
          {loading && <Typography variant="body2">Loading…</Typography>}
          {section("Made by Google", shown.filter(isGoogle))}
          {section("Made by partners", shown.filter((m) => !isGoogle(m) && !isOpen(m)))}
          {section("Open models", shown.filter((m) => !isGoogle(m) && isOpen(m)))}
          {!loading && !shown.length && <Typography variant="body2" color="text.secondary">No models match.</Typography>}
        </Box>
      </Box>
    </Box>
  );
}

export function ModelDetail({ params }) {
  const notify = useNotify();
  const [tab, setTab] = useState(0);
  const [deploy, setDeploy] = useState(false);
  const { data: m, loading, error } = useAsync(() => api.get(`publishers/${params.publisher}/models/${params.id}`), [params.publisher, params.id]);
  const meta = byId(params.id);
  return (
    <Box>
      <Crumbs trail={[{ text: "Agent Platform", href: "#/vertex-ai" }, { text: "Models", href: "#/vertex-ai/model-garden" }, { text: "Model Garden", href: "#/vertex-ai/model-garden" }, { text: `Model: ${params.id}` }]} />
      <Stack direction="row" alignItems="center" spacing={2} sx={{ borderBottom: 1, borderColor: "divider", pb: 1, mb: 3 }}>
        <IconButton href="#/vertex-ai/model-garden" aria-label="Back to Model Garden" color="primary"><ArrowBackIcon /></IconButton>
        <Typography variant="h1" component="h1" sx={{ fontSize: 22, fontWeight: 400 }}>{m?.displayName || params.id}</Typography>
      </Stack>
      <ErrorAlert error={error} />
      {loading && <Typography variant="body2">Loading…</Typography>}
      {m && (
        <Box sx={{ maxWidth: 920, mx: "auto" }}>
          <Stack direction="row" spacing={2} alignItems="flex-start" sx={{ mb: 3 }}>
            <AutoAwesomeIcon sx={{ fontSize: 44, color: "#4285f4" }} />
            <Box><Typography variant="h1" sx={{ fontSize: 44, fontWeight: 400 }}>{m.displayName}</Typography><Typography fontSize={20} sx={{ maxWidth: 520, mt: 1 }}>{m.description}</Typography></Box>
          </Stack>
          <Stack direction="row" spacing={1.5} sx={{ mb: 3 }}>
            <Button variant="contained" href="#/vertex-ai/studio/prompt" disabled={!m.servedByVyomi} sx={{ textTransform: "none" }}>Open in Agent Studio</Button>
            <Button variant="outlined" onClick={() => notify.info(`POST /v1/projects/${"{project}"}/locations/us-central1/publishers/${params.publisher}/models/${params.id}:generateContent`, "View code")} sx={{ textTransform: "none" }}>View Code</Button>
            {m.supportedActions?.deploy && <Button variant="outlined" onClick={() => setDeploy(true)} sx={{ textTransform: "none" }}>Deploy</Button>}
          </Stack>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ borderBottom: 1, borderColor: "divider", mb: 3 }}><Tab label="Latest" /><Tab label="Overview" /><Tab label="Documentation" /></Tabs>
          <Box sx={{ display: "flex", gap: 6 }}>
            <Box sx={{ flex: 1 }} data-testid={`model-tab-${tab}`}>
              {tab === 0 && <><Typography variant="h2" sx={{ fontSize: 28, fontWeight: 400, mb: 2 }}>Latest</Typography><Typography variant="body2" paragraph>{m.displayName} is available on this project through the Agent Platform publisher-model API (generateContent, countTokens, embedContent).</Typography>
                <Typography variant="body2" paragraph>Availability: {m.vyomiAvailability?.label || "Available"}. Launch stage: {m.launchStage}.</Typography></>}
              {tab === 1 && <><Typography variant="h2" sx={{ fontSize: 28, fontWeight: 400, mb: 2 }}>Overview</Typography><Typography variant="body2" paragraph>{m.description}</Typography>
                <Typography variant="h3" sx={{ fontSize: 22, fontWeight: 400, mb: 1 }}>Model details</Typography>
                <KeyValue labelWidth={180} items={[["Model name", params.id], ["Supported data types", meta?.kind === "embed" ? "Inputs: text; Output: embedding" : "Inputs: text; Output: text"], ["Open source", isOpen(m) ? "Yes" : "No"]]} /></>}
              {tab === 2 && <><Typography variant="h2" sx={{ fontSize: 28, fontWeight: 400, mb: 2 }}>Documentation</Typography><Typography variant="body2" paragraph>Call the model over REST:</Typography>
                <Box component="pre" sx={{ m: 0, p: 2, bgcolor: "action.hover", borderRadius: 2, fontSize: 13, overflow: "auto" }}>{`POST /v1/projects/PROJECT/locations/us-central1/publishers/${params.publisher}/models/${params.id}:${meta?.kind === "embed" ? "embedContent" : "generateContent"}`}</Box></>}
            </Box>
            <Box sx={{ width: 240 }}>
              <Typography fontWeight={500}>Model ID</Typography><Typography variant="body2" paragraph sx={{ wordBreak: "break-all" }}>{m.name}</Typography>
              <Typography fontWeight={500}>Version name</Typography><Typography variant="body2" paragraph>{params.publisher}/{params.id}</Typography>
              <Typography fontWeight={500} sx={{ mb: 1 }}>Tags</Typography><Typography variant="caption" color="text.secondary">Task</Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}><Chip label={taskOf(m) === "Text embeddings" ? "Embedding" : "Generation"} /></Stack>
            </Box>
          </Box>
        </Box>
      )}
      {deploy && m && <FormDialog open title={`Deploy ${m.displayName}`} submitLabel="Deploy" onClose={() => setDeploy(false)}
        fields={[{ key: "displayName", label: "Model name", default: params.id }, { key: "region", label: "Region", options: api.REGIONS, default: "us-central1" }]}
        onSubmit={async (v) => { await api.deployToNewEndpoint({ displayName: v.displayName, artifactUri: `gs://vertex-model-garden/${params.id}`, imageUri: m.supportedActions.deploy.containerSpec.imageUri, loc: v.region }); notify.success(`Deployed ${v.displayName} to a new endpoint`); }} />}
    </Box>
  );
}
