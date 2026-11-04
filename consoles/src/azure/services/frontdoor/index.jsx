import { Profiles, ProfileBlade, MENU } from "./FrontDoor.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const prof = (p) => ({ text: p.name, href: `#/frontdoor/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/frontdoor", component: Profiles },
    { pattern: "/frontdoor/:rg/:name", component: ProfileBlade, crumbs: (p) => [prof(p)] },
    { pattern: "/frontdoor/:rg/:name/:panel", component: ProfileBlade, crumbs: (p) => [prof(p), { text: label[p.panel] || p.panel, href: `#/frontdoor/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
