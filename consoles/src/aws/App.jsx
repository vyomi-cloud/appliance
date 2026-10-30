/* AWS lens shell: top bar (services menu, search, region, preferences), app layout with the
 * service's side navigation, breadcrumbs, notifications and the help panel. */
import { Suspense, useEffect, useState } from "react";
import AppLayout from "@cloudscape-design/components/app-layout";
import { iconDataUri } from "../common/icons/ServiceIcon.jsx";
import SideNavigation from "@cloudscape-design/components/side-navigation";
import BreadcrumbGroup from "@cloudscape-design/components/breadcrumb-group";
import Flashbar from "@cloudscape-design/components/flashbar";
import HelpPanel from "@cloudscape-design/components/help-panel";
import Spinner from "@cloudscape-design/components/spinner";
import Box from "@cloudscape-design/components/box";
import { applyDensity, applyMode, Density, Mode } from "@cloudscape-design/global-styles";
import { follow, match, useRoute } from "../common/router.js";
import { useNotify } from "../common/notify.jsx";
import { setRegion } from "../common/wire.js";
import { SERVICES, byId, classicHref } from "./services/registry.js";
import Home, { AllServices, recordVisit } from "./pages/Home.jsx";
import TopBar from "./pages/TopBar.jsx";
import { applyAwsTheme } from "./kit/theme.js";
import ServicesMenu from "./pages/ServicesMenu.jsx";
import { NotSimulated } from "./kit/common.jsx";
import { VyomiMark } from "../common/VyomiMark.jsx";

const REGIONS = [
  ["us-east-1", "US East (N. Virginia)"], ["us-east-2", "US East (Ohio)"], ["us-west-2", "US West (Oregon)"],
  ["eu-west-1", "Europe (Ireland)"], ["eu-central-1", "Europe (Frankfurt)"], ["ap-south-1", "Asia Pacific (Mumbai)"],
  ["ap-southeast-1", "Asia Pacific (Singapore)"], ["ap-northeast-1", "Asia Pacific (Tokyo)"],
];

const pref = (k, d) => { try { return localStorage.getItem(`vyomi.v4.${k}`) || d; } catch { return d; } };
const savePref = (k, v) => { try { localStorage.setItem(`vyomi.v4.${k}`, v); } catch {} };

/** Resolve the current route against a loaded service module. */
function resolve(m, route) {
  for (const r of m.routes) {
    const params = match(r.pattern, route.path);
    if (params) return { content: <r.component params={params} query={route.query} />, nav: m.nav, crumbs: r.crumbs?.(params) || [], help: r.help };
  }
  return { content: <NotSimulated feature={`The page ${route.path}`} />, nav: m.nav, crumbs: [] };
}

applyAwsTheme();   // orange primary actions, as in the native console

export default function App() {
  const route = useRoute();
  const notify = useNotify();
  const [region, setRegionState] = useState(pref("region", "us-east-1"));
  const [mode, setMode] = useState(pref("mode", "light"));
  const [density, setDensity] = useState(pref("density", "comfortable"));
  const [navOpen, setNavOpen] = useState(true);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => { setRegion(region); savePref("region", region); }, [region]);
  useEffect(() => { applyMode(mode === "dark" ? Mode.Dark : Mode.Light); savePref("mode", mode); }, [mode]);
  useEffect(() => { applyDensity(density === "compact" ? Density.Compact : Density.Comfortable); savePref("density", density); }, [density]);
  useEffect(() => { setMenuOpen(false); }, [route.path]);
  // Recently visited services (Console Home widget) — recorded as the user navigates.
  useEffect(() => { if (route.parts[0] && byId[route.parts[0]]) recordVisit(route.parts[0]); }, [route.parts[0]]);

  const svcId = route.parts[0];
  const svc = byId[svcId];
  const [loaded, setLoaded] = useState({});
  useEffect(() => {
    if (svc?.load && !loaded[svcId]) svc.load().then((m) => setLoaded((l) => ({ ...l, [svcId]: m.default })));
  }, [svcId]);
  // A service's side navigation opens on entry, like the native console (the user can still collapse it).
  useEffect(() => { if (byId[svcId]?.load) setNavOpen(true); }, [svcId, !!loaded[svcId]]);

  let content, nav, crumbs = [], help;
  if (!svcId) { content = <Home />; }
  else if (svcId === "services") { content = <AllServices />; }
  else if (!svc) { content = <NotSimulated feature={`The service "${svcId}"`} />; }
  else if (!svc.load) {
    content = <NotSimulated feature={`The v4 ${svc.title} console`} note={<a href={classicHref(svc.classic)}>Open {svc.title} in the classic <VyomiMark /> console</a>} />;
  } else if (!loaded[svcId]) { content = <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>; }
  else ({ content, nav, crumbs, help } = resolve(loaded[svcId], route));

  const regionLabel = REGIONS.find(([r]) => r === region)?.[1] || region;

  return (
    <>
      <div id="vyomi-top" style={{ position: "sticky", top: 0, zIndex: 1002 }}>
        <TopBar
          onServices={() => setMenuOpen((v) => !v)}
          region={region} regions={REGIONS} onRegion={(r) => { setRegionState(r); notify.info(`Switched to ${r}`); }}
          mode={mode} density={density} onMode={setMode} onDensity={setDensity}
          onHelp={() => setToolsOpen((v) => !v)}
          notifications={notify.history || []}
          onNotice={(content, header) => notify.info(content, header)}
        />
        {menuOpen && <ServicesMenu onClose={() => setMenuOpen(false)} />}
      </div>
      <AppLayout
        headerSelector="#vyomi-top"
        footerSelector="#vyomi-footer"
        navigationHide={!nav}
        navigationOpen={navOpen}
        onNavigationChange={({ detail }) => setNavOpen(detail.open)}
        navigation={nav && (
          <SideNavigation
            header={{ text: svc.title, href: `#/${svc.id}`, logo: { src: iconDataUri("aws", svc.icon || svc.id, svc.category), alt: "" } }}
            activeHref={"#" + route.path}
            items={nav}
            onFollow={follow}
          />
        )}
        breadcrumbs={svcId && (
          <BreadcrumbGroup items={[{ text: "Console Home", href: "#/" }, { text: svc?.title || (svcId === "services" ? "All services" : svcId), href: `#/${svcId}` }, ...crumbs]} onFollow={follow} ariaLabel="Breadcrumbs" />
        )}
        notifications={<Flashbar items={notify.items} stackItems />}
        tools={<HelpPanel header={<h2>{help?.title || svc?.title || "Vyomi"}</h2>}>{help?.body || <p><VyomiMark /> simulates this console against local backends. Everything you do here is real in the simulator and visible to your SDKs and CLI.</p>}</HelpPanel>}
        toolsOpen={toolsOpen}
        onToolsChange={({ detail }) => setToolsOpen(detail.open)}
        content={<Suspense fallback={<Spinner />}>{content}</Suspense>}
      />
      <footer id="vyomi-footer" style={{ position: "fixed", bottom: 0, left: 0, right: 0, height: 32, zIndex: 1001, display: "flex", alignItems: "center", gap: 20, padding: "0 16px", background: "#0f141a", color: "#d1d5db", fontSize: 12, fontFamily: '"Open Sans", "Helvetica Neue", Roboto, Arial, sans-serif' }}>
        <a href="#/" style={{ color: "inherit", textDecoration: "none" }}>Console Home</a>
        <a href={classicHref("")} style={{ color: "inherit", textDecoration: "none" }}>Classic console</a>
        <a href="https://github.com/vyomi-cloud/appliance/issues" target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>Feedback</a>
        <span style={{ marginLeft: "auto" }}><VyomiMark /> — local cloud simulator · not affiliated with Amazon Web Services</span>
      </footer>
    </>
  );
}

export { SERVICES };
