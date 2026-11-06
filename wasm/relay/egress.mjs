/* Allow-listed egress proxy for Nano's in-browser VMs.
 *
 * The VM's network is the browser's own fetch (v86 "fetch" adapter), which can't read cross-origin responses (no CORS on
 * Alpine/PyPI/npm mirrors) and can't do TLS from inside the guest. The VM host points v86's cors_proxy at
 * `<relay>/egress?u=<url-encoded>`; this module fetches the URL (http or https, redirects followed hop by hop) and
 * streams it back with CORS headers. ONLY package-manager / toolchain hosts are reachable; everything else is refused,
 * so the relay is never an open proxy and can't be pointed at localhost / private addresses.
 *
 *   in the VM:  sudo apk add openjdk8-jre      (repositories use http://dl-cdn.alpinelinux.org/...)
 *               pip install --index-url http://pypi.org/simple <pkg>
 */
export const ALLOWED_HOSTS = [
  // Alpine
  "alpinelinux.org",
  // Python
  "pypi.org", "pythonhosted.org",
  // Node
  "npmjs.org", "npmjs.com", "nodejs.org",
  // Java
  "maven.org", "maven.apache.org", "gradle.org", "adoptium.net", "azul.com",
  // Go / PHP / Rust / Ruby
  "golang.org", "go.dev", "packagist.org", "getcomposer.org", "crates.io", "rust-lang.org", "rubygems.org",
  // Source hosting + artifacts
  "github.com", "githubusercontent.com", "gitlab.com", "storage.googleapis.com", "dl.google.com",
];
export const MAX_HOPS = 6;
export const hostAllowed = (host) => {
  host = String(host || "").toLowerCase().replace(/\.$/, "");
  if (!host || /^[\d.]+$/.test(host) || host.includes(":") || host === "localhost") return false;   // no IPs, no localhost
  return ALLOWED_HOSTS.some((d) => host === d || host.endsWith("." + d));
};

const CORS = { "access-control-allow-origin": "*", "access-control-allow-private-network": "true", "access-control-expose-headers": "*" };

/** Handle GET/HEAD/POST /egress?u=<url>; returns a web Response. */
export async function egress(request) {
  const reqUrl = new URL(request.url);
  let target;
  try { target = new URL(reqUrl.searchParams.get("u") || ""); } catch (_) { return new Response("bad url", { status: 400, headers: CORS }); }
  const method = request.method.toUpperCase();
  if (!["GET", "HEAD", "POST"].includes(method)) return new Response("method not allowed", { status: 405, headers: CORS });
  const body = method === "POST" ? await request.arrayBuffer() : undefined;
  const headers = {};
  for (const h of ["accept", "accept-encoding", "content-type", "range", "user-agent"]) { const v = request.headers.get(h); if (v) headers[h] = v; }
  for (let hop = 0; hop <= MAX_HOPS; hop++) {
    if (!/^https?:$/.test(target.protocol) || !hostAllowed(target.hostname))
      return new Response(`egress blocked: ${target.hostname} is not on the Nano VM allow-list`, { status: 403, headers: CORS });
    if (target.protocol === "http:") target = new URL(target.href.replace(/^http:/, "https:"));   // the guest speaks plain HTTP (no TLS inside); upstream is always HTTPS (PyPI's CDN 403s plain HTTP)
    let res;
    try { res = await fetch(target, { method, headers, body, redirect: "manual" }); }
    catch (e) { return new Response("egress fetch failed: " + (e && e.message), { status: 502, headers: CORS }); }
    if (res.status >= 300 && res.status < 400 && res.headers.get("location")) {
      target = new URL(res.headers.get("location"), target);        // re-checked against the allow-list on the next hop
      continue;
    }
    // The guest cannot do TLS, so package indexes must point it at plain-HTTP URLs on allow-listed hosts (this proxy upgrades them upstream):
    // PyPI's simple index links to https://files.pythonhosted.org/... which pip would otherwise try to fetch itself.
    const ct = String(res.headers.get("content-type") || "");
    if (/text\/html|application\/vnd\.pypi\.simple|application\/json/i.test(ct) && /(^|\.)(pypi\.org|pythonhosted\.org)$/.test(target.hostname) && method === "GET") {
      const txt = (await res.text()).replace(/https:\/\/((?:[a-z0-9-]+\.)*(?:pypi\.org|pythonhosted\.org))/gi, "http://$1");
      const oh = new Headers(res.headers);
      for (const k of ["content-encoding", "content-length", "transfer-encoding", "connection", "set-cookie"]) oh.delete(k);
      for (const [k, v] of Object.entries(CORS)) oh.set(k, v);
      return new Response(txt, { status: res.status, headers: oh });
    }
    const out = new Headers(res.headers);
    for (const k of ["content-encoding", "content-length", "transfer-encoding", "connection", "set-cookie"]) out.delete(k);
    for (const [k, v] of Object.entries(CORS)) out.set(k, v);
    const len = res.headers.get("content-length"); if (len && !res.headers.get("content-encoding")) out.set("content-length", len);
    return new Response(method === "HEAD" ? null : res.body, { status: res.status, headers: out });
  }
  return new Response("too many redirects", { status: 508, headers: CORS });
}
