/* Cloud overview → Dashboard, laid out like the native console: tabs (Dashboard · Activity ·
 * Recommendations), Customize, a dismissible promo card, and cards with icon / title / ⋮ menu /
 * "→ Go to …" footer. Every value is live: project from the picker, product health and resource
 * counts from one real native call per product, API request rate from Vyomi's event log. */
import { useMemo, useState } from "react";
import {
  Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, Divider, FormControlLabel, IconButton,
  Link, Menu, MenuItem, Paper, Stack, Tab, Tabs, Tooltip, Typography,
} from "@mui/material";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import ArrowForwardIcon from "@mui/icons-material/esm/ArrowForward.js";
import CloseIcon from "@mui/icons-material/esm/Close.js";
import EditIcon from "@mui/icons-material/esm/Edit.js";
import HexagonIcon from "@mui/icons-material/esm/HexagonOutlined.js";
import ApiIcon from "@mui/icons-material/esm/Api.js";
import CheckCircleIcon from "@mui/icons-material/esm/CheckCircleOutline.js";
import ErrorIcon from "@mui/icons-material/esm/ErrorOutline.js";
import InsightsIcon from "@mui/icons-material/esm/Insights.js";
import CategoryIcon from "@mui/icons-material/esm/CategoryOutlined.js";
import TerminalIcon from "@mui/icons-material/esm/Terminal.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import { sdkEndpoint } from "../../common/connect.js";
import { restJson, WIRE_BASE } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { useProject } from "../project.js";
import { PRODUCTS, classicHref } from "../services/registry.js";

const store = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(`vyomi.v4.gcp.${k}`)) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(`vyomi.v4.gcp.${k}`, JSON.stringify(v)); } catch {} },
};

// One real native call per product: proves it answers AND counts its resources.
const PROBES = {
  storage: (p) => restJson("GET", "/storage/v1/b", { query: { project: p } }).then((r) => [(r.items || []).length, "buckets"]),
  pubsub: (p) => restJson("GET", `/v1/projects/${p}/topics`).then((r) => [(r.topics || []).length, "topics"]),
  "security/secret-manager": (p) => restJson("GET", `/v1/projects/${p}/secrets`).then((r) => [(r.secrets || []).length, "secrets"]),
  "security/kms": (p) => restJson("GET", `/v1/projects/${p}/locations/global/keyRings`).then((r) => [(r.keyRings || []).length, "key rings"]),
  "iam-admin": (p) => restJson("GET", `/v1/projects/${p}/serviceAccounts`).then((r) => [(r.accounts || []).length, "service accounts"]),
};
const prodById = Object.fromEntries(PRODUCTS.map((p) => [p.id, p]));

function useProbes(project) {
  return useAsync(() => Promise.all(Object.entries(PROBES).map(async ([id, fn]) => {
    try { const [count, noun] = await fn(project); return { id, ok: true, count, noun }; }
    catch (e) { return { id, ok: false, error: e.code || e.message }; }
  })), [project]);
}

function useEvents() {
  return useAsync(async () => {
    const base = WIRE_BASE.replace(/\/_wire$/, "");
    const r = await fetch(`${base}/api/cloudsim/events?limit=200`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return ((await r.json()).events || []).map((e) => ({
      at: new Date(e.at || e.ts), what: e.event || [e.provider, e.service, e.action].filter(Boolean).join("."),
      provider: e.provider || String(e.event || "").split(".")[0], resource: e.detail?.name || e.resource || "",
    }));
  }, []);
}

/** A dashboard card: icon + title + ⋮ menu, body, optional "→ Go to …" footer. */
function Card({ icon: Icon, title, onHide, footer, accent, children }) {
  const [anchor, setAnchor] = useState(null);
  return (
    <Paper variant="outlined" sx={{ borderRadius: 2, overflow: "hidden", borderTop: accent ? `4px solid ${accent}` : undefined, breakInside: "avoid", mb: 2 }}>
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ px: 2, pt: 1.5, pb: 1 }}>
        <Icon fontSize="small" sx={{ color: "text.secondary" }} />
        <Typography variant="h3" component="h2" sx={{ flex: 1, fontSize: 18 }}>{title}</Typography>
        <IconButton size="small" aria-label={`${title} options`} onClick={(e) => setAnchor(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>
        <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
          <MenuItem onClick={() => { setAnchor(null); onHide(); }}>Remove card</MenuItem>
        </Menu>
      </Stack>
      <Box sx={{ px: 2, pb: 1.5, pl: 6.5 }}>{children}</Box>
      {footer && (
        <>
          <Divider />
          <Link {...(footer.onClick ? { component: "button", onClick: footer.onClick } : { href: footer.href })} underline="none"
            sx={{ display: "flex", alignItems: "center", gap: 1.5, px: 2, py: 1.25, color: "text.primary", width: "100%", textAlign: "left" }}>
            <ArrowForwardIcon fontSize="small" /> <Typography variant="body2">{footer.label}</Typography>
          </Link>
        </>
      )}
    </Paper>
  );
}

const CARDS = [
  { id: "project", title: "Project info" },
  { id: "apis", title: "APIs" },
  { id: "status", title: "Vyomi status" },
  { id: "resources", title: "Resources" },
  { id: "monitoring", title: "Monitoring" },
  { id: "getting-started", title: "Connect gcloud or an SDK" },
];

function RequestsChart({ events }) {
  // Requests per 5 minutes over the last hour, from Vyomi's event log (GCP events only).
  const now = Date.now(), slot = 5 * 60e3;
  const bins = Array.from({ length: 12 }, (_, i) => ({ t: now - (11 - i) * slot, n: 0 }));
  for (const e of events.filter((e) => /gcp/i.test(e.provider))) {
    const i = 11 - Math.floor((now - e.at.getTime()) / slot);
    if (i >= 0 && i < 12) bins[i].n++;
  }
  const max = Math.max(1, ...bins.map((b) => b.n));
  const total = bins.reduce((a, b) => a + b.n, 0);
  return (
    <Box>
      <Typography variant="body2" sx={{ mb: 1 }}>Requests (per 5 min, last hour)</Typography>
      {total === 0 ? (
        <Stack direction="row" spacing={1} alignItems="center" sx={{ color: "text.secondary", py: 3 }}>
          <ErrorIcon fontSize="small" /><Typography variant="body2">No data is available for the selected time frame.</Typography>
        </Stack>
      ) : (
        <Stack direction="row" alignItems="flex-end" spacing={0.5} sx={{ height: 110, borderBottom: 1, borderColor: "divider" }}>
          {bins.map((b) => <Box key={b.t} title={`${b.n} requests at ${new Date(b.t).toLocaleTimeString()}`} sx={{ flex: 1, height: `${(b.n / max) * 100}%`, minHeight: b.n ? 2 : 0, bgcolor: "primary.main", borderRadius: "2px 2px 0 0" }} />)}
        </Stack>
      )}
    </Box>
  );
}

function CodeBlock({ code, label }) {
  const [copied, setCopied] = useState(false);
  return (
    <Box sx={{ position: "relative", bgcolor: "action.hover", borderRadius: 1, p: 1.5, pr: 5 }}>
      <Box component="pre" sx={{ m: 0, fontFamily: "monospace", fontSize: 12, lineHeight: 1.5, whiteSpace: "pre", overflowX: "auto" }}>{code}</Box>
      <Tooltip title={copied ? "Copied" : `Copy ${label}`}>
        <IconButton size="small" aria-label={`Copy ${label}`} sx={{ position: "absolute", top: 4, right: 4 }}
          onClick={async () => { try { await navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch {} }}>
          <ContentCopyIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Box>
  );
}

/** "Connect gcloud or an SDK": tabbed, ready-to-run snippets for this environment. */
function ConnectTabs({ project }) {
  const [tab, setTab] = useState(0);
  const ep = sdkEndpoint();
  const cli = [
    "# Vyomi doesn't check credentials; gcloud just needs a token to send",
    "export CLOUDSDK_AUTH_ACCESS_TOKEN=vyomi",
    `gcloud config set project ${project}`,
    `gcloud config set api_endpoint_overrides/storage ${ep.url}/storage/v1/`,
    "gcloud storage buckets list",
    `gcloud storage cp ./hello.txt gs://<bucket>/`,
  ].join("\n");
  const sdk = [
    "import os",
    `os.environ["STORAGE_EMULATOR_HOST"] = "${ep.url}"`,
    "",
    "from google.cloud import storage",
    `client = storage.Client(project="${project}")`,
    "print([b.name for b in client.list_buckets()])",
  ].join("\n");
  return (
    <Box>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ minHeight: 36, mb: 1, "& .MuiTab-root": { minHeight: 36, py: 0.5 } }}>
        <Tab label="gcloud CLI" /><Tab label="Python" />
      </Tabs>
      {tab === 0 ? <CodeBlock code={cli} label="gcloud commands" /> : <CodeBlock code={sdk} label="Python snippet" />}
      {ep.note && <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>{ep.note}</Typography>}
    </Box>
  );
}

export default function Home() {
  const project = useProject();
  const [tab, setTab] = useState(0);
  const [hidden, setHidden] = useState(() => store.get("home.hidden", []));
  const [promo, setPromo] = useState(() => !store.get("home.promoDismissed", false));
  const [customize, setCustomize] = useState(null);
  const probes = useProbes(project);
  const events = useEvents();
  const hide = (id) => { const h = [...hidden, id]; setHidden(h); store.set("home.hidden", h); };
  const rows = probes.data || [];
  const down = rows.filter((r) => !r.ok);
  const show = (id) => !hidden.includes(id);

  const cards = {
    project: (
      <Card icon={HexagonIcon} title="Project info" onHide={() => hide("project")} footer={{ label: "Go to project settings", href: classicHref("iam") }}>
        <Stack spacing={1.25}>
          <Box><Typography variant="body2" color="text.secondary">Project name</Typography><Typography variant="body2">{project}</Typography></Box>
          <Box><Typography variant="body2" color="text.secondary">Project ID</Typography><Typography variant="body2">{project}</Typography></Box>
          <Box><Typography variant="body2" color="text.secondary">Backend</Typography><Typography variant="body2">Vyomi simulator (local)</Typography></Box>
        </Stack>
      </Card>
    ),
    apis: (
      <Card icon={ApiIcon} title="APIs" onHide={() => hide("apis")} footer={{ label: "Go to recent activity", onClick: () => setTab(1) }}>
        {events.loading ? <Typography variant="body2" color="text.secondary">Loading…</Typography> : <RequestsChart events={events.data || []} />}
      </Card>
    ),
    status: (
      <Card icon={down.length ? ErrorIcon : CheckCircleIcon} title="Vyomi status" accent={probes.loading ? undefined : down.length ? "#d93025" : "#188038"} onHide={() => hide("status")}
        footer={{ label: "Refresh status", onClick: probes.reload }}>
        {probes.loading ? <Typography variant="body2" color="text.secondary">Checking products…</Typography>
          : down.length ? (
            <Stack spacing={0.5}>
              <Typography variant="body2">{down.length} of {rows.length} products not responding</Typography>
              {down.map((r) => <Typography key={r.id} variant="body2" color="error">{prodById[r.id]?.title}: {r.error}</Typography>)}
            </Stack>
          ) : <Typography variant="body2">All services normal</Typography>}
      </Card>
    ),
    resources: (
      <Card icon={CategoryIcon} title="Resources" onHide={() => hide("resources")} footer={{ label: "View all products", href: "#/products" }}>
        <Stack spacing={1.25}>
          {rows.filter((r) => r.ok).map((r) => {
            const p = prodById[r.id];
            return (
              <Stack key={r.id} direction="row" spacing={1.5} alignItems="flex-start">
                <p.icon fontSize="small" sx={{ color: "text.secondary", mt: 0.25 }} />
                <Box>
                  <Link href={`#/${p.id}`} underline="hover" variant="body2">{p.title}</Link>
                  <Typography variant="caption" display="block" color="text.secondary">{r.count} {r.noun}</Typography>
                </Box>
              </Stack>
            );
          })}
          {probes.loading && <Typography variant="body2" color="text.secondary">Loading…</Typography>}
        </Stack>
      </Card>
    ),
    monitoring: (
      <Card icon={InsightsIcon} title="Monitoring" onHide={() => hide("monitoring")} footer={{ label: "Go to Monitoring", href: classicHref("monitoring") }}>
        <Stack spacing={1}>
          <Link href={classicHref("monitoring")} underline="hover" variant="body2">Create my dashboard</Link>
          <Link href={classicHref("monitoring")} underline="hover" variant="body2">Set up alerting policies</Link>
          <Link href={classicHref("monitoring")} underline="hover" variant="body2">Create uptime checks</Link>
        </Stack>
      </Card>
    ),
    "getting-started": (
      <Card icon={TerminalIcon} title="Connect gcloud or an SDK" onHide={() => hide("getting-started")}>
        <ConnectTabs project={project} />
      </Card>
    ),
  };
  const cols = [["project", "resources"], ["apis", "getting-started"], ["status", "monitoring"]];

  return (
    <Box>
      <Stack direction="row" alignItems="flex-end" sx={{ borderBottom: 1, borderColor: "divider", mb: 2 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ flex: 1 }}>
          <Tab label="Dashboard" /><Tab label="Activity" /><Tab label="Recommendations" />
        </Tabs>
        {tab === 0 && <Button variant="outlined" startIcon={<EditIcon />} onClick={() => setCustomize([...hidden])} sx={{ mb: 1 }}>Customize</Button>}
      </Stack>

      {tab === 0 && (
        <>
          {promo && (
            <Paper variant="outlined" sx={{ borderRadius: 3, p: 3, mb: 2, position: "relative", bgcolor: "action.hover" }}>
              <IconButton aria-label="Dismiss" onClick={() => { setPromo(false); store.set("home.promoDismissed", true); }} sx={{ position: "absolute", top: 8, right: 8 }}><CloseIcon /></IconButton>
              <Typography variant="h2" sx={{ fontSize: 22, mb: 1 }}>Welcome to Vyomi Google Cloud</Typography>
              <Typography variant="body2" sx={{ mb: 2, maxWidth: 820 }}>
                Everything in this console runs against your local Vyomi simulator — the same native APIs gcloud, gsutil and the client libraries call. Products without a v4 page open in the classic Vyomi console.
              </Typography>
              <Stack direction="row" spacing={1}>
                <Button variant="outlined" href="#/storage">Go to Cloud Storage</Button>
                <Button variant="outlined" href="https://vyomi.cloud" target="_blank" rel="noopener">Learn more</Button>
              </Stack>
            </Paper>
          )}
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr", lg: "1fr 1fr 1fr" }, gap: 2, alignItems: "start" }}>
            {cols.map((col, i) => <Box key={i}>{col.filter(show).map((id) => <Box key={id}>{cards[id]}</Box>)}</Box>)}
          </Box>
          {CARDS.every((c) => !show(c.id)) && <Typography color="text.secondary">All cards are hidden. Use Customize to bring them back.</Typography>}
        </>
      )}

      {tab === 1 && (
        <Paper variant="outlined" sx={{ borderRadius: 2 }}>
          <Typography variant="h3" sx={{ fontSize: 18, p: 2 }}>Activity</Typography>
          <Divider />
          {(events.data || []).slice(0, 50).map((e, i) => (
            <Stack key={i} direction="row" spacing={2} sx={{ px: 2, py: 1, borderBottom: 1, borderColor: "divider" }}>
              <Typography variant="body2" color="text.secondary" sx={{ width: 220 }}>{e.at.toLocaleString()}</Typography>
              <Typography variant="body2" sx={{ width: 220 }}>{e.what}</Typography>
              <Typography variant="body2" color="text.secondary">{e.resource || "-"}</Typography>
            </Stack>
          ))}
          {!events.loading && !(events.data || []).length && <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>No activity yet.</Typography>}
        </Paper>
      )}

      {tab === 2 && (
        <Paper variant="outlined" sx={{ borderRadius: 2, p: 3, textAlign: "center" }} data-vyomi-not-simulated="Recommender">
          <Typography variant="h3" sx={{ fontSize: 18, mb: 1 }}>No recommendations</Typography>
          <Typography variant="body2" color="text.secondary">Recommender isn't simulated in Vyomi.</Typography>
        </Paper>
      )}

      <Dialog open={!!customize} onClose={() => setCustomize(null)}>
        <DialogTitle>Customize dashboard</DialogTitle>
        <DialogContent>
          {customize && CARDS.map((c) => (
            <FormControlLabel key={c.id} sx={{ display: "flex" }} label={c.title}
              control={<Checkbox checked={!customize.includes(c.id)} onChange={(e) => setCustomize(e.target.checked ? customize.filter((x) => x !== c.id) : [...customize, c.id])} />} />
          ))}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCustomize(null)}>Cancel</Button>
          <Button variant="contained" onClick={() => { setHidden(customize); store.set("home.hidden", customize); setCustomize(null); }}>Save</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
