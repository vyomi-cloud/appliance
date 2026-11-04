/* Real gateway data plane views for API Management (core/azure_apim_gateway_core.py): the Capacity gauge and
 * request analytics are derived from requests that really went through the simulated gateway, and "Test the
 * gateway" sends one. See azure.apim.gateway.* in core/capabilities/azure/apim.json. */
import { useState } from "react";
import { Button, Field, Input, Select } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import { KV, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

export function CapacityGauge({ a }) {
  const { data, loading, error, reload } = useAsync(() => api.gatewayAnalytics(a.resourceGroup, a.name), [a.id]);
  if (loading && !data) return <Loading />;
  if (error) return <p role="alert">Failed to load gateway capacity: {String(error.message || error)}</p>;
  const c = data.capacity;
  return (
    <section className="vy-section" aria-label="Capacity">
      <h3>Capacity</h3>
      <div role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={c.percent} aria-label="Gateway capacity"
        style={{ height: 14, maxWidth: 420, background: "var(--colorNeutralBackground5, #e6e6e6)", borderRadius: 7, overflow: "hidden" }}>
        <div style={{ width: `${Math.max(c.percent, 1)}%`, height: "100%", background: c.percent > 80 ? "#d13438" : c.percent > 50 ? "#ffb900" : "#107c10" }} />
      </div>
      <div className="vy-props" style={{ marginTop: 12 }}>
        <KV label="Capacity" value={`${c.percent} %`} />
        <KV label="Units" value={c.units} />
        <KV label="Requests (last 60 s)" value={`${data.requestsPerSecond60s} req/s`} />
        <KV label="Requests (last hour)" value={data.totalRequests} />
      </div>
      <p className="vy-muted" style={{ fontSize: 12 }}>{c.basis}</p>
      <Button size="small" onClick={reload}>Refresh</Button>
    </section>
  );
}

const Table = ({ title, rows }) => (
  <section className="vy-section">
    <h3>{title}</h3>
    <table className="vy-grid"><thead><tr><th>Name</th><th>Requests</th></tr></thead>
      <tbody>{Object.entries(rows).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}
        {!Object.keys(rows).length && <tr><td colSpan={2} className="vy-muted">No requests yet</td></tr>}</tbody></table>
  </section>
);

export function RequestAnalytics({ a }) {
  const { data, loading, reload } = useAsync(() => api.gatewayAnalytics(a.resourceGroup, a.name), [a.id]);
  const [m, setM] = useState("GET");
  const [path, setPath] = useState("");
  const [key, setKey] = useState("");
  const [res, setRes] = useState(null);
  const send = async () => { setRes(await api.gatewayCall(a.name, m, path, { key })); reload(); };
  return (
    <>
      <section className="vy-section">
        <h3>Test the gateway</h3>
        <p className="vy-muted" style={{ fontSize: 13 }}>Sends a real request through this service's simulated gateway ({api.gatewayUrl(a.name)} maps to /azure-data/apim/{a.name}/).</p>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
          <Field label="Method"><Select value={m} onChange={(_, d) => setM(d.value)}>{["GET", "POST", "PUT", "DELETE"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
          <Field label="Path (api-path/operation)"><Input value={path} onChange={(_, d) => setPath(d.value)} placeholder="echo/resource/1" /></Field>
          <Field label="Subscription key"><Input value={key} onChange={(_, d) => setKey(d.value)} /></Field>
          <Button appearance="primary" onClick={send} disabled={!path.trim()}>Send</Button>
        </div>
        {res && <pre aria-label="Gateway response" style={{ fontSize: 12 }}>{res.status} {typeof res.body === "string" ? res.body : JSON.stringify(res.body, null, 1)}</pre>}
      </section>
      {loading && !data ? <Loading /> : data && (
        <>
          <div className="vy-props"><KV label="Requests (last hour)" value={data.totalRequests} /><KV label="Failed (4xx/5xx)" value={data.failedRequests} />
            <KV label="Avg latency" value={`${data.avgLatencyMs} ms`} /><KV label="p95 latency" value={`${data.p95LatencyMs} ms`} /></div>
          <Table title="Status classes" rows={data.statusClasses} />
          <Table title="Requests by API" rows={data.byApi} />
          <Table title="Requests by operation" rows={data.byOperation} />
          <Table title="Requests by subscription" rows={data.bySubscription} />
        </>
      )}
    </>
  );
}
