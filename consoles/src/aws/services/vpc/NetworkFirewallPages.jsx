/* AWS Network Firewall console pages over the native JSON wire (core/netfw_core.py). */
import Box from "@cloudscape-design/components/box";
import Table from "@cloudscape-design/components/table";
import { ResourceList } from "./Crud.jsx";
import * as nf from "./apiNfw.js";
import * as x from "./apiExtras.js";

const col = (id, header, cell, extra = {}) => ({ id, header, cell, ...extra });
const arnOpts = (load, filter = () => true) => async () => (await load()).filter(filter).map((r) => ({ value: r.Arn, label: r.Name }));
const vpcOpts = async () => (await x.describeVpcs()).map((v) => ({ value: v.VpcId, label: v.VpcId }));
const subnetOpts = async () => (await x.describeSubnets()).map((s) => ({ value: s.SubnetId, label: `${s.SubnetId} (${s.CidrBlock})` }));
const Sub = ({ title, items, columns, empty }) => <Table variant="container" header={<Box variant="h3">{title}</Box>} items={items} columnDefinitions={columns} empty={<Box textAlign="center">{empty || "None"}</Box>} />;

export const Firewalls = () => (
  <ResourceList title="Firewalls" capId="aws.vpc.network-firewall" trackBy="Id" load={nf.listFirewalls}
    columns={[col("n", "Name", (r) => r.Name, { isRowHeader: true }), col("st", "Status", (r) => r.Status), col("sync", "Configuration sync", (r) => r.Sync), col("pol", "Firewall policy", (r) => r.Policy.split("/").pop()), col("vpc", "VPC", (r) => r.Vpc),
      col("sub", "Subnets", (r) => r.Subnets.join(", ")), col("dp", "Delete protection", (r) => (r.DeleteProtection ? "Enabled" : "Disabled"))]}
    create={{ label: "Create firewall", fields: [{ key: "name", label: "Name", required: true }, { key: "description", label: "Description" },
      { key: "vpc", label: "VPC", type: "select", required: true, options: vpcOpts }, { key: "subnet", label: "Firewall subnet", type: "select", required: true, options: subnetOpts },
      { key: "policy", label: "Associated firewall policy", type: "select", required: true, options: arnOpts(nf.listPolicies) }, { key: "deleteProtection", label: "Enable delete protection", type: "checkbox" }], submit: (v) => nf.createFirewall(v) }}
    actions={[
      { text: "Associate policy", needs: "one", fields: [{ key: "policy", label: "Firewall policy", type: "select", required: true, options: arnOpts(nf.listPolicies) }], submit: ([f], v) => nf.associateFirewallPolicy(f, v.policy) },
      { text: "Add subnet", needs: "one", fields: [{ key: "subnet", label: "Subnet", type: "select", required: true, options: subnetOpts }], submit: ([f], v) => nf.associateSubnet(f, v.subnet) },
      { text: "Toggle delete protection", needs: "one", submit: ([f]) => nf.setDeleteProtection(f, !f.DeleteProtection) },
      { text: "Edit logging", needs: "one", fields: [{ key: "type", label: "Log type", type: "select", required: true, default: "ALERT", options: ["ALERT", "FLOW", "TLS"] }, { key: "bucket", label: "S3 bucket name", required: true }], submit: ([f], v) => nf.putLogging(f, v.type, v.bucket) },
    ]}
    del={{ label: "Delete", type: "firewall", run: (r) => nf.deleteFirewall(r) }}
    detail={(f) => [
      { id: "details", label: "Firewall details", content: <Sub title="Details" items={[{ k: "ARN", v: f.Arn }, { k: "Policy", v: f.Policy }, { k: "Policy change protection", v: String(f.PolicyProtection) }, { k: "Subnet change protection", v: String(f.SubnetProtection) }, { k: "Description", v: f.Description || "-" }]} columns={[col("k", "Property", (r) => r.k), col("v", "Value", (r) => r.v)]} /> },
      { id: "endpoints", label: "Firewall endpoints", content: <Sub title="Firewall endpoints" items={f.Endpoints} columns={[col("az", "Availability Zone", (r) => r.Az), col("s", "Subnet", (r) => r.Subnet), col("e", "Endpoint ID", (r) => r.Endpoint), col("st", "Status", (r) => r.Status)]} /> },
      { id: "logging", label: "Logging", content: <Sub title="Logging configuration" empty="No logging destinations configured" items={f.Logging} columns={[col("t", "Log type", (r) => r.LogType), col("d", "Destination type", (r) => r.LogDestinationType), col("l", "Destination", (r) => JSON.stringify(r.LogDestination))]} /> },
    ]} />
);

export const FirewallPolicies = () => (
  <ResourceList title="Firewall policies" capId="aws.vpc.network-firewall" trackBy="Id" load={nf.listPolicies}
    columns={[col("n", "Name", (r) => r.Name, { isRowHeader: true }), col("st", "Status", (r) => r.Status), col("sl", "Stateless default action", (r) => r.StatelessDefault), col("rg", "Rule groups", (r) => r.StatelessRG.length + r.StatefulRG.length), col("a", "Associated firewalls", (r) => r.Assoc), col("d", "Description", (r) => r.Description || "-")]}
    create={{ label: "Create firewall policy", fields: [{ key: "name", label: "Name", required: true }, { key: "description", label: "Description" },
      { key: "statelessDefault", label: "Stateless default action", type: "select", default: "aws:forward_to_sfe", options: ["aws:pass", "aws:drop", "aws:forward_to_sfe"] },
      { key: "fragmentDefault", label: "Stateless fragment default action", type: "select", default: "aws:forward_to_sfe", options: ["aws:pass", "aws:drop", "aws:forward_to_sfe"] },
      { key: "statelessRg", label: "Stateless rule group", type: "select", options: arnOpts(nf.listRuleGroups, (g) => g.Type === "STATELESS") },
      { key: "statefulRg", label: "Stateful rule group", type: "select", options: arnOpts(nf.listRuleGroups, (g) => g.Type === "STATEFUL") }], submit: (v) => nf.createPolicy(v) }}
    del={{ label: "Delete", type: "firewall policy", run: (r) => nf.deletePolicy(r) }}
    detail={(p) => [{ id: "rg", label: "Rule groups", content: <Sub title="Rule group references" items={[...p.StatelessRG.map((r) => ({ arn: r.ResourceArn, kind: "Stateless", prio: r.Priority })), ...p.StatefulRG.map((r) => ({ arn: r.ResourceArn, kind: "Stateful", prio: r.Priority ?? "-" }))]} columns={[col("k", "Type", (r) => r.kind), col("a", "Rule group", (r) => r.arn.split("/").pop()), col("p", "Priority", (r) => r.prio)]} /> }]} />
);

export const NetworkFirewallRuleGroups = () => (
  <ResourceList title="Network Firewall rule groups" capId="aws.vpc.network-firewall" trackBy="Id" load={nf.listRuleGroups}
    columns={[col("n", "Name", (r) => r.Name, { isRowHeader: true }), col("t", "Type", (r) => r.Type), col("k", "Rules source", (r) => r.Kind), col("c", "Capacity", (r) => r.Capacity), col("u", "Consumed", (r) => r.Consumed), col("a", "Policies using it", (r) => r.Assoc)]}
    create={{ label: "Create rule group", fields: [{ key: "name", label: "Name", required: true }, { key: "type", label: "Rule group type", type: "select", required: true, default: "STATEFUL", options: ["STATEFUL", "STATELESS"] }, { key: "capacity", label: "Capacity", required: true, default: "100" }, { key: "description", label: "Description" },
      { key: "mode", label: "Stateful rule source", type: "select", default: "suricata", options: [{ value: "suricata", label: "Suricata compatible rules" }, { value: "domains", label: "Domain list" }], showIf: (v) => v.type !== "STATELESS" },
      { key: "rules", label: "Suricata compatible rules (one per line)", type: "textarea", placeholder: 'drop tcp any any -> any 4444 (msg:"block"; sid:1;)', showIf: (v) => v.type !== "STATELESS" && v.mode !== "domains" },
      { key: "listType", label: "Domain list type", type: "select", default: "ALLOWLIST", options: ["ALLOWLIST", "DENYLIST"], showIf: (v) => v.type !== "STATELESS" && v.mode === "domains" },
      { key: "domains", label: "Domains (comma or space separated, e.g. .example.com)", showIf: (v) => v.type !== "STATELESS" && v.mode === "domains" },
      { key: "priority", label: "Stateless rule priority", default: "1", showIf: (v) => v.type === "STATELESS" }, { key: "action", label: "Stateless action", type: "select", default: "aws:pass", options: ["aws:pass", "aws:drop", "aws:forward_to_sfe"], showIf: (v) => v.type === "STATELESS" },
      { key: "protocol", label: "Protocol number (6=TCP, 17=UDP)", showIf: (v) => v.type === "STATELESS" }, { key: "src", label: "Source CIDR", showIf: (v) => v.type === "STATELESS" }, { key: "dst", label: "Destination CIDR", showIf: (v) => v.type === "STATELESS" }, { key: "dport", label: "Destination port", showIf: (v) => v.type === "STATELESS" }], submit: (v) => nf.createRuleGroup(v) }}
    del={{ label: "Delete", type: "rule group", run: (r) => nf.deleteRuleGroup(r) }}
    detail={(g) => [{ id: "rules", label: "Rules", content: <Box padding="s"><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{g.Rules}</pre></Box> }]} />
);

export const TlsInspectionConfigurations = () => (
  <ResourceList title="TLS inspection configurations" capId="aws.vpc.network-firewall" trackBy="Id" load={nf.listTls}
    columns={[col("n", "Name", (r) => r.Name, { isRowHeader: true }), col("st", "Status", (r) => r.Status), col("c", "Server certificates", (r) => r.Certs), col("d", "Description", (r) => r.Description || "-")]}
    create={{ label: "Create TLS inspection configuration", fields: [{ key: "name", label: "Name", required: true }, { key: "description", label: "Description" }, { key: "cert", label: "Server certificate (ACM ARN)", required: true, placeholder: "arn:aws:acm:us-east-1:123456789012:certificate/..." }], submit: (v) => nf.createTls(v) }}
    del={{ label: "Delete", type: "TLS inspection configuration", run: (r) => nf.deleteTls(r) }} />
);

export const NetworkFirewallResourceGroups = () => (
  <ResourceList title="Network Firewall resource groups" capId="aws.vpc.network-firewall" trackBy="Id" load={nf.listResourcePolicies}
    columns={[col("n", "Resource", (r) => r.Name, { isRowHeader: true }), col("k", "Type", (r) => r.Kind), col("p", "Resource policy", (r) => (r.Policy ? "Attached" : "None"))]}
    actions={[{ text: "Put resource policy", needs: "one", label: "Save", fields: [{ key: "policy", label: "Resource policy (JSON)", type: "textarea", required: true, placeholder: '{"Version":"2012-10-17","Statement":[...]}' }], submit: ([r], v) => nf.putResourcePolicy(r.Arn, v.policy) },
      { text: "Remove resource policy", needs: "one", submit: ([r]) => nf.deleteResourcePolicy(r.Arn) }]}
    detail={(r) => [{ id: "policy", label: "Policy", content: <Box padding="s"><pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{r.Policy || "No resource policy attached"}</pre></Box> }]} />
);

export const VpcEndpointAssociations = () => (
  <ResourceList title="VPC endpoint associations" capId="aws.vpc.network-firewall" trackBy="Id" load={nf.listEndpointAssociations}
    columns={[col("id", "Association", (r) => r.Arn.split("/").pop(), { isRowHeader: true }), col("fw", "Firewall", (r) => r.Firewall.split("/").pop()), col("v", "VPC", (r) => r.Vpc), col("s", "Subnet", (r) => r.Subnet), col("st", "Status", (r) => r.Status)]}
    create={{ label: "Create VPC endpoint association", fields: [{ key: "firewall", label: "Firewall", type: "select", required: true, options: arnOpts(nf.listFirewalls) }, { key: "vpc", label: "VPC (not the firewall's own VPC)", type: "select", required: true, options: vpcOpts }, { key: "subnet", label: "Subnet", type: "select", required: true, options: subnetOpts }, { key: "description", label: "Description" }], submit: (v) => nf.createEndpointAssociation(v) }}
    del={{ label: "Delete", type: "VPC endpoint association", run: (r) => nf.deleteEndpointAssociation(r) }} />
);
