/* Network Intelligence Center > Network Topology (native view by default: VPC networks > regions > subnets, workloads inside; Vyomi layered view is an opt-in addition): the project's VPC network, its subnets, firewall rules and the workloads and data
 * services around them, read from the real Google APIs (compute, run, sql, storage, pubsub) and drawn in the shared layered view. */
import { useMemo, useState } from "react";
import { Box, Chip, FormControlLabel, Checkbox, Typography } from "@mui/material";
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
  const [layered, setLayered] = useState(false);
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


  const byNet = useMemo(() => {
    if (!data) return [];
    return data.networks.map((n) => {
      const subs = data.subnets.filter((s) => tail(s.network) === n.name), regions = {};
      subs.forEach((s) => { (regions[tail(s.region)] = regions[tail(s.region)] || []).push(s); });
      return { n, regions, vms: data.instances.filter((i) => tail(i.networkInterfaces?.[0]?.network) === n.name) };
    });
  }, [data]);
  const NativeView = () => (
    <Box>
      {byNet.map(({ n, regions, vms }) => (
        <Box key={n.name} sx={{ border: "1px solid #dadce0", borderRadius: 1, p: 1.5, mb: 2 }}>
          <Typography fontWeight={500}>VPC network: {n.name}</Typography>
          {Object.entries(regions).map(([r, ss]) => (
            <Box key={r} sx={{ border: "1px dashed #bdc1c6", borderRadius: 1, p: 1, mt: 1 }}>
              <Typography variant="body2" color="text.secondary">{r}</Typography>
              {ss.map((s) => <Chip key={s.name} size="small" sx={{ m: 0.5 }} label={`${s.name} ${s.ipCidrRange}`} />)}
            </Box>
          ))}
          {vms.length > 0 && <Typography variant="body2" sx={{ mt: 1 }}>VM instances: {vms.map((v) => v.name).join(", ")}</Typography>}
        </Box>
      ))}
      <Typography variant="body2" color="text.secondary">Also in this project: {graph.nodes.filter((x) => !/^(subnet|firewall|instance)$/.test(x.type)).map((x) => x.label).join(", ") || "nothing else"}.</Typography>
    </Box>
  );
  return (
    <Box sx={{ p: 2 }}>
      <PageHeader title="Network Topology" />
      <Box>
        <FormControlLabel control={<Checkbox checked={layered} onChange={(e) => setLayered(e.target.checked)} />} label="Vyomi layered view (users → gateway → services → data)" />
        {loading || !graph ? <p>Loading…</p> : !graph.nodes.length && !byNet.length ? <p>No resources in this project.</p> : layered ? <InfraDiagram graph={graph} profile={GCP_PROFILE} height={620} /> : <NativeView />}
      </Box>
    </Box>
  );
}
