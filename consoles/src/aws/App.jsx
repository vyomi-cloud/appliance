/* AWS lens shell: top bar (services menu, search, region, preferences), app layout with the
 * service's side navigation, breadcrumbs, notifications and the help panel. */
import { Suspense, useEffect, useState } from "react";
import TopNavigation from "@cloudscape-design/components/top-navigation";
import AppLayout from "@cloudscape-design/components/app-layout";
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
import Home from "./pages/Home.jsx";
import ServicesMenu from "./pages/ServicesMenu.jsx";
import { NotSimulated } from "./kit/common.jsx";

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
  else if (!svc) { content = <NotSimulated feature={`The service "${svcId}"`} />; }
  else if (!svc.load) {
    content = <NotSimulated feature={`The v4 ${svc.title} console`} note={<a href={classicHref(svc.classic)}>Open {svc.title} in the classic Vyomi console</a>} />;
  } else if (!loaded[svcId]) { content = <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>; }
  else ({ content, nav, crumbs, help } = resolve(loaded[svcId], route));

  const regionLabel = REGIONS.find(([r]) => r === region)?.[1] || region;

  return (
    <>
      <div id="vyomi-top" style={{ position: "sticky", top: 0, zIndex: 1002 }}>
        <TopNavigation
          identity={{ href: "#/", title: "Vyomi", logo: undefined, onFollow: follow }}
          search={<ServicesMenu.Search />}
          utilities={[
            { type: "button", text: "Services", iconName: "grid-view", onClick: () => setMenuOpen((v) => !v), ariaLabel: "Services" },
            {
              type: "menu-dropdown", text: regionLabel, description: region, ariaLabel: "Region",
              items: REGIONS.map(([id, label]) => ({ id, text: label, secondaryText: id, checked: id === region })),
              onItemClick: ({ detail }) => { setRegionState(detail.id); notify.info(`Switched to ${detail.id}`); },
            },
            {
              type: "menu-dropdown", iconName: "settings", ariaLabel: "Settings", title: "Settings",
              items: [
                { id: "mode", text: "Visual mode", items: [{ id: "light", text: "Light", checked: mode === "light" }, { id: "dark", text: "Dark", checked: mode === "dark" }] },
                { id: "density", text: "Density", items: [{ id: "comfortable", text: "Comfortable", checked: density === "comfortable" }, { id: "compact", text: "Compact", checked: density === "compact" }] },
              ],
              onItemClick: ({ detail }) => {
                if (detail.id === "light" || detail.id === "dark") setMode(detail.id);
                if (detail.id === "comfortable" || detail.id === "compact") setDensity(detail.id);
              },
            },
            { type: "menu-dropdown", text: "Vyomi", description: "Local simulator", iconName: "user-profile", items: [{ id: "classic", text: "Classic console", href: classicHref("") }] },
          ]}
        />
        {menuOpen && <ServicesMenu onClose={() => setMenuOpen(false)} />}
      </div>
      <AppLayout
        headerSelector="#vyomi-top"
        navigationHide={!nav}
        navigationOpen={navOpen}
        onNavigationChange={({ detail }) => setNavOpen(detail.open)}
        navigation={nav && (
          <SideNavigation
            header={{ text: svc.title, href: `#/${svc.id}` }}
            activeHref={"#" + route.path}
            items={nav}
            onFollow={follow}
          />
        )}
        breadcrumbs={svcId && (
          <BreadcrumbGroup items={[{ text: svc?.title || svcId, href: `#/${svcId}` }, ...crumbs]} onFollow={follow} ariaLabel="Breadcrumbs" />
        )}
        notifications={<Flashbar items={notify.items} stackItems />}
        tools={<HelpPanel header={<h2>{help?.title || svc?.title || "Vyomi"}</h2>}>{help?.body || <p>Vyomi simulates this console against local backends. Everything you do here is real in the simulator and visible to your SDKs and CLI.</p>}</HelpPanel>}
        toolsOpen={toolsOpen}
        onToolsChange={({ detail }) => setToolsOpen(detail.open)}
        content={<Suspense fallback={<Spinner />}>{content}</Suspense>}
      />
    </>
  );
}

export { SERVICES };
