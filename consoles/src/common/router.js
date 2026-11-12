/* Hash router: `#/<service>/<path...>?<query>`. Hash routing keeps deep links working on
 * every substrate (static files on the appliance, the Nano service worker scope) with no
 * server-side rewrite rules. */
import { useEffect, useState } from "react";

export function parseHash(hash = location.hash) {
  const [p, q = ""] = hash.replace(/^#/, "").split("?");
  const parts = p.split("/").filter(Boolean).map(decodeURIComponent);
  return { path: "/" + parts.join("/"), parts, query: Object.fromEntries(new URLSearchParams(q)) };
}

export function useRoute() {
  const [route, setRoute] = useState(parseHash());
  useEffect(() => {
    const on = () => setRoute(parseHash());
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const href = (...parts) => "#/" + parts.map((p) => encodeURIComponent(p)).join("/");
export const navigate = (...parts) => { location.hash = href(...parts).slice(1); };

/** Cloudscape `onFollow` handler: route internal links through the hash, let external ones go. */
export function follow(e) {
  const h = e.detail.href;
  if (!h || e.detail.external || !h.startsWith("#")) return;
  e.preventDefault();
  location.hash = h.slice(1);
}

/** Match `pattern` like "/s3/buckets/:name" against a route path; returns params or null. */
export function match(pattern, path) {
  const a = pattern.split("/").filter(Boolean), b = path.split("/").filter(Boolean);
  if (a.length !== b.length) return null;
  const params = {};
  for (let i = 0; i < a.length; i++) {
    if (a[i].startsWith(":")) params[a[i].slice(1)] = b[i];
    else if (a[i] !== b[i]) return null;
  }
  return params;
}
