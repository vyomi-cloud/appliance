/* Storage account | Front Door and CDN: a real caching edge in front of this account's Blob endpoint
 * (core/azure_cdn_edge_core.py).  "Create" builds the real Microsoft.Cdn resources (profile, endpoint, origin group,
 * origin, route with caching); the test box fetches through the edge and shows x-cache HIT/MISS; purge evicts. */
import { useState } from "react";
import { Button, Field, Input, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson, sendRaw } from "../../../common/wire.js";
import { useSubscription } from "../../kit/subscription.js";
import { ErrorBar, Loading } from "../../kit/common.jsx";

const API = "2024-02-01";
const q = { "api-version": API };
const list = async (path) => (await restJson("GET", path, { query: q }).catch(() => ({ value: [] }))).value || [];

export default function StorageEdge({ a }) {
  const notify = useNotify();
  const sub = useSubscription();
  const origin = `${a.name}.blob.core.windows.net`;
  const eps = useAsync(async () => {
    const out = [];
    for (const p of await list(`/subscriptions/${sub.id}/providers/Microsoft.Cdn/profiles`)) {
      for (const ep of await list(`${p.id}/afdEndpoints`)) {
        for (const og of await list(`${p.id}/originGroups`)) {
          const origins = await list(`${og.id}/origins`);
          if (origins.some((o) => (o.properties?.hostName || "").toLowerCase() === origin)) out.push({ profile: p, ep, og });
        }
      }
    }
    return out;
  }, [sub.id, a.name]);
  const [name, setName] = useState(`${a.name}-edge`.slice(0, 40));
  const [ttl, setTtl] = useState("0.00:05:00");
  const [path, setPath] = useState("/");
  const [probe, setProbe] = useState(null);
  const [busy, setBusy] = useState(false);
  const put = (id, body) => restJson("PUT", id, { query: q, body });
  const create = async () => {
    setBusy(true);
    try {
      const base = `/subscriptions/${sub.id}/resourceGroups/${a.resourceGroup}/providers/Microsoft.Cdn/profiles/${name}`;
      await put(base, { location: "global", sku: { name: "Standard_AzureFrontDoor" }, properties: {} });
      await put(`${base}/afdEndpoints/${name}`, { location: "global", properties: { enabledState: "Enabled" } });
      const og = await put(`${base}/originGroups/default`, { properties: {} });
      await put(`${base}/originGroups/default/origins/blob`, { properties: { hostName: origin, originHostHeader: origin, priority: 1, weight: 1000 } });
      const rs = await put(`${base}/ruleSets/caching`, { properties: {} });
      await put(`${base}/ruleSets/caching/rules/ttl`, { properties: { order: 1, actions: [{ name: "CacheExpiration", parameters: { typeName: "DeliveryRuleCacheExpirationActionParameters", cacheBehavior: "Override", cacheType: "All", cacheDuration: ttl } }] } });
      await put(`${base}/afdEndpoints/${name}/routes/default`, { properties: { originGroup: { id: og.id }, ruleSets: [{ id: rs.id }], patternsToMatch: ["/*"], cacheConfiguration: { queryStringCachingBehavior: "IgnoreQueryString" }, supportedProtocols: ["Http", "Https"], forwardingProtocol: "MatchRequest" } });
      notify.success(`Front Door endpoint ${name} now caches ${origin}.`, "Created");
      eps.reload();
    } catch (e) { notify.error(e, "Create failed"); } finally { setBusy(false); }
  };
  const call = async (host, p, method = "GET", body) => {
    const r = await sendRaw(method, `/_edge/${host}${p}`, { headers: body ? { "content-type": "application/json" } : {}, body });
    return r;
  };
  const test = async (host) => { const r = await call(host, path); setProbe({ host, status: r.status, cache: r.headers.get("x-cache"), age: r.headers.get("age"), size: r.text.length }); };
  const purge = async (host) => { const r = await call(host, "/__purge", "POST", JSON.stringify({ contentPaths: ["/*"] })); notify.success(`Purged ${JSON.parse(r.text).purged} cached object(s).`, "Purge"); };
  const stats = useAsync(async () => { const o = {}; for (const e of eps.data || []) { const r = await call(e.ep.properties.hostName, "/__stats"); try { o[e.ep.id] = JSON.parse(r.text); } catch { /* none */ } } return o; }, [eps.data, probe]);
  return (
    <>
      <div className="vy-panel-title">Front Door and CDN</div>
      <p>A real caching edge in front of <code>{origin}</code>: requests to the endpoint are served from cache (<code>x-cache: TCP_HIT</code>) until the rule set's TTL expires or you purge. The container must allow anonymous blob read, as with a real public origin.</p>
      {eps.error && <ErrorBar error={eps.error} title="Could not list Front Door endpoints" />}
      {eps.loading && !eps.data ? <Loading /> : (
        <Table size="small" aria-label="Edge endpoints">
          <TableHeader><TableRow>{["Endpoint host", "Profile", "Requests", "Hits", "Misses", "Cached", ""].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
          <TableBody>
            {(eps.data || []).length === 0 && <TableRow><TableCell colSpan={7}>No Front Door endpoint is fronting this account.</TableCell></TableRow>}
            {(eps.data || []).map((e) => { const s = (stats.data || {})[e.ep.id] || {}; return (
              <TableRow key={e.ep.id}><TableCell>{e.ep.properties.hostName}</TableCell><TableCell>{e.profile.name}</TableCell><TableCell>{s.requests ?? 0}</TableCell><TableCell>{s.hits ?? 0}</TableCell><TableCell>{s.misses ?? 0}</TableCell><TableCell>{s.cachedObjects ?? 0}</TableCell>
                <TableCell><Button size="small" onClick={() => purge(e.ep.properties.hostName)}>Purge all</Button></TableCell></TableRow>); })}
          </TableBody>
        </Table>
      )}
      <h3>Test through the edge</h3>
      {(eps.data || []).slice(0, 1).map((e) => (
        <div key={e.ep.id} style={{ display: "flex", gap: 8, alignItems: "end" }}>
          <Field label="Path (/container/blob)"><Input value={path} onChange={(_, d) => setPath(d.value)} /></Field>
          <Button onClick={() => test(e.ep.properties.hostName)}>Fetch</Button>
          {probe && <span>HTTP {probe.status}, x-cache: <b>{probe.cache || "n/a"}</b>{probe.age ? `, age ${probe.age}s` : ""}, {probe.size} bytes</span>}
        </div>
      ))}
      <h3>Add an endpoint</h3>
      <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
        <Field label="Name"><Input value={name} onChange={(_, d) => setName(d.value)} /></Field>
        <Field label="Cache duration (d.hh:mm:ss)"><Input value={ttl} onChange={(_, d) => setTtl(d.value)} /></Field>
        <Button appearance="primary" disabled={busy || !name} onClick={create}>Create</Button>
      </div>
    </>
  );
}
