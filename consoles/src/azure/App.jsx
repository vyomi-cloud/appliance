/* Azure lens shell: the portal top bar (portal menu, global search, Copilot / Cloud Shell /
 * notifications / settings / help, directory + user chip), breadcrumbs, toasts, and the
 * service router. Theme (light/dark) and the subscription filter live in Settings. */
import { wordmark } from "../common/brand.js";
const AZ_BRAND = wordmark("Azure");
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Avatar, Button, FluentProvider, Menu, MenuDivider, MenuGroupHeader, MenuItem, MenuList, MenuPopover, MenuTrigger,
  MessageBar, MessageBarActions, MessageBarBody, MessageBarTitle, Radio, RadioGroup, SearchBox, Select, Field,
  Tooltip, webDarkTheme, webLightTheme,
} from "@fluentui/react-components";
import {
  Alert20Regular, Dismiss20Regular, Navigation20Regular, QuestionCircle20Regular, Settings20Regular, Sparkle20Regular,
  WindowConsole20Regular, Home20Regular, Grid20Regular, Add20Regular,
} from "@fluentui/react-icons";
import { match, useRoute } from "../common/router.js";
import { useNotify } from "../common/notify.jsx";
import { DEFAULT_SUBSCRIPTION, getSubscriptionInfo, setSubscription } from "./kit/arm.js";
import { Glyph, Loading, NotSimulated } from "./kit/common.jsx";
import { SubscriptionCtx } from "./kit/subscription.js";
import { SERVICES, byId, classicHref } from "./services/registry.js";
import Home from "./pages/Home.jsx";
import AllServices from "./pages/AllServices.jsx";
import ServiceNotSimulated from "./pages/ServiceNotSimulated.jsx";
import { listStorageAccounts } from "./services/storage/api.js";

const pref = (k, d) => { try { return localStorage.getItem(`vyomi.v4.azure.${k}`) || d; } catch { return d; } };
const savePref = (k, v) => { try { localStorage.setItem(`vyomi.v4.azure.${k}`, v); } catch {} };


function resolve(m, route) {
  for (const r of m.routes) {
    const params = match(r.pattern, route.path);
    if (params) return { content: <r.component params={params} query={route.query} />, crumbs: r.crumbs?.(params) || [] };
  }
  return { content: <div className="vy-page"><NotSimulated feature={`The page ${route.path}`} /></div>, crumbs: [] };
}

export default function App() {
  const route = useRoute();
  const notify = useNotify();
  const [mode, setMode] = useState(pref("mode", "light"));
  const [drawer, setDrawer] = useState(null);          // notifications | settings | help | copilot | shell
  const [menuOpen, setMenuOpen] = useState(false);
  const [sub, setSub] = useState({ id: pref("subscription", DEFAULT_SUBSCRIPTION), displayName: "" });
  const [subs, setSubs] = useState([]);

  useEffect(() => { savePref("mode", mode); }, [mode]);
  useEffect(() => { setMenuOpen(false); setDrawer(null); }, [route.path]);
  useEffect(() => {
    // Vyomi's simulated subscription, read back over native ARM (GET /subscriptions/{id}).
    getSubscriptionInfo(DEFAULT_SUBSCRIPTION)
      .then((s) => { setSubs([s]); if (sub.id === s.subscriptionId) setSub({ id: s.subscriptionId, displayName: s.displayName }); })
      .catch(() => setSubs([]));
  }, []);
  useEffect(() => { setSubscription(sub.id); savePref("subscription", sub.id); }, [sub.id]);
  useEffect(() => {
    const on = (e) => { if (e.key === "/" && e.ctrlKey === false && (e.target === document.body)) { e.preventDefault(); document.getElementById("vy-global-search")?.focus(); } };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, []);

  const svcId = route.parts[0];
  const svc = byId[svcId];
  const [loaded, setLoaded] = useState({});
  useEffect(() => {
    if (svc?.load && !loaded[svcId]) svc.load().then((m) => setLoaded((l) => ({ ...l, [svcId]: m.default })));
  }, [svcId]);

  let content, crumbs = [];
  if (!svcId || svcId === "home") content = <Home />;
  else if (svcId === "allservices") { content = <AllServices />; crumbs = [{ text: "All services", href: "#/allservices" }]; }
  else if (svcId === "allresources") {
    content = <div className="vy-page"><h1 style={{ fontSize: 24, fontWeight: 600 }}>All resources</h1><NotSimulated feature="All resources (the cross-type resource list)" note={<>Browse a type instead, for example <a href="#/storage">Storage accounts</a>.</>} /></div>;
    crumbs = [{ text: "All resources", href: "#/allresources" }];
  }
  else if (!svc) content = <div className="vy-page"><NotSimulated feature={`The service "${svcId}"`} /></div>;
  else if (!svc.load) { content = <ServiceNotSimulated svc={svc} />; crumbs = [{ text: svc.title, href: `#/${svc.id}` }]; }
  else if (!loaded[svcId]) content = <Loading />;
  else {
    const r = resolve(loaded[svcId], route);
    content = r.content;
    crumbs = [{ text: svc.title, href: `#/${svc.id}` }, ...r.crumbs];
  }

  const theme = mode === "dark" ? webDarkTheme : webLightTheme;
  const top = (icon, label, id) => (
    <Tooltip content={label} relationship="label" key={id}>
      <Button className="vy-top-btn" appearance="transparent" icon={icon} aria-label={label} aria-pressed={drawer === id} onClick={() => setDrawer((d) => (d === id ? null : id))} />
    </Tooltip>
  );

  return (
    <FluentProvider theme={theme} style={{ "--vy-top-bg": mode === "dark" ? "#0b2a4a" : "#0078d4", background: "transparent" }}>
      <SubscriptionCtx.Provider value={sub}>
        <div className="vy-app">
          <header className="vy-top">
            <Tooltip content="Show portal menu" relationship="label">
              <Button className="vy-top-btn" appearance="transparent" icon={<Navigation20Regular />} aria-label="Show portal menu" onClick={() => setMenuOpen((v) => !v)} />
            </Tooltip>
            <a className="vy-brand" href="#/" aria-label="Vyomi Azure — Home"><img src={AZ_BRAND.src} alt="vyomi.cloud | Azure" height={26} style={{ display: "block" }} /></a>
            <GlobalSearch />
            <Button className="vy-copilot" size="small" icon={<Sparkle20Regular />} onClick={() => setDrawer((d) => (d === "copilot" ? null : "copilot"))}>Copilot</Button>
            {top(<WindowConsole20Regular />, "Cloud Shell", "shell")}
            {top(<Alert20Regular />, `Notifications${notify.items.length ? ` (${notify.items.length})` : ""}`, "notifications")}
            {top(<Settings20Regular />, "Settings", "settings")}
            {top(<QuestionCircle20Regular />, "Help + support", "help")}
            <Menu>
              <MenuTrigger disableButtonEnhancement>
                <button className="vy-account" aria-label="Account and directory">
                  <span className="vy-acct-text"><b>vyomi@simulator.local</b><small>Vyomi simulator (default directory)</small></span>
                  <Avatar size={28} name="Vyomi" color="neutral" />
                </button>
              </MenuTrigger>
              <MenuPopover>
                <MenuList>
                  <MenuGroupHeader>Directory: Vyomi simulator</MenuGroupHeader>
                  <MenuItem disabled>Subscription: {sub.displayName || sub.id}</MenuItem>
                  <MenuItem onClick={() => setDrawer("settings")}>Switch directory or subscription</MenuItem>
                  <MenuDivider />
                  <MenuItem onClick={() => { location.href = classicHref(); }}>Open the classic Vyomi console</MenuItem>
                </MenuList>
              </MenuPopover>
            </Menu>
          </header>

          {menuOpen && <>
            <div className="vy-scrim" onClick={() => setMenuOpen(false)} />
            <nav className="vy-portal-menu" aria-label="Portal menu">
              <a href="#/allservices"><Add20Regular /> Create a resource</a>
              <a href="#/"><Home20Regular /> Home</a>
              <a href="#/allservices"><Grid20Regular /> All services</a>
              <hr />
              <div className="vy-pm-head">FAVORITES</div>
              {SERVICES.map((s) => <a key={s.id} href={`#/${s.id}`}><Glyph text={s.glyph[0]} color={s.glyph[1]} size={20} /> {s.title}</a>)}
            </nav>
          </>}

          {drawer && (
            <aside className="vy-drawer" aria-label={drawer}>
              <h2>
                {{ notifications: "Notifications", settings: "Portal settings", help: "Help + support", copilot: "Copilot", shell: "Cloud Shell" }[drawer]}
                <Button appearance="subtle" icon={<Dismiss20Regular />} aria-label="Close pane" style={{ marginLeft: "auto" }} onClick={() => setDrawer(null)} />
              </h2>
              {drawer === "notifications" && (notify.items.length ? notify.items.map((n) => (
                <MessageBar key={n.id} intent={n.type === "error" ? "error" : n.type === "success" ? "success" : "info"} style={{ marginBottom: 8 }}>
                  <MessageBarBody>{n.header && <MessageBarTitle>{n.header}</MessageBarTitle>}{n.content}</MessageBarBody>
                  <MessageBarActions containerAction={<Button appearance="transparent" size="small" icon={<Dismiss20Regular />} aria-label="Dismiss" onClick={n.onDismiss} />} />
                </MessageBar>
              )) : <div className="vy-muted">No new notifications from this session.</div>)}
              {drawer === "settings" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                  <Field label="Default subscription filter" hint="Vyomi simulates one subscription; its id is what your SDK and CLI use.">
                    <Select value={sub.id} onChange={(_, d) => setSub({ id: d.value, displayName: subs.find((s) => s.subscriptionId === d.value)?.displayName || "" })} aria-label="Subscription">
                      {(subs.length ? subs : [{ subscriptionId: DEFAULT_SUBSCRIPTION, displayName: DEFAULT_SUBSCRIPTION }]).map((s) => (
                        <option key={s.subscriptionId} value={s.subscriptionId}>{s.displayName} ({s.subscriptionId})</option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Theme">
                    <RadioGroup value={mode} onChange={(_, d) => setMode(d.value)} aria-label="Theme">
                      <Radio value="light" label="Light" />
                      <Radio value="dark" label="Dark" />
                    </RadioGroup>
                  </Field>
                  <NotSimulated feature="Language + region, notifications and signing-out settings" />
                </div>
              )}
              {drawer === "help" && (
                <div style={{ fontSize: 13, lineHeight: 1.5 }}>
                  <p>Vyomi simulates this portal against local backends. Storage accounts are created over native Azure Resource Manager (ARM) and blobs over the native Blob REST API — the same endpoints your azure-* SDKs and the az CLI use, so both always see the same state.</p>
                  <p>Services without a Vyomi v4 page open in the <a href={classicHref()}>classic Vyomi console</a>.</p>
                  <NotSimulated feature="Support requests, service health and the documentation search" />
                </div>
              )}
              {drawer === "copilot" && <NotSimulated feature="Copilot" />}
              {drawer === "shell" && <NotSimulated feature="Cloud Shell" note="Use the az CLI or the azure-* SDKs on your machine against the Vyomi endpoints instead." />}
            </aside>
          )}

          <div className="vy-toasts" aria-live="polite">
            {notify.items.slice(0, 1).map((n) => (
              <MessageBar key={n.id} intent={n.type === "error" ? "error" : n.type === "success" ? "success" : "info"} layout="multiline">
                <MessageBarBody>{n.header && <MessageBarTitle>{n.header}</MessageBarTitle>}{n.content}</MessageBarBody>
                <MessageBarActions containerAction={<Button appearance="transparent" size="small" icon={<Dismiss20Regular />} aria-label="Dismiss" onClick={n.onDismiss} />} />
              </MessageBar>
            ))}
          </div>

          <main className="vy-main">
            {svcId && svcId !== "home" && (
              <nav className="vy-crumbs" aria-label="Breadcrumb">
                <a href="#/">Home</a>
                {crumbs.map((c, i) => <span key={i}><span className="sep">&gt;</span>{i === crumbs.length - 1 ? <span>{c.text}</span> : <a href={c.href}>{c.text}</a>}</span>)}
              </nav>
            )}
            {content}
          </main>
        </div>
      </SubscriptionCtx.Provider>
    </FluentProvider>
  );
}

/** "Search resources, services, and docs (G+/)": matches services from the registry and
 *  storage accounts from ARM (fetched on focus — the only resource type with a v4 page). */
function GlobalSearch() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [accounts, setAccounts] = useState([]);
  const box = useRef(null);
  const f = q.trim().toLowerCase();
  const services = useMemo(() => (f ? SERVICES.filter((s) => s.title.toLowerCase().includes(f)) : []), [f]);
  const resources = useMemo(() => (f ? accounts.filter((a) => a.name.toLowerCase().includes(f)) : []), [f, accounts]);
  useEffect(() => {
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    addEventListener("mousedown", close);
    return () => removeEventListener("mousedown", close);
  }, []);
  const load = () => listStorageAccounts().then(setAccounts).catch(() => {});
  return (
    <div className="vy-search" ref={box}>
      <SearchBox id="vy-global-search" size="medium" placeholder="Search resources, services, and docs (G+/)" value={q}
        onFocus={() => { setOpen(true); load(); }} onChange={(_, d) => { setQ(d.value); setOpen(true); }} aria-label="Search resources, services, and docs" />
      {open && f && (
        <div className="vy-search-results" role="listbox" onClick={() => { setOpen(false); setQ(""); }}>
          <h4>Services</h4>
          {services.length ? services.map((s) => <a key={s.id} href={`#/${s.id}`} role="option">{s.title}</a>) : <div className="vy-muted" style={{ padding: "4px 16px" }}>No results</div>}
          <h4>Resources</h4>
          {resources.length ? resources.map((r) => <a key={r.id} href={`#/storage/${r.resourceGroup}/${r.name}`} role="option">{r.name} <span className="vy-muted">· Storage account</span></a>)
            : <div className="vy-muted" style={{ padding: "4px 16px" }}>No results</div>}
        </div>
      )}
    </div>
  );
}
