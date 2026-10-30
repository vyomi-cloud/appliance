/* GCP lens shell: tinted top bar (navigation menu, product name, project picker, search,
 * mode/help/account icons), collapsible product navigation, white content card, toasts. */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Autocomplete, Avatar, Box, Button, CircularProgress, CssBaseline, IconButton, InputAdornment, List,
  ListItemButton, ListItemIcon, ListItemText, ListSubheader, Stack, TextField, Tooltip, Typography,
} from "@mui/material";
import { ThemeProvider } from "@mui/material/styles";
import MenuIcon from "@mui/icons-material/esm/Menu.js";
import SearchIcon from "@mui/icons-material/esm/Search.js";
import DarkModeIcon from "@mui/icons-material/esm/DarkMode.js";
import LightModeIcon from "@mui/icons-material/esm/LightMode.js";
import HelpOutlineIcon from "@mui/icons-material/esm/HelpOutline.js";
import TerminalIcon from "@mui/icons-material/esm/Terminal.js";
import NotificationsIcon from "@mui/icons-material/esm/NotificationsNone.js";
import MoreVertIcon from "@mui/icons-material/esm/MoreVert.js";
import { Badge, Menu, MenuItem, Divider as MDivider } from "@mui/material";
import AccountTreeIcon from "@mui/icons-material/esm/AccountTree.js";
import KeyboardArrowDownIcon from "@mui/icons-material/esm/KeyboardArrowDown.js";
import ChevronLeftIcon from "@mui/icons-material/esm/ChevronLeft.js";
import MenuOpenIcon from "@mui/icons-material/esm/Menu.js";
import { match, useRoute } from "../common/router.js";
import { useNotify } from "../common/notify.jsx";
import { makeTheme } from "./theme.js";
import { PRODUCTS, classicHref, productFor } from "./services/registry.js";
import { useProject } from "./project.js";
import { NotSimulated } from "./kit/common.jsx";
import Home from "./pages/Home.jsx";
import ProductMenu, { recordVisit } from "./pages/ProductMenu.jsx";
import AllProducts from "./pages/AllProducts.jsx";
import ProjectPicker from "./pages/ProjectPicker.jsx";
import { Brand } from "./pages/Brand.jsx";

const pref = (k, d) => { try { return localStorage.getItem(`vyomi.v4.${k}`) || d; } catch { return d; } };
const savePref = (k, v) => { try { localStorage.setItem(`vyomi.v4.${k}`, v); } catch {} };

function resolve(m, route) {
  for (const r of m.routes) {
    const params = match(r.pattern, route.path);
    if (params) return <r.component params={params} query={route.query} />;
  }
  return <NotSimulated feature={`The page ${route.path}`} />;
}

export default function App() {
  const route = useRoute();
  const project = useProject();
  const [mode, setMode] = useState(pref("mode", "light"));
  const theme = useMemo(() => makeTheme(mode), [mode]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(pref("gcp.navCollapsed", "") === "1");
  useEffect(() => { savePref("mode", mode); document.documentElement.style.colorScheme = mode; }, [mode]);
  useEffect(() => { savePref("gcp.navCollapsed", navCollapsed ? "1" : ""); }, [navCollapsed]);
  useEffect(() => { document.title = `${prod ? prod.title + " – " : ""}${project} – Vyomi · Google Cloud`; });

  const prod = route.parts[0] === "products" ? null : productFor(route.parts);
  useEffect(() => { if (prod) recordVisit(prod.id); }, [prod?.id]);
  const [loaded, setLoaded] = useState({});
  const [loadErr, setLoadErr] = useState(null);
  useEffect(() => {
    if (prod?.load && !loaded[prod.id]) prod.load().then((m) => setLoaded((l) => ({ ...l, [prod.id]: m.default })), setLoadErr);
  }, [prod?.id]);

  let content, nav;
  if (!route.parts.length) content = <Home />;
  else if (route.parts[0] === "products") content = <AllProducts />;
  else if (!prod && route.parts[0] !== "products") content = <NotSimulated feature={`The product "${route.parts[0]}"`} />;
  else if (!prod.load) {
    content = (
      <Box>
        <Typography variant="h1" component="h1" sx={{ mb: 2 }}>{prod.title}</Typography>
        <NotSimulated feature={`The v4 ${prod.title} console`} note={<a href={classicHref(prod.classic)}>Open {prod.title} in the classic Vyomi console</a>} />
      </Box>
    );
  } else if (loadErr) content = <Alert severity="error">Failed to load {prod.title}: {String(loadErr.message || loadErr)}</Alert>;
  else if (!loaded[prod.id]) content = <Box sx={{ textAlign: "center", py: 8 }}><CircularProgress /></Box>;
  else { content = resolve(loaded[prod.id], route); nav = loaded[prod.id].nav; }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ minHeight: "100vh", bgcolor: "chrome.main", display: "flex", flexDirection: "column" }}>
        <TopBar onMenu={() => setMenuOpen(true)} onPicker={() => setPickerOpen(true)} project={project} mode={mode}
          onMode={() => setMode(mode === "dark" ? "light" : "dark")} />
        <Box sx={{ display: "flex", flex: 1, minHeight: 0 }}>
          {nav && <ProductNav prod={prod} nav={nav} route={route} collapsed={navCollapsed} onToggle={() => setNavCollapsed((v) => !v)} />}
          <Box component="main" sx={{ flex: 1, minWidth: 0, bgcolor: "background.paper", borderRadius: "16px 16px 0 0", mr: { xs: 0, sm: 2 }, ml: nav ? 0 : { xs: 0, sm: 2 }, px: 3, pt: 1, pb: 6 }}>
            {content}
          </Box>
        </Box>
      </Box>
      <ProductMenu open={menuOpen} onClose={() => setMenuOpen(false)} active={prod?.id} />
      {pickerOpen && <ProjectPicker open onClose={() => setPickerOpen(false)} project={project} />}
      <Toasts />
    </ThemeProvider>
  );
}

function TopBar({ onMenu, onPicker, project, mode, onMode }) {
  const search = useRef(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    const on = (e) => { if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement?.tagName)) { e.preventDefault(); search.current?.focus(); } };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, []);
  return (
    <Box component="header" sx={{ position: "sticky", top: 0, zIndex: 1100, bgcolor: "chrome.main", height: 64, display: "flex", alignItems: "center", px: 1, gap: 1 }}>
      <Tooltip title="Navigation menu"><IconButton aria-label="Navigation menu" onClick={onMenu}><MenuIcon /></IconButton></Tooltip>
      <Brand />
      <Button variant="outlined" color="inherit" onClick={onPicker} aria-label={`Project picker: ${project}`} startIcon={<AccountTreeIcon fontSize="small" />} endIcon={<KeyboardArrowDownIcon />}
        sx={{ ml: 2, borderColor: "divider", color: "text.primary", fontWeight: 400, maxWidth: 240, "& .MuiButton-startIcon": { color: "text.secondary" } }}>
        <Box component="span" sx={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{project}</Box>
      </Button>
      <Box sx={{ flex: 1, display: "flex", justifyContent: "center", px: 2, minWidth: 0 }}>
        <Autocomplete
          sx={{ width: "100%", maxWidth: 720, display: { xs: "none", md: "block" } }}
          options={PRODUCTS} getOptionLabel={(o) => o.title} inputValue={q} onInputChange={(_, v) => setQ(v)}
          onChange={(_, v) => { if (v) { location.hash = "/" + v.id; setQ(""); search.current?.blur(); } }}
          value={null} blurOnSelect clearOnBlur noOptionsText="No matching products" popupIcon={null}
          renderOption={(props, o) => (
            <li {...props} key={o.id}><o.icon fontSize="small" sx={{ mr: 1.5, color: "text.secondary" }} /><Box><Typography variant="body2">{o.title}</Typography><Typography variant="caption" color="text.secondary">{o.description}</Typography></Box></li>
          )}
          renderInput={(p) => (
            <TextField {...p} inputRef={search} placeholder="Search (/) for resources, docs, products, and more"
              inputProps={{ ...p.inputProps, "aria-label": "Search" }}
              InputProps={{ ...p.InputProps, endAdornment: <InputAdornment position="end"><SearchIcon fontSize="small" /><Typography variant="body2" sx={{ ml: 0.5 }}>Search</Typography></InputAdornment>,
                sx: { bgcolor: "chrome.search", borderRadius: 2, "& fieldset": { border: 0 }, height: 40 } }} />
          )}
        />
      </Box>
      <TopBarActions mode={mode} onMode={onMode} />
      <Tooltip title="Vyomi · local simulator"><Avatar sx={{ width: 32, height: 32, bgcolor: "primary.main", color: "primary.contrastText", fontSize: 15, ml: 0.5, mr: 1 }}>V</Avatar></Tooltip>
    </Box>
  );
}

/** Right side of the top bar, as in the native console: Cloud Shell · notifications · ⋮ menu. */
function TopBarActions({ mode, onMode }) {
  const notify = useNotify();
  const [bell, setBell] = useState(null);
  const [more, setMore] = useState(null);
  const history = notify.history || [];
  return (
    <>
      <Tooltip title="Activate Cloud Shell">
        <IconButton aria-label="Activate Cloud Shell" onClick={() => notify.info("Cloud Shell isn't simulated in Vyomi. Use your own terminal: gcloud, gsutil and the client libraries work against this endpoint.", "Cloud Shell")}><TerminalIcon /></IconButton>
      </Tooltip>
      <Tooltip title="Notifications">
        <IconButton aria-label="Notifications" onClick={(e) => setBell(e.currentTarget)}>
          <Badge badgeContent={history.length} color="error" max={99}><NotificationsIcon /></Badge>
        </IconButton>
      </Tooltip>
      <Menu anchorEl={bell} open={!!bell} onClose={() => setBell(null)} PaperProps={{ sx: { width: 360, maxHeight: 420 } }}>
        <Typography variant="subtitle2" sx={{ px: 2, py: 1 }}>Notifications</Typography>
        <MDivider />
        {history.length ? history.slice(0, 15).map((n) => (
          <MenuItem key={n.id} onClick={() => setBell(null)} sx={{ whiteSpace: "normal", display: "block" }}>
            <Typography variant="body2" sx={{ fontWeight: 500 }}>{n.header || n.type}</Typography>
            <Typography variant="body2" color="text.secondary">{String(n.content)}</Typography>
            <Typography variant="caption" color="text.secondary">{n.at.toLocaleTimeString()}</Typography>
          </MenuItem>
        )) : <Typography variant="body2" color="text.secondary" sx={{ px: 2, py: 1.5 }}>No notifications in this session</Typography>}
      </Menu>
      <Tooltip title="More options">
        <IconButton aria-label="More options" onClick={(e) => setMore(e.currentTarget)}><MoreVertIcon /></IconButton>
      </Tooltip>
      <Menu anchorEl={more} open={!!more} onClose={() => setMore(null)}>
        <MenuItem onClick={() => { onMode(); setMore(null); }}>{mode === "dark" ? <LightModeIcon fontSize="small" sx={{ mr: 1.5 }} /> : <DarkModeIcon fontSize="small" sx={{ mr: 1.5 }} />}{mode === "dark" ? "Use light theme" : "Use dark theme"}</MenuItem>
        <MenuItem component="a" href={classicHref("")}><HelpOutlineIcon fontSize="small" sx={{ mr: 1.5 }} />Classic Vyomi console</MenuItem>
      </Menu>
    </>
  );
}

function ProductNav({ prod, nav, route, collapsed, onToggle }) {
  const here = "#" + route.path;
  const isActive = (h) => here === h || (h !== `#/${prod.id}` && here.startsWith(h + "/"));
  const item = (it) => (
    <Tooltip key={it.href} title={collapsed ? it.text : ""} placement="right">
      <ListItemButton component="a" href={it.href} selected={isActive(it.href) || (it.match && it.match.some((m) => here.startsWith(m)))}
        sx={{ borderRadius: "0 20px 20px 0", mr: 1, minHeight: 36, py: 0.25, "&.Mui-selected": { bgcolor: "chrome.active", fontWeight: 500 } }}>
        {it.icon && <ListItemIcon sx={{ minWidth: collapsed ? 0 : 36 }}><it.icon fontSize="small" /></ListItemIcon>}
        {!collapsed && <ListItemText primary={it.text} primaryTypographyProps={{ fontSize: 14, noWrap: true }} />}
      </ListItemButton>
    </Tooltip>
  );
  return (
    <Box component="nav" aria-label={`${prod.title} navigation`} sx={{ width: collapsed ? 64 : 256, flexShrink: 0, transition: "width .15s", overflow: "hidden" }}>
      <Stack direction="row" alignItems="center" sx={{ pl: 2, pr: 1, height: 48 }}>
        <prod.icon sx={{ color: "text.secondary", mr: 1.5 }} />
        {!collapsed && <Typography sx={{ fontSize: 18, flex: 1 }} noWrap>{prod.title}</Typography>}
        <Tooltip title={collapsed ? "Expand navigation" : "Collapse navigation"}>
          <IconButton size="small" aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} onClick={onToggle}>
            {collapsed ? <MenuOpenIcon fontSize="small" /> : <ChevronLeftIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
      </Stack>
      <List dense disablePadding>
        {nav.map((n) => n.section ? (
          <Box key={n.section}>
            {!collapsed && <ListSubheader disableSticky sx={{ bgcolor: "transparent", lineHeight: "36px", fontWeight: 500, color: "text.primary" }}>{n.section}</ListSubheader>}
            {n.items.map(item)}
          </Box>
        ) : item(n))}
      </List>
    </Box>
  );
}

/** The console's snackbar: one message at a time, bottom-left, inverse surface. Newer
 *  messages replace older ones (the provider keeps a short history; we show the latest). */
function Toasts() {
  const { items } = useNotify();
  const n = items[0];
  if (!n) return null;
  const err = n.type === "error";
  return (
    <Box role="status" aria-live="polite" sx={{ position: "fixed", left: 24, bottom: 24, zIndex: 1400, maxWidth: 560 }}>
      <Alert key={n.id} icon={false} onClose={n.onDismiss} variant="filled"
        sx={{ boxShadow: 3, alignItems: "center", bgcolor: err ? "error.main" : (t) => (t.palette.mode === "dark" ? "#e3e3e3" : "#303030"),
          color: err ? "error.contrastText" : (t) => (t.palette.mode === "dark" ? "#1f1f1f" : "#f2f2f2"), fontSize: 14 }}>
        {n.header ? <b>{n.header}: </b> : null}{n.content}
      </Alert>
    </Box>
  );
}
