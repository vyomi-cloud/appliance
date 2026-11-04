/* AWS Network Firewall (JSON 1.0, NetworkFirewall_20201112) — firewalls, policies, rule groups, TLS inspection, resource policies, logging, endpoint associations. */
import { awsJson } from "../../../common/wire.js";

const call = (op, body) => awsJson("network-firewall", `NetworkFirewall_20201112.${op}`, body, { version: "1.0" });
const tagMap = (t) => Object.fromEntries((t || []).map((x) => [x.Key, x.Value]));
const tags = (name) => (name ? [{ Key: "Name", Value: name }] : undefined);

export const listFirewalls = async () => {
  const names = (await call("ListFirewalls", {})).Firewalls || [];
  return Promise.all(names.map(async (f) => {
    const d = await call("DescribeFirewall", { FirewallArn: f.FirewallArn });
    const lg = await call("DescribeLoggingConfiguration", { FirewallArn: f.FirewallArn }).catch(() => ({}));
    const fw = d.Firewall;
    return { Id: fw.FirewallArn, Name: fw.FirewallName, Arn: fw.FirewallArn, Policy: fw.FirewallPolicyArn, Vpc: fw.VpcId, Status: d.FirewallStatus?.Status, Sync: d.FirewallStatus?.ConfigurationSyncStateSummary,
      Subnets: fw.SubnetMappings.map((s) => s.SubnetId), Endpoints: Object.entries(d.FirewallStatus?.SyncStates || {}).map(([az, s]) => ({ Az: az, Subnet: s.Attachment.SubnetId, Endpoint: s.Attachment.EndpointId, Status: s.Attachment.Status })),
      DeleteProtection: fw.DeleteProtection, PolicyProtection: fw.FirewallPolicyChangeProtection, SubnetProtection: fw.SubnetChangeProtection, Description: fw.Description, Token: d.UpdateToken,
      Logging: lg.LoggingConfiguration?.LogDestinationConfigs || [], Tags: tagMap(fw.Tags) };
  }));
};
export const createFirewall = (v) => call("CreateFirewall", { FirewallName: v.name, FirewallPolicyArn: v.policy, VpcId: v.vpc, SubnetMappings: [{ SubnetId: v.subnet }], DeleteProtection: !!v.deleteProtection, Description: v.description || undefined });
export const deleteFirewall = (f) => call("DeleteFirewall", { FirewallArn: f.Arn });
export const associateFirewallPolicy = (f, policy) => call("AssociateFirewallPolicy", { FirewallArn: f.Arn, FirewallPolicyArn: policy, UpdateToken: f.Token });
export const associateSubnet = (f, subnet) => call("AssociateSubnets", { FirewallArn: f.Arn, SubnetMappings: [{ SubnetId: subnet }], UpdateToken: f.Token });
export const disassociateSubnet = (f, subnet) => call("DisassociateSubnets", { FirewallArn: f.Arn, SubnetIds: [subnet], UpdateToken: f.Token });
export const setDeleteProtection = (f, on) => call("UpdateFirewallDeleteProtection", { FirewallArn: f.Arn, DeleteProtection: on, UpdateToken: f.Token });
export const putLogging = (f, type, bucket) => call("UpdateLoggingConfiguration", { FirewallArn: f.Arn, LoggingConfiguration: { LogDestinationConfigs: [...(f.Logging || []).filter((l) => l.LogType !== type), { LogType: type, LogDestinationType: "S3", LogDestination: { bucketName: bucket, prefix: "netfw" } }] } });
export const removeLogging = (f, type) => call("UpdateLoggingConfiguration", { FirewallArn: f.Arn, LoggingConfiguration: { LogDestinationConfigs: (f.Logging || []).filter((l) => l.LogType !== type) } });

export const listPolicies = async () => {
  const items = (await call("ListFirewallPolicies", {})).FirewallPolicies || [];
  return Promise.all(items.map(async (p) => {
    const d = await call("DescribeFirewallPolicy", { FirewallPolicyArn: p.Arn }); const r = d.FirewallPolicyResponse;
    return { Id: r.FirewallPolicyArn, Name: r.FirewallPolicyName, Arn: r.FirewallPolicyArn, Description: r.Description || "", Status: r.FirewallPolicyStatus, Assoc: r.NumberOfAssociations,
      StatelessDefault: (d.FirewallPolicy.StatelessDefaultActions || []).join(", "), StatelessRG: d.FirewallPolicy.StatelessRuleGroupReferences || [], StatefulRG: d.FirewallPolicy.StatefulRuleGroupReferences || [],
      Doc: d.FirewallPolicy, Token: d.UpdateToken, Tags: tagMap(r.Tags) };
  }));
};
export const createPolicy = (v) => call("CreateFirewallPolicy", { FirewallPolicyName: v.name, Description: v.description || undefined, Tags: tags(v.nameTag),
  FirewallPolicy: { StatelessDefaultActions: [v.statelessDefault || "aws:forward_to_sfe"], StatelessFragmentDefaultActions: [v.fragmentDefault || "aws:forward_to_sfe"],
    StatelessRuleGroupReferences: v.statelessRg ? [{ ResourceArn: v.statelessRg, Priority: 1 }] : undefined, StatefulRuleGroupReferences: v.statefulRg ? [{ ResourceArn: v.statefulRg }] : undefined } });
export const deletePolicy = (p) => call("DeleteFirewallPolicy", { FirewallPolicyArn: p.Arn });

export const listRuleGroups = async () => {
  const items = (await call("ListRuleGroups", {})).RuleGroups || [];
  return Promise.all(items.map(async (g) => {
    const d = await call("DescribeRuleGroup", { RuleGroupArn: g.Arn }); const r = d.RuleGroupResponse; const src = d.RuleGroup?.RulesSource || {};
    return { Id: r.RuleGroupArn, Name: r.RuleGroupName, Arn: r.RuleGroupArn, Type: r.Type, Capacity: r.Capacity, Consumed: r.ConsumedCapacity, Description: r.Description || "", Assoc: r.NumberOfAssociations,
      Kind: src.RulesString !== undefined ? "Suricata compatible rules" : src.RulesSourceList ? `Domain list (${src.RulesSourceList.GeneratedRulesType})` : src.StatefulRules ? "5-tuple rules" : "Stateless rules",
      Rules: src.RulesString ?? JSON.stringify(src.RulesSourceList || src.StatefulRules || src.StatelessRulesAndCustomActions || {}, null, 1), Token: d.UpdateToken, Tags: tagMap(r.Tags) };
  }));
};
export function createRuleGroup(v) {
  const base = { RuleGroupName: v.name, Type: v.type, Capacity: Number(v.capacity), Description: v.description || undefined };
  if (v.type === "STATELESS") {
    return call("CreateRuleGroup", { ...base, RuleGroup: { RulesSource: { StatelessRulesAndCustomActions: { StatelessRules: [{ Priority: Number(v.priority || 1), RuleDefinition: { Actions: [v.action || "aws:pass"],
      MatchAttributes: { Protocols: v.protocol ? [Number(v.protocol)] : undefined, Sources: v.src ? [{ AddressDefinition: v.src }] : undefined, Destinations: v.dst ? [{ AddressDefinition: v.dst }] : undefined,
        DestinationPorts: v.dport ? [{ FromPort: Number(v.dport), ToPort: Number(v.dport) }] : undefined } } }] } } } });
  }
  if (v.mode === "domains") {
    return call("CreateRuleGroup", { ...base, RuleGroup: { RulesSource: { RulesSourceList: { Targets: v.domains.split(/[\s,]+/).filter(Boolean), TargetTypes: ["HTTP_HOST", "TLS_SNI"], GeneratedRulesType: v.listType || "ALLOWLIST" } } } });
  }
  return call("CreateRuleGroup", { ...base, Rules: v.rules });
}
export const deleteRuleGroup = (g) => call("DeleteRuleGroup", { RuleGroupArn: g.Arn });

export const listTls = async () => {
  const items = (await call("ListTLSInspectionConfigurations", {})).TLSInspectionConfigurations || [];
  return Promise.all(items.map(async (t) => {
    const d = await call("DescribeTLSInspectionConfiguration", { TLSInspectionConfigurationArn: t.Arn }); const r = d.TLSInspectionConfigurationResponse;
    return { Id: r.TLSInspectionConfigurationArn, Name: r.TLSInspectionConfigurationName, Arn: r.TLSInspectionConfigurationArn, Status: r.TLSInspectionConfigurationStatus, Description: r.Description || "",
      Certs: (d.TLSInspectionConfiguration.ServerCertificateConfigurations || []).flatMap((c) => (c.ServerCertificates || []).map((x) => x.ResourceArn)).join(", ") || "-" };
  }));
};
export const createTls = (v) => call("CreateTLSInspectionConfiguration", { TLSInspectionConfigurationName: v.name, Description: v.description || undefined,
  TLSInspectionConfiguration: { ServerCertificateConfigurations: [{ ServerCertificates: [{ ResourceArn: v.cert }], Scopes: [{ Protocols: [6], Sources: [{ AddressDefinition: "0.0.0.0/0" }], Destinations: [{ AddressDefinition: "0.0.0.0/0" }], SourcePorts: [{ FromPort: 0, ToPort: 65535 }], DestinationPorts: [{ FromPort: 443, ToPort: 443 }] }] }] } });
export const deleteTls = (t) => call("DeleteTLSInspectionConfiguration", { TLSInspectionConfigurationArn: t.Arn });

export const listResourcePolicies = async () => {
  const [fw, pol, rg] = await Promise.all([call("ListFirewalls", {}), call("ListFirewallPolicies", {}), call("ListRuleGroups", {})]);
  const all = [...(fw.Firewalls || []).map((x) => ({ Arn: x.FirewallArn, Name: x.FirewallName, Kind: "Firewall" })), ...(pol.FirewallPolicies || []).map((x) => ({ Arn: x.Arn, Name: x.Name, Kind: "Firewall policy" })), ...(rg.RuleGroups || []).map((x) => ({ Arn: x.Arn, Name: x.Name, Kind: "Rule group" }))];
  return Promise.all(all.map(async (r) => { const d = await call("DescribeResourcePolicy", { ResourceArn: r.Arn }).catch(() => null); return { ...r, Id: r.Arn, Policy: d?.Policy || "" }; }));
};
export const putResourcePolicy = (arn, policy) => call("PutResourcePolicy", { ResourceArn: arn, Policy: policy });
export const deleteResourcePolicy = (arn) => call("DeleteResourcePolicy", { ResourceArn: arn });

export const listEndpointAssociations = async () => {
  const items = (await call("ListVpcEndpointAssociations", {})).VpcEndpointAssociations || [];
  return Promise.all(items.map(async (a) => { const d = await call("DescribeVpcEndpointAssociation", { VpcEndpointAssociationArn: a.VpcEndpointAssociationArn }); const x = d.VpcEndpointAssociation; return { Id: x.VpcEndpointAssociationArn, Arn: x.VpcEndpointAssociationArn, Firewall: x.FirewallArn, Vpc: x.VpcId, Subnet: x.SubnetMapping?.SubnetId, Status: d.VpcEndpointAssociationStatus?.Status, Description: x.Description || "" }; }));
};
export const createEndpointAssociation = (v) => call("CreateVpcEndpointAssociation", { FirewallArn: v.firewall, VpcId: v.vpc, SubnetMapping: { SubnetId: v.subnet }, Description: v.description || undefined });
export const deleteEndpointAssociation = (a) => call("DeleteVpcEndpointAssociation", { VpcEndpointAssociationArn: a.Arn });
