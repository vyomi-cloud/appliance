/* VPC > Container associations: attach a Network Firewall to an EKS cluster's node networks (Vyomi-simulated control plane in
 * core/netfw_core.py: CreateContainerAssociation & co; capability aws.vpc.network-firewall-containers). */
import Box from "@cloudscape-design/components/box";
import Table from "@cloudscape-design/components/table";
import { ResourceList } from "./Crud.jsx";
import * as nf from "./apiNfw.js";
import * as eks from "../eks/api.js";
import SimPanel from "../../kit/SimPanel.jsx";

const col = (id, header, cell, extra = {}) => ({ id, header, cell, ...extra });
const firewallOpts = async () => (await nf.listFirewalls()).map((f) => ({ value: f.Arn, label: f.Name }));
const clusterOpts = async () => (await eks.listClusterNames()).map((n) => ({ value: n, label: n }));

export const ContainerAssociations = () => (
  <ResourceList title="Container associations" capId="aws.vpc.network-firewall-containers" trackBy="Id" load={nf.listContainerAssociations}
    empty="Associate a Network Firewall with an Amazon EKS cluster so its node networks are inspected by the firewall policy."
    columns={[col("id", "Association ID", (r) => r.Id, { isRowHeader: true }), col("fw", "Firewall", (r) => r.Firewall), col("t", "Platform", (r) => r.ClusterType), col("c", "Cluster", (r) => r.Cluster),
      col("v", "VPC", (r) => r.Vpc), col("st", "Status", (r) => r.Status)]}
    create={{ label: "Create container association", fields: [
      { key: "firewall", label: "Firewall", type: "select", required: true, options: firewallOpts },
      { key: "cluster", label: "Amazon EKS cluster", type: "select", required: true, options: clusterOpts },
      { key: "description", label: "Description" }], submit: (v) => nf.createContainerAssociation(v) }}
    del={{ label: "Delete", type: "container association", run: (r) => nf.deleteContainerAssociation(r) }}
    detail={(a) => [
      { id: "details", label: "Details", content: <Table variant="container" header={<Box variant="h3">Details</Box>} trackBy="k" items={[
        { k: "ARN", v: a.Arn }, { k: "Firewall", v: a.FirewallArn }, { k: "Cluster", v: `${a.ClusterType} ${a.Cluster}` }, { k: "VPC", v: a.Vpc }, { k: "Cluster subnets", v: a.Subnets.join(", ") || "-" },
        { k: "Protected node networks", v: a.Cidrs.join(", ") || "-" }, { k: "Firewall endpoints", v: a.Endpoints.join(", ") }, { k: "Description", v: a.Description || "-" }]}
        columnDefinitions={[col("k", "Property", (r) => r.k), col("v", "Value", (r) => r.v)]} /> },
      { id: "sim", label: "Simulate traffic", content: <SimPanel key={a.Id} title="Simulate traffic" testId="casc" description="Runs one packet from the cluster's node network through the associated firewall's policy. Simulator verb: SimulateContainerTraffic."
        fields={[{ key: "proto", label: "Protocol", default: "tcp", options: ["tcp", "udp", "icmp"].map((m) => ({ value: m, label: m })) }, { key: "src", label: "Source IP (inside a protected network)", default: (a.Cidrs[0] || "10.0.1.0/24").replace(/\.\d+\/\d+$/, ".10") },
          { key: "dst", label: "Destination IP", default: "93.184.216.34" }, { key: "dport", label: "Destination port", default: "443" }]}
        run={(v) => nf.simulateContainerTraffic(a.Id, { Protocol: v.proto, SourceIp: v.src, DestinationIp: v.dst, SourcePort: 40000, DestinationPort: Number(v.dport) || undefined })}
        verdict={(r) => [r.Action === "PASS" ? "success" : "warning", `${r.Action} at the ${r.Stage} stage (rule: ${r.Rule})`]} /> },
    ]} />
);
