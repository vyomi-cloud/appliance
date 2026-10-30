/* Navigation menu (☰), laid out like the native console: Cloud overview + Recently visited,
 * Favorite products (☆ pins, saved per browser), Products (icon · name · ☆ · ›), and a
 * "View all products" button. Products without a v4 page open in the classic console. */
import { useState } from "react";
import { Box, Button, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Stack, Tooltip, Typography } from "@mui/material";
import CloseIcon from "@mui/icons-material/esm/Close.js";
import DashboardIcon from "@mui/icons-material/esm/DashboardOutlined.js";
import HistoryIcon from "@mui/icons-material/esm/History.js";
import ChevronRightIcon from "@mui/icons-material/esm/ChevronRight.js";
import StarIcon from "@mui/icons-material/esm/Star.js";
import StarBorderIcon from "@mui/icons-material/esm/StarBorder.js";
import AppsIcon from "@mui/icons-material/esm/Apps.js";
import OpenInNewIcon from "@mui/icons-material/esm/OpenInNew.js";
import { PRODUCTS } from "../services/registry.js";
import { Brand } from "./Brand.jsx";

const read = (k, d) => { try { return JSON.parse(localStorage.getItem(`vyomi.v4.gcp.${k}`)) ?? d; } catch { return d; } };
const write = (k, v) => { try { localStorage.setItem(`vyomi.v4.gcp.${k}`, JSON.stringify(v)); } catch {} };

export function recordVisit(id) {
  const r = read("recent", []).filter((x) => x !== id);
  write("recent", [id, ...r].slice(0, 10));
}

const byId = Object.fromEntries(PRODUCTS.map((p) => [p.id, p]));

export default function ProductMenu({ open, onClose, active }) {
  const [favs, setFavs] = useState(() => read("favorites", []));
  const [showRecent, setShowRecent] = useState(false);
  const toggle = (id) => { const f = favs.includes(id) ? favs.filter((x) => x !== id) : [...favs, id]; setFavs(f); write("favorites", f); };
  // Every product opens in-app; one without a v4 page shows the honest panel with a classic link.
  const go = (p) => { location.hash = `/${p.id}`; onClose(); };
  const recent = read("recent", []).map((id) => byId[id]).filter(Boolean);

  const Row = ({ p }) => (
    <ListItemButton selected={active === p.id} onClick={() => go(p)} sx={{ borderRadius: "0 20px 20px 0", mr: 1, py: 0.6 }}>
      <ListItemIcon sx={{ minWidth: 40 }}><p.icon fontSize="small" /></ListItemIcon>
      <ListItemText primary={p.title} primaryTypographyProps={{ variant: "body2" }} />
      <Tooltip title={favs.includes(p.id) ? "Remove from favorites" : "Add to favorites"}>
        <IconButton size="small" edge="end" onClick={(e) => { e.stopPropagation(); toggle(p.id); }} aria-label={`${favs.includes(p.id) ? "Unpin" : "Pin"} ${p.title}`}>
          {favs.includes(p.id) ? <StarIcon fontSize="small" sx={{ color: "primary.main" }} /> : <StarBorderIcon fontSize="small" />}
        </IconButton>
      </Tooltip>
      {p.load ? <ChevronRightIcon fontSize="small" sx={{ color: "text.secondary", ml: 0.5 }} />
        : <Tooltip title="Opens in the classic Vyomi console"><OpenInNewIcon sx={{ fontSize: 15, color: "text.secondary", ml: 0.75 }} /></Tooltip>}
    </ListItemButton>
  );

  return (
    <Drawer open={open} onClose={onClose} PaperProps={{ sx: { width: 300, bgcolor: "background.paper", display: "flex", flexDirection: "column" } }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 1, height: 64, flexShrink: 0 }}>
        <IconButton aria-label="Close navigation menu" onClick={onClose}><CloseIcon /></IconButton>
        <Brand />
      </Stack>
      <Box sx={{ overflowY: "auto", flex: 1 }}>
        <List dense aria-label="Console">
          <ListItemButton selected={!active} onClick={() => { location.hash = "/"; onClose(); }} sx={{ borderRadius: "0 20px 20px 0", mr: 1 }}>
            <ListItemIcon sx={{ minWidth: 40 }}><DashboardIcon fontSize="small" /></ListItemIcon>
            <ListItemText primary="Cloud overview" primaryTypographyProps={{ variant: "body2" }} />
            <ChevronRightIcon fontSize="small" sx={{ color: "text.secondary" }} />
          </ListItemButton>
          <ListItemButton onClick={() => setShowRecent((v) => !v)} sx={{ borderRadius: "0 20px 20px 0", mr: 1 }}>
            <ListItemIcon sx={{ minWidth: 40 }}><HistoryIcon fontSize="small" /></ListItemIcon>
            <ListItemText primary="Recently visited" primaryTypographyProps={{ variant: "body2" }} />
            <ChevronRightIcon fontSize="small" sx={{ color: "text.secondary", transform: showRecent ? "rotate(90deg)" : "none" }} />
          </ListItemButton>
          {showRecent && (recent.length ? recent.map((p) => <Box key={p.id} sx={{ pl: 2 }}><Row p={p} /></Box>)
            : <Typography variant="body2" color="text.secondary" sx={{ px: 3, py: 1 }}>Products you open appear here</Typography>)}
        </List>
        <Divider />
        <Typography variant="subtitle2" sx={{ px: 2.5, pt: 2 }}>Favorite products</Typography>
        {favs.length ? <List dense>{favs.map((id) => byId[id] && <Row key={id} p={byId[id]} />)}</List>
          : <Typography variant="body2" color="text.secondary" sx={{ px: 2.5, py: 1 }}>Favorite products appear here</Typography>}
        <Typography variant="subtitle2" sx={{ px: 2.5, pt: 1.5 }}>Products</Typography>
        <List dense aria-label="Products">{PRODUCTS.map((p) => <Row key={p.id} p={p} />)}</List>
      </Box>
      <Box sx={{ p: 1.5, flexShrink: 0, borderTop: 1, borderColor: "divider" }}>
        <Button variant="outlined" startIcon={<AppsIcon />} onClick={() => { location.hash = "/products"; onClose(); }}>View all products</Button>
      </Box>
    </Drawer>
  );
}
