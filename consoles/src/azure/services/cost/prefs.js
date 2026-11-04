/* Cost Management's console preferences — the portal's "Preview features" and
 * "Configuration" pages store these per-browser (Vyomi has no signed-in user profile to
 * persist them against), exactly like any console setting that needs no backend. */
const KEY = "vyomi.v4.azure.cost.prefs";

const DEFAULTS = {
  chartsPreview: true,
  forecastPreview: true,
  changeScopeFromMenu: false,
  defaultCurrency: "USD",
};

export function getPrefs() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; }
  catch { return { ...DEFAULTS }; }
}

export function setPrefs(next) {
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage unavailable */ }
}
