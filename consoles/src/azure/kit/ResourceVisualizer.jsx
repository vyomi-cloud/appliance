/* Resource visualizer shared by the Azure blades: the resources of a resource group and the real
 * ARM references between them (any property value that is another resource's id), drawn as a
 * graph. Read from the real ARM resource list — nothing is invented. */
import { restJson } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import { getSubscription } from "./arm.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, Loading } from "./common.jsx";

const ids = (v, out = new Set()) => { if (typeof v === "string") { if (/^\/subscriptions\/.+\/providers\//i.test(v)) out.add(v.toLowerCase()); } else if (v && typeof v === "object") Object.values(v).forEach((x) => ids(x, out)); return out; };

export default function ResourceVisualizer({ resourceGroup, focus, title, capId }) {
  const { data, loading, error } = useAsync(async () => (await restJson("GET", `/subscriptions/${getSubscription()}/resourcegroups/${encodeURIComponent(resourceGroup)}/resources`, { query: { "api-version": "2021-04-01" } })).value || [], [resourceGroup]);
  const nodes = (data || []).filter((r) => !/\/(events|suppressions)$/i.test(r.type || ""));
  const byId = Object.fromEntries(nodes.map((n) => [n.id.toLowerCase(), n]));
  const edges = [];
  nodes.forEach((n) => ids(n.properties).forEach((t) => { if (t !== n.id.toLowerCase() && byId[t]) edges.push([n.id.toLowerCase(), t]); }));
  const W = 760, H = 460, cx = W / 2, cy = H / 2, R = Math.min(cx, cy) - 70;
  const pos = Object.fromEntries(nodes.map((n, i) => { const a = (2 * Math.PI * i) / Math.max(nodes.length, 1) - Math.PI / 2; return [n.id.toLowerCase(), [cx + R * Math.cos(a), cy + R * Math.sin(a)]]; }));
  return (
    <CapabilityContainer id={capId || "azure.common.resource_visualizer"} title={title || `${resourceGroup} | Resource visualizer`}>
      <ErrorBar error={error} />
      {loading ? <Loading /> : !nodes.length ? <p>No resources in this resource group.</p> : (
        <svg role="img" aria-label="Resource visualizer graph" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W, border: "1px solid var(--colorNeutralStroke2)", borderRadius: 4 }}>
          {edges.map(([a, b], i) => <line key={i} x1={pos[a][0]} y1={pos[a][1]} x2={pos[b][0]} y2={pos[b][1]} stroke="#8a8886" strokeWidth="1.5" />)}
          {nodes.map((n) => { const [x, y] = pos[n.id.toLowerCase()]; const hot = focus && n.name.toLowerCase() === focus.toLowerCase(); return (
            <g key={n.id} data-testid="viz-node"><circle cx={x} cy={y} r={hot ? 22 : 16} fill={hot ? "#0078d4" : "#c7e0f4"} stroke="#0078d4" />
              <text x={x} y={y + 34} textAnchor="middle" fontSize="11" fill="currentColor">{n.name}</text>
              <text x={x} y={y + 46} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.7">{(n.type || "").split("/").pop()}</text></g>); })}
        </svg>
      )}
      <p className="vy-muted" style={{ fontSize: 12 }}>{nodes.length} resource{nodes.length === 1 ? "" : "s"} and {edges.length} reference{edges.length === 1 ? "" : "s"} between them (a reference is any stored property holding another resource's id).</p>
    </CapabilityContainer>
  );
}
