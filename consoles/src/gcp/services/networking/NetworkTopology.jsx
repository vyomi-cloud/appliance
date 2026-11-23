/* Network Intelligence Center > Network Topology: the project's VPC network, its subnets, firewall rules and the workloads and data
 * services around them, read from the real Google APIs (compute, run, sql, storage, pubsub) and drawn in the shared layered view. */
import { useMemo } from "react";
import { Box } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import InfraDiagram from "../../../common/infra-diagram/InfraDiagram.jsx";
import { GCP_PROFILE } from "../../kit/gcpDiagramProfile.js";
import { PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import * as net from "./api.js";
import * as compute from "../compute/api.js";
import * as storage from "../storage/api.js";
import * as sql from "../sql/api.js";
import * as pubsub from "../pubsub/api.js";
import * as run from "../run/api.js";

const tail = (u) => (u || "").split("/").pop();
const safe = async (f) => { try { return (await f()) || []; } catch { return []; } };

export default function NetworkTopology() {
  const project = useProject();
  const { data, loading } = useAsync(async () => {
    const [networks, subnets, firewalls, instances, buckets, sqls, topics, subs, services] = await Promise.all([
      safe(net.listNetworks), safe(net.listAllSubnets), safe(net.listFirewalls), safe(compute.listInstancesAllZones),
      safe(storage.listBuckets), safe(sql.listInstances), safe(pubsub.listTopics), safe(pubsub.listSubscriptions), safe(() => run.listServices("-")),
    ]);
    return { networks, subnets, firewalls, instances, buckets, sqls, topics, subs, services };
  }, [project]);

  const graph = useMemo(() => {
    if (!data) return null;
    const nodes = [], edges = [], id = (k, n) => `${k}.${n}`;
    const add = (type, name) => nodes.push({ id: id(type, name), label: name, type, status: "supported" });
    data.subnets.forEach((s) => { add("subnet", s.name); });
    data.firewalls.forEach((f) => { add("firewall", f.name); });
    data.instances.forEach((i) => { add("instance", i.name); (i.networkInterfaces || []).forEach((ni) => ni.subnetwork && edges.push({ from: id("instance", i.name), to: id("subnet", tail(ni.subnetwork)) })); });
    data.services.forEach((s) => add("run", tail(s.name)));
    data.buckets.forEach((b) => add("bucket", b.name));
    data.sqls.forEach((d) => add("sql", d.name));
    data.topics.forEach((t) => add("topic", tail(t.name)));
    data.subs.forEach((s) => { add("subscription", tail(s.name)); if (s.topic) edges.push({ from: id("topic", tail(s.topic)), to: id("subscription", tail(s.name)) }); });
    const have = new Set(nodes.map((n) => n.id));
    return { nodes, edges: edges.filter((e) => have.has(e.from) && have.has(e.to)), availability: {}, wrappers: { region: `Project · ${project}`, network: { label: `VPC network ${data.networks[0]?.name || "default"}` } } };
  }, [data, project]);

  return (
    <Box sx={{ p: 2 }}>
      <PageHeader title="Network Topology" />
      <Box>
        {loading || !graph ? <p>Loading…</p> : !graph.nodes.length ? <p>No resources in this project.</p> : <InfraDiagram graph={graph} profile={GCP_PROFILE} height={620} />}
      </Box>
    </Box>
  );
}
