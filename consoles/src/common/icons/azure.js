/* Vyomi's own Azure-lens service icons — ORIGINAL artwork, drawn for Vyomi (no Azure / Microsoft
 * service icons, nothing traced or copied). The language borrows only the portal's convention:
 * flat, multi-tone filled glyphs in an Azure-like blue palette with light-cyan accents, no tile.
 * 24×24 grid; mid-tones only (no near-black blues) so every glyph holds up on the dark theme. */

const A = "#0078D4"; // primary blue
const C = "#1490DF"; // secondary blue
const M = "#83B9F9"; // soft blue
const L = "#50E6FF"; // cyan accent
const G = "#FFB900"; // warm accent (used sparingly)
const W = "#FFFFFF";

const hex = (cx, cy, r) => {
  const p = [0, 60, 120, 180, 240, 300].map((d) => {
    const a = ((d + 30) * Math.PI) / 180;
    return `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`;
  });
  return `M${p.join("L")}Z`;
};
const line = (d, color = W, w = 1.4) => `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;

export const AZURE_ICONS = {
  // storage account: a drawer cabinet with three tiers
  storage: `<rect x="3" y="4.5" width="18" height="15" rx="1.8" fill="${A}"/><rect x="5" y="7" width="14" height="2.6" rx=".6" fill="${L}"/><rect x="5" y="10.7" width="14" height="2.6" rx=".6" fill="${M}"/><rect x="5" y="14.4" width="14" height="2.6" rx=".6" fill="${W}" fill-opacity=".85"/>`,
  // virtual machine: a monitor showing a shell prompt
  vms: `<rect x="2.5" y="4" width="19" height="12.5" rx="1.4" fill="${A}"/>${line("M6.5 8.2l2.6 2.1-2.6 2.1M11 12.6h5")}<rect x="10.8" y="16.5" width="2.4" height="2" fill="${M}"/><rect x="7.5" y="18.3" width="9" height="1.9" rx=".7" fill="${M}"/>`,
  // SQL database: cylinder with row lines
  sql: `<path d="M5 6.5v11c0 1.7 3.1 3 7 3s7-1.3 7-3v-11z" fill="${A}"/><ellipse cx="12" cy="6.5" rx="7" ry="3" fill="${L}"/>${line("M8.6 12.6h6.8M8.6 16h6.8", W, 1.3)}`,
  // Cosmos DB: a globe with an orbiting satellite
  cosmos: `<circle cx="12" cy="12" r="6.2" fill="${A}"/><path d="M5.8 12h12.4" stroke="${M}" stroke-width="1"/><ellipse cx="12" cy="12" rx="10" ry="3.6" fill="none" stroke="${L}" stroke-width="1.5" transform="rotate(-28 12 12)"/><circle cx="19.6" cy="7.6" r="1.6" fill="${L}"/>`,
  // key vault: a safe door with a dial
  keyvaults: `<rect x="3.5" y="3.5" width="17" height="17" rx="2.2" fill="${A}"/><circle cx="12" cy="12" r="5" fill="${L}"/><circle cx="12" cy="12" r="1.7" fill="${A}"/>${line("M12 7v2.6M12 14.4V17M7 12h2.6M14.4 12H17", A, 1.2)}<rect x="4.8" y="7" width="1.4" height="3" rx=".5" fill="${M}"/><rect x="4.8" y="14" width="1.4" height="3" rx=".5" fill="${M}"/>`,
  // Service Bus: a channel carrying messages with direction arrows
  servicebus: `<rect x="2.5" y="5.5" width="19" height="13" rx="1.8" fill="${A}"/>${line("M5.5 9.7h8.5M5.5 14.3h8.5", L, 1.6)}<path d="M14.6 7.7l3.4 2-3.4 2zM14.6 12.3l3.4 2-3.4 2z" fill="${L}"/>`,
  // Function App: a bolt inside a round badge
  functionapp: `<circle cx="12" cy="12" r="9" fill="${A}"/><path d="M13.4 5.2 8.2 13h3.3l-1.2 5.8 5.5-8.3h-3.4z" fill="${G}"/>`,
  // App Service: a web globe
  appservices: `<circle cx="12" cy="12" r="8.6" fill="${A}"/>${line("M3.6 12h16.8M5 7.8h14M5 16.2h14M12 3.4c2.6 2.4 3.8 5.3 3.8 8.6s-1.2 6.2-3.8 8.6M12 3.4C9.4 5.8 8.2 8.7 8.2 12s1.2 6.2 3.8 8.6", L, 1.1)}`,
  // Virtual network: three linked nodes inside a boundary
  vnets: `<rect x="3" y="3" width="18" height="18" rx="3" fill="none" stroke="${A}" stroke-width="1.6"/>${line("M8 9.5h8M8 9.5l4 6.5M16 9.5l-4 6.5", C, 1.3)}<circle cx="8" cy="9.5" r="2.1" fill="${A}"/><circle cx="16" cy="9.5" r="2.1" fill="${A}"/><circle cx="12" cy="16" r="2.1" fill="${L}"/>`,
  // NSG: a two-tone shield with a check
  // Defender for Cloud: a shield carrying a posture gauge (arc + needle) — original Vyomi glyph
  defender: `<path d="M12 2.6 20 5.6v5.8c0 4.7-3.3 8.5-8 10.4-4.7-1.9-8-5.7-8-10.4V5.6z" fill="${C}"/><path d="M7.4 14.2a4.6 4.6 0 0 1 9.2 0" fill="none" stroke="${L}" stroke-width="1.8" stroke-linecap="round"/>${line("M12 14.2l2.6-3.1", W, 1.6)}<circle cx="12" cy="14.2" r="1.1" fill="${W}"/><rect x="9.2" y="6.4" width="5.6" height="1.6" rx=".8" fill="${M}"/>`,
  nsgs: `<path d="M12 2.8 19.5 5.7v5.6c0 4.5-3.1 8.1-7.5 10-4.4-1.9-7.5-5.5-7.5-10V5.7z" fill="${A}"/><path d="M12 2.8v18.5c4.4-1.9 7.5-5.5 7.5-10V5.7z" fill="${C}"/>${line("M8.6 12.1l2.4 2.4 4.6-4.8", W, 1.7)}`,
  // resource group: a dashed boundary holding four resources
  resourcegroups: `<rect x="3" y="3" width="18" height="18" rx="2.4" fill="none" stroke="${A}" stroke-width="1.5" stroke-dasharray="3 2"/><rect x="6.5" y="6.5" width="4.8" height="4.8" rx=".9" fill="${A}"/><rect x="12.7" y="6.5" width="4.8" height="4.8" rx=".9" fill="${L}"/><rect x="6.5" y="12.7" width="4.8" height="4.8" rx=".9" fill="${M}"/><rect x="12.7" y="12.7" width="4.8" height="4.8" rx=".9" fill="${C}"/>`,
  // container registry: stacked shipping containers
  acr: `<rect x="2.5" y="12" width="9" height="7.5" rx="1" fill="${A}"/><rect x="12.5" y="12" width="9" height="7.5" rx="1" fill="${C}"/><rect x="7.5" y="4" width="9" height="7" rx="1" fill="${L}"/>${line("M5.5 14v3.5M8.5 14v3.5M15.5 14v3.5M18.5 14v3.5", W, 1)}${line("M10.5 6v3M13.5 6v3", A, 1)}`,
  // Kubernetes service: a cluster of three hexagonal nodes
  aks: `<path d="${hex(8, 8.6, 4.6)}" fill="${A}"/><path d="${hex(16, 8.6, 4.6)}" fill="${C}"/><path d="${hex(12, 15.5, 4.6)}" fill="${L}"/>`,
  // API Management: a cloud carrying an API bracket pair
  apim: `<path d="M7 19a4.6 4.6 0 0 1-.7-9.15A6 6 0 0 1 17.9 9.2 4.9 4.9 0 0 1 17.3 19z" fill="${A}"/>${line("M10.2 11.6l-2.1 2.2 2.1 2.2M13.8 11.6l2.1 2.2-2.1 2.2", W, 1.4)}`,
  // Event Grid: a mesh of nodes routing events
  eventgrid: `${line("M5 5l7 7M19 5l-7 7M5 19l7-7M19 19l-7-7M5 5h14M5 19h14", M, 1.2)}<circle cx="5" cy="5" r="2" fill="${A}"/><circle cx="19" cy="5" r="2" fill="${A}"/><circle cx="5" cy="19" r="2" fill="${A}"/><circle cx="19" cy="19" r="2" fill="${A}"/><circle cx="12" cy="12" r="3" fill="${L}"/>`,
  // Monitor: a gauge with a pulse needle
  monitor: `<path d="M3.2 16.5a8.8 8.8 0 0 1 17.6 0" fill="none" stroke="${A}" stroke-width="3" stroke-linecap="round"/><path d="M3.2 16.5a8.8 8.8 0 0 1 4.2-7.5" fill="none" stroke="${L}" stroke-width="3" stroke-linecap="round"/>${line("M12 16.5l4-5", C, 1.8)}<circle cx="12" cy="16.5" r="2" fill="${C}"/>`,
  // Entra ID: an identity card
  entra: `<rect x="2.5" y="5" width="19" height="14" rx="2" fill="${A}"/><circle cx="8.3" cy="10.6" r="2.3" fill="${L}"/><path d="M4.8 16.4c.5-2 1.9-3.1 3.5-3.1s3 1.1 3.5 3.1z" fill="${L}"/>${line("M14 10h4.5M14 13.2h4.5", M, 1.4)}`,
  // subscription: a billing card with chip and stripe
  subscriptions: `<rect x="2.5" y="5" width="19" height="14" rx="2" fill="${A}"/><rect x="2.5" y="8" width="19" height="2.4" fill="${C}"/><rect x="5" y="12.6" width="4" height="3.2" rx=".6" fill="${G}"/>${line("M11.5 14.2h7", M, 1.4)}`,
  // Cost Management: a coin with rising bars
  cost: `<circle cx="12" cy="12" r="9" fill="${A}"/>${line("M8 16v-2.4M11 16v-4.6M14 16V9.6M17 16V7.6", L, 1.8)}`,
};

const FALLBACK = `<rect x="3" y="3" width="18" height="18" rx="2.4" fill="${A}"/><rect x="6.5" y="6.5" width="4.5" height="4.5" rx=".8" fill="${L}"/><rect x="13" y="6.5" width="4.5" height="4.5" rx=".8" fill="${M}"/><rect x="6.5" y="13" width="4.5" height="4.5" rx=".8" fill="${M}"/><rect x="13" y="13" width="4.5" height="4.5" rx=".8" fill="${L}"/>`;

/** Inner SVG markup for a 24×24 viewBox. */
export const azureIconMarkup = (id) => AZURE_ICONS[id] || FALLBACK;
