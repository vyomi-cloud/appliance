/* AWS lens service registry. One entry per service; `load` lazy-imports the service module
 * (its own chunk). A service module exports default {nav, routes} — see s3/index.jsx.
 * Services without a v4 module yet stay reachable through the classic (v3) console.
 * `icon` names Vyomi's own original tile (common/icons/aws.js) — no AWS Architecture Icons. */

export const CATEGORIES = ["Compute", "Storage", "Database", "Networking & Content Delivery", "Security, Identity, & Compliance", "Application Integration", "Management & Governance"];

export const SERVICES = [
  { id: "secretsmanager", icon: "secretsmanager", title: "Secrets Manager", description: "Store, manage, and retrieve secrets", category: "Security, Identity, & Compliance", load: () => import("./secretsmanager/index.jsx") },
];

export const byId = Object.fromEntries(SERVICES.map((s) => [s.id, s]));

/** Classic (v3) console deep link, used until a service has its v4 module. */
export const classicHref = (svc) => `${location.pathname.split("/v4/")[0]}/console/aws#${svc}`;
