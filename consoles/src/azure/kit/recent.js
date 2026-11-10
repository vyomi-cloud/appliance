/* Home → Resources → "Recent": resources this viewer opened, kept per browser like the
 * portal's recently-viewed list. Per-viewer convenience only (never resource state). */
const KEY = "vyomi.v4.azure.recent";

export function recent() {
  try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; }
}

export function remember(item) {
  try {
    const xs = recent().filter((x) => x.href !== item.href);
    localStorage.setItem(KEY, JSON.stringify([{ ...item, viewed: Date.now() }, ...xs].slice(0, 20)));
  } catch {}
}

export function forget(href) {
  try { localStorage.setItem(KEY, JSON.stringify(recent().filter((x) => x.href !== href))); } catch {}
}

/* A remembered resource that no longer exists (e.g. it lived in a previous Codespace) is kept in the list
 * but flagged inactive: greyed out and not clickable. */
export function setInactive(href, inactive = true) {
  try {
    const xs = recent();
    if (!xs.some((x) => x.href === href && !!x.inactive !== inactive)) return;
    localStorage.setItem(KEY, JSON.stringify(xs.map((x) => (x.href === href ? { ...x, inactive } : x))));
  } catch {}
}

export const isNotFound = (e) => /ResourceNotFound|NotFound|was not found|\b404\b/i.test(`${e?.code || ""} ${e?.message || e || ""}`);
