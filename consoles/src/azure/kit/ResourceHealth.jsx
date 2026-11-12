/* Resource health blade body shared by every Azure resource blade: the real
 * Microsoft.ResourceHealth/availabilityStatuses/current read (core/azure_health_core.py). */
import { restJson } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, KV, Loading, fmtDate } from "./common.jsx";

const COLOR = { Available: "#107c10", Unavailable: "#d13438", Degraded: "#ca5010", Unknown: "#797775" };

/** scope: a resource id (current status) or a resource-group id (every resource in it). */
export default function ResourceHealth({ id, name, group = false, title }) {
  const url = `${id}/providers/Microsoft.ResourceHealth/availabilityStatuses${group ? "" : "/current"}`;
  const { data, loading, error, reload } = useAsync(() => restJson("GET", url, { query: { "api-version": "2022-10-01" } }), [url]);
  const rows = group ? data?.value || [] : data ? [data] : [];
  return (
    <>
      <div className="vy-panel-title">{title || `${name} | Resource health`}</div>
      <CapabilityContainer id="azure.common.resource_health" title="Health">
        <ErrorBar error={error} title="Failed to load resource health" />
        {loading ? <Loading /> : !rows.length ? <p>No resources in this scope.</p> : rows.map((s) => {
          const p = s.properties;
          return (
            <section className="vy-section" key={s.id} style={{ marginBottom: 12 }}>
              <h3 style={{ color: COLOR[p.availabilityState] }}>{group ? `${s.properties.resourceId.split("/").pop()} — ` : ""}{p.availabilityState}</h3>
              <p style={{ fontSize: 13 }}>{p.summary}</p>
              <KV label="Resource" value={p.resourceId} />
              <KV label="Reason type" value={p.reasonType || "--"} />
              <KV label="Reported" value={fmtDate(p.reportedTime)} />
            </section>
          );
        })}
        <section className="vy-section"><h3>Health history</h3>
          <p className="vy-muted" style={{ fontSize: 13 }}>No platform health events in the last 30 days. Vyomi runs no Azure platform that could cause an outage, so only the resource's own state (failed provisioning, stopped VM/cluster) changes its health.</p>
          <a href="#" onClick={(e) => { e.preventDefault(); reload(); }}>Refresh</a>
        </section>
      </CapabilityContainer>
    </>
  );
}
