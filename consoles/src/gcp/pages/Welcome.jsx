/* Landing page (#/) laid out like the native post-login "Welcome" page: greeting, the project
 * you're working in (opens the picker) with a copyable ID, Dashboard / Cloud Hub links, quick
 * action chips, a promo card on the right, Quick access tiles and "View all products".
 * Every action goes somewhere real: a v4 page, the classic console, or the Connect dialog.
 * The old Cloud overview dashboard lives on at #/dashboard. */
import { useState } from "react";
import { Box, Button, ButtonBase, Dialog, DialogContent, DialogTitle, IconButton, Link, Paper, Stack, Tooltip, Typography } from "@mui/material";
import AddBoxIcon from "@mui/icons-material/esm/AddBox.js";
import AppsIcon from "@mui/icons-material/esm/Apps.js";
import ArrowForwardIcon from "@mui/icons-material/esm/ArrowForward.js";
import CloseIcon from "@mui/icons-material/esm/Close.js";
import CloudQueueIcon from "@mui/icons-material/esm/CloudQueue.js";
import ContentCopyIcon from "@mui/icons-material/esm/ContentCopy.js";
import { useProject } from "../project.js";
import { byId, classicHref } from "../services/registry.js";
import { ConnectTabs } from "./Home.jsx";

const href = (id) => { const p = byId[id]; return p.load ? `#/${id}` : classicHref(p.classic); };

// Quick actions: each lands on the page that actually creates the thing.
const ACTIONS = [
  ["Create a storage bucket", "#/storage/create-bucket"],
  ["Create a VM", () => href("compute")],
  ["Deploy an application", () => href("run")],
  ["Create a secret", () => href("security/secret-manager")],
  ["Create a Pub/Sub topic", () => href("pubsub")],
  ["Create a key ring", () => href("security/kms")],
];
const QUICK = ["iam-admin", "compute", "storage", "sql", "networking", "kubernetes", "run", "security/secret-manager"];

function Copy({ value, label }) {
  const [ok, setOk] = useState(false);
  return (
    <Tooltip title={ok ? "Copied" : `Copy ${label}`}>
      <IconButton size="small" aria-label={`Copy ${label}`} sx={{ p: 0.25 }}
        onClick={async () => { try { await navigator.clipboard.writeText(value); setOk(true); setTimeout(() => setOk(false), 1500); } catch {} }}>
        <ContentCopyIcon sx={{ fontSize: 14 }} />
      </IconButton>
    </Tooltip>
  );
}

// Our own decoration: a few coloured dots and a paper plane in outline.
function Decor() {
  return (
    <Box aria-hidden sx={{ position: "absolute", top: 4, right: 140, width: 380, height: 130, pointerEvents: "none", display: { xs: "none", md: "block" } }}>
      <svg width="380" height="130" viewBox="0 0 380 130">
        <circle cx="10" cy="16" r="6" fill="#4285f4" />
        <circle cx="86" cy="80" r="6" fill="#fbbc04" />
        <circle cx="356" cy="24" r="12" fill="#34a853" />
        <circle cx="294" cy="122" r="3" fill="#ea4335" />
        <g fill="none" stroke="#80868b" strokeWidth="1.3">
          <path d="M214 12 L256 54 L194 54 Z" /><path d="M214 12 L214 96" strokeDasharray="2 3" /><path d="M256 54 L214 96" strokeDasharray="2 3" />
        </g>
      </svg>
    </Box>
  );
}

export default function Welcome({ onPicker }) {
  const project = useProject();
  const [connect, setConnect] = useState(false);
  const chip = { borderRadius: 2, textTransform: "none", fontWeight: 500, py: 0.4, px: 1.25, borderColor: "divider" };

  return (
    <Box sx={{ maxWidth: 1060, mx: "auto", px: { xs: 0, md: 4 }, pt: 6, position: "relative" }}>
      <Decor />
      <Stack direction={{ xs: "column", md: "row" }} spacing={4} justifyContent="space-between" alignItems={{ md: "flex-end" }}>
        <Box>
          <Stack direction="row" alignItems="center" spacing={1.25} sx={{ mb: 2 }}>
            <CloudQueueIcon sx={{ fontSize: 36, color: "primary.main" }} />
            <Typography variant="h1" component="h1" sx={{ fontSize: 32, fontWeight: 400 }}>Welcome</Typography>
          </Stack>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
            <Typography variant="body1">You're working in</Typography>
            <Button variant="outlined" size="small" onClick={onPicker} aria-label={`Change project: ${project}`} sx={{ ...chip, fontSize: 16, fontWeight: 400 }}>{project}</Button>
          </Stack>
          <Stack direction="row" alignItems="center" spacing={0.75} sx={{ mb: 2 }}>
            <Typography variant="body2">Project ID:</Typography>
            <Typography variant="body2">{project}</Typography>
            <Copy value={project} label="project ID" />
          </Stack>
          <Stack direction="row" spacing={2} sx={{ mb: 4 }}>
            <Link href="#/dashboard" variant="body2" underline="always">Dashboard</Link>
            <Link href="#/cloud-hub" variant="body2" underline="always">Cloud Hub</Link>
          </Stack>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, maxWidth: 640 }}>
            {ACTIONS.map(([label, to]) => (
              <Button key={label} variant="outlined" size="small" href={typeof to === "function" ? to() : to} startIcon={<AddBoxIcon />} sx={chip}>{label}</Button>
            ))}
          </Box>
        </Box>
        <Paper elevation={0} sx={{ bgcolor: (t) => (t.palette.mode === "dark" ? "action.hover" : "#f0f6fe"), p: 2, width: { md: 240 }, flexShrink: 0, borderRadius: 1 }}>
          <Typography variant="body1" sx={{ fontSize: 17, mb: 3 }}>Connect gcloud or a Google Cloud SDK to this simulator in two lines.</Typography>
          <ButtonBase onClick={() => setConnect(true)} sx={{ width: "100%", justifyContent: "space-between", typography: "body1" }}>
            Show me how <ArrowForwardIcon fontSize="small" color="primary" />
          </ButtonBase>
        </Paper>
      </Stack>

      <Typography variant="h2" sx={{ fontSize: 22, fontWeight: 400, mt: 5, mb: 1.5 }}>Quick access</Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, gap: 2 }}>
        {QUICK.map((id) => {
          const p = byId[id];
          return (
            <ButtonBase key={id} href={href(id)} aria-label={p.title}
              sx={{ justifyContent: "flex-start", gap: 1.25, px: 2, height: 64, border: 1, borderColor: "divider", borderRadius: 1, "&:hover": { bgcolor: "action.hover" } }}>
              <p.icon fontSize="small" /><Typography variant="body2" sx={{ fontWeight: 500 }}>{p.title}</Typography>
            </ButtonBase>
          );
        })}
      </Box>
      <Button variant="outlined" size="small" href="#/products" startIcon={<AppsIcon />} sx={{ ...chip, mt: 3 }}>View all products</Button>

      <Dialog open={connect} onClose={() => setConnect(false)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ pr: 6 }}>Connect gcloud or an SDK
          <IconButton aria-label="Close" onClick={() => setConnect(false)} sx={{ position: "absolute", right: 8, top: 8 }}><CloseIcon /></IconButton>
        </DialogTitle>
        <DialogContent><ConnectTabs project={project} /></DialogContent>
      </Dialog>
    </Box>
  );
}
