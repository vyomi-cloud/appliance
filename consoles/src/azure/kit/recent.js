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
