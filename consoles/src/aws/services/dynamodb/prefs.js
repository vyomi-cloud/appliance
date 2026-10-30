/* Console-preference pages (Settings / Edit layout / Edit explore items) persist here and
 * are actually read back by the pages they govern — not just stored and ignored. */
import { applyDensity, Density } from "@cloudscape-design/global-styles";

const LAYOUT_KEY = "vyomi.ddb.layoutSettings";
const EXPLORE_KEY = "vyomi.ddb.exploreSettings";
const FAVORITES_KEY = "vyomi.ddb.favoriteTables";

const DEFAULT_LAYOUT = { density: "Comfortable", defaultEntryPage: "Dashboard", defaultTableTab: "Settings" };
const DEFAULT_EXPLORE = { defaultQueryType: "Scan", defaultItemEditorView: "Form view", defaultJsonSyntax: "DynamoDB JSON" };

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : { ...fallback };
  } catch { return { ...fallback }; }
}
function write(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

export const getLayoutSettings = () => read(LAYOUT_KEY, DEFAULT_LAYOUT);
export const setLayoutSettings = (v) => write(LAYOUT_KEY, { ...DEFAULT_LAYOUT, ...v });

export const getExploreSettings = () => read(EXPLORE_KEY, DEFAULT_EXPLORE);
export const setExploreSettings = (v) => write(EXPLORE_KEY, { ...DEFAULT_EXPLORE, ...v });

export function getFavoriteTables() {
  try { return JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]"); } catch { return []; }
}
export function setFavoriteTables(names) { write(FAVORITES_KEY, names); }
export function isFavoriteTable(name) { return getFavoriteTables().includes(name); }
export function toggleFavoriteTable(name) {
  const cur = getFavoriteTables();
  const next = cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name];
  setFavoriteTables(next);
  return next;
}

// Applies the console-wide content density (the same `vyomi.v4.density` preference the top
// bar's "Density" menu sets) — so this console-scoped setting has a real, visible effect
// immediately, and persists for the shell to pick up on the next load.
export function applyContentDensity(label) {
  const compact = label === "Compact";
  applyDensity(compact ? Density.Compact : Density.Comfortable);
  try { localStorage.setItem("vyomi.v4.density", compact ? "compact" : "comfortable"); } catch { /* storage unavailable */ }
}

// Table-tab labels (spec) -> TableDetail tab ids. "Settings" is the console's name for the
// table's landing tab (general info + capacity + TTL + encryption + deletion protection + tags
// in the real console); TableDetail splits that across "overview" and "settings" — the general
// info landing tab is the closer analogue, so that's where "Settings" points.
export const TABLE_TAB_ID = {
  "Settings": "overview", "Indexes": "indexes", "Monitor": "monitor",
  "Global tables": "global-tables", "Backups": "backups", "Exports and streams": "exports",
  "Permissions": "permissions",
};
