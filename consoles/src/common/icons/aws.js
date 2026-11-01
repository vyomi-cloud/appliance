/* Vyomi's own AWS-lens service icons — ORIGINAL artwork, drawn for Vyomi (no AWS Architecture
 * Icons, nothing traced or copied). The language only borrows the *convention* of the AWS
 * console: a rounded-square tile in the service's category colour with a simple white line
 * glyph. All glyphs live on a 24×24 grid inside a 5–19 safe zone, stroke 1.6 (≈1 px at 16 px),
 * so they stay crisp at 16 / 20 / 32 px and read the same in light and dark mode (the tile
 * carries its own background). */

export const AWS_CATEGORY_COLORS = {
  compute: "#ED7100",
  containers: "#ED7100",
  storage: "#7AA116",
  database: "#C925D1",
  networking: "#8C4FFF",
  analytics: "#8C4FFF",
  security: "#DD344C",
  integration: "#E7157B",
  management: "#B0084D",
  other: "#5A6B86",
};

/** id -> [category key, glyph markup (white strokes, fill none unless stated)]. */
export const AWS_ICONS = {
  // bucket: open-top tapered pail
  s3: ["storage", '<ellipse cx="12" cy="7.5" rx="6.5" ry="2"/><path d="M5.5 7.5l1.6 10.2a1.5 1.5 0 0 0 1.5 1.3h6.8a1.5 1.5 0 0 0 1.5-1.3l1.6-10.2"/>'],
  // key/value table: grid with a key column
  dynamodb: ["database", '<rect x="5" y="5.5" width="14" height="13" rx="1.5"/><path d="M5 9.8h14M5 14.2h14M10 9.8v8.7"/>'],
  // processor chip with pins
  ec2: ["compute", '<rect x="7.5" y="7.5" width="9" height="9" rx="1"/><rect x="10.3" y="10.3" width="3.4" height="3.4" fill="#fff" stroke="none"/><path d="M10 4.6v2.9M14 4.6v2.9M10 16.5v2.9M14 16.5v2.9M4.6 10h2.9M4.6 14h2.9M16.5 10h2.9M16.5 14h2.9"/>'],
  // lambda-like stroke: a function letter
  lambda: ["compute", '<path d="M7 5.5h2.2c.6 0 1.1.3 1.4.9l5.8 12.1H18"/><path d="M11.7 10.4 7 18.5"/>'],
  // relational DB: stacked cylinder
  rds: ["database", '<ellipse cx="12" cy="6.8" rx="6" ry="2.2"/><path d="M6 6.8v10.4c0 1.2 2.7 2.2 6 2.2s6-1 6-2.2V6.8"/><path d="M6 12c0 1.2 2.7 2.2 6 2.2s6-1 6-2.2"/>'],
  // isolated network: dashed boundary around linked nodes
  vpc: ["networking", '<rect x="4.8" y="4.8" width="14.4" height="14.4" rx="2" stroke-dasharray="2.4 1.8"/><circle cx="9.2" cy="9.6" r="1.5"/><circle cx="14.8" cy="9.6" r="1.5"/><circle cx="12" cy="14.8" r="1.5"/><path d="M10.7 9.6h2.6M9.9 11l1.4 2.4M14.1 11l-1.4 2.4"/>'],
  // API: angle brackets with a slash
  apigateway: ["networking", '<path d="M8.5 7.5 4.6 12l3.9 4.5M15.5 7.5l3.9 4.5-3.9 4.5M13.3 6.5l-2.6 11"/>'],
  // identity: person
  iam: ["security", '<circle cx="12" cy="8.6" r="3.1"/><path d="M5.8 19c.6-3.3 3.2-5.3 6.2-5.3s5.6 2 6.2 5.3"/>'],
  // key
  kms: ["security", '<circle cx="8.4" cy="12" r="3.3"/><path d="M11.7 12h7.3M16.6 12v2.8M19 12v2.2"/>'],
  // padlock with an asterisk
  secretsmanager: ["security", '<rect x="6" y="10.5" width="12" height="8.5" rx="1.5"/><path d="M8.8 10.5V8.3a3.2 3.2 0 0 1 6.4 0v2.2"/><path d="M12 12.9v3.8M10.3 13.9l3.4 1.8M13.7 13.9l-3.4 1.8"/>'],
  // queue: two queued messages moving right
  sqs: ["integration", '<rect x="4.6" y="8.5" width="4.2" height="7" rx=".8"/><rect x="10" y="8.5" width="4.2" height="7" rx=".8"/><path d="M15.6 12h3.6M17.5 10.1l1.9 1.9-1.9 1.9"/>'],
  // pub/sub: one source fanning out to three subscribers
  sns: ["integration", '<circle cx="6.8" cy="12" r="2"/><path d="M8.8 12h3.2M12 12l4-4.6M12 12h4.2M12 12l4 4.6"/><circle cx="17.3" cy="6.5" r="1.4"/><circle cx="17.8" cy="12" r="1.4"/><circle cx="17.3" cy="17.5" r="1.4"/>'],
  // event bus: a rail with taps up and down
  eventbridge: ["integration", '<path d="M4.6 12h14.8M8 12V8.3M12 12v3.7M16 12V8.3"/><circle cx="8" cy="6.8" r="1.5"/><circle cx="12" cy="17.2" r="1.5"/><circle cx="16" cy="6.8" r="1.5"/>'],
  // monitoring: trend line in a dial
  cloudwatch: ["management", '<circle cx="12" cy="12" r="7"/><path d="M8 13.8l2.4-2.7 2 1.6 3.6-4"/>'],
  // templates/stacks: three layers
  cloudformation: ["management", '<path d="M12 5 19 8.7 12 12.4 5 8.7z"/><path d="M5 12.3l7 3.7 7-3.7M5 15.7l7 3.7 7-3.7"/>'],
  // workflow: linked state nodes with a branch
  states: ["integration", '<circle cx="6.2" cy="8" r="2"/><circle cx="12" cy="17" r="2"/><circle cx="17.8" cy="8" r="2"/><path d="M7.4 9.6 10.8 15.4M16.6 9.6 13.2 15.4"/>'],
};

const FALLBACK = ["other", '<rect x="6" y="6" width="5" height="5" rx="1"/><rect x="13" y="6" width="5" height="5" rx="1"/><rect x="6" y="13" width="5" height="5" rx="1"/><rect x="13" y="13" width="5" height="5" rx="1"/>'];

/** Inner SVG markup for a 24×24 viewBox. `category` (registry category name) only matters
 *  for ids without their own icon. */
export function awsIconMarkup(id, category) {
  let [cat, glyph] = AWS_ICONS[id] || FALLBACK;
  if (!AWS_ICONS[id] && category) cat = categoryKey(category);
  const fill = AWS_CATEGORY_COLORS[cat] || AWS_CATEGORY_COLORS.other;
  return `<rect width="24" height="24" rx="4.5" fill="${fill}"/>`
    + `<g fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${glyph}</g>`;
}

/** Map an AWS console category label to a colour key. */
export function categoryKey(label = "") {
  const l = label.toLowerCase();
  if (l.startsWith("compute")) return "compute";
  if (l.startsWith("container")) return "containers";
  if (l.startsWith("storage")) return "storage";
  if (l.startsWith("database")) return "database";
  if (l.startsWith("network")) return "networking";
  if (l.startsWith("analytics")) return "analytics";
  if (l.startsWith("security")) return "security";
  if (l.startsWith("application integration")) return "integration";
  if (l.startsWith("management")) return "management";
  return "other";
}
