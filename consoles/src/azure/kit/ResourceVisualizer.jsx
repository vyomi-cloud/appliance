/* Resource visualizer shared by the Azure blades: the resources of a resource group and the real
 * ARM references between them (any property value that is another resource's id), drawn as a
 * graph. Read from the real ARM resource list — nothing is invented. */
import { useMemo } from "react";
import { restJson } from "../../common/wire.js";
import InfraDiagram from "../../common/infra-diagram/InfraDiagram.jsx";
import { AZURE_PROFILE } from "./azureDiagramProfile.js";
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
  const graph = useMemo(() => {
    const gn = nodes.map((n) => ({ id: n.id.toLowerCase(), label: n.name, type: (n.type || "").toLowerCase(), kind: n.kind, status: "supported" }));
    const vnet = nodes.find((n) => /^microsoft\.network\/virtualnetworks$/i.test(n.type || ""));
    const cidr = vnet?.properties?.addressSpace?.addressPrefixes?.[0];
    return { nodes: gn, edges: edges.map(([from, to]) => ({ from, to })), availability: {}, wrappers: { region: `Resource group · ${resourceGroup}`, network: vnet ? { label: `Virtual network ${vnet.name}`, cidr } : { label: "Resources" } } };
  }, [data, resourceGroup]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <CapabilityContainer id={capId || "azure.common.resource_visualizer"} title={title || `${resourceGroup} | Resource visualizer`}>
      <ErrorBar error={error} />
      {loading ? <Loading /> : !nodes.length ? <p>No resources in this resource group.</p> : (
        <InfraDiagram graph={graph} profile={AZURE_PROFILE} height={600} />
      )}
      <p className="vy-muted" style={{ fontSize: 12 }}>{nodes.length} resource{nodes.length === 1 ? "" : "s"} and {edges.length} reference{edges.length === 1 ? "" : "s"} between them (a reference is any stored property holding another resource's id).</p>
    </CapabilityContainer>
  );
}
