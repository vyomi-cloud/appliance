/* Route 53 Resolver DNS Firewall (JSON 1.1, Route53Resolver) — rule groups, domain lists, VPC associations. */
import { awsJson } from "../../../common/wire.js";

const call = (op, body) => awsJson("route53resolver", `Route53Resolver.${op}`, body, { version: "1.1" });

export const listDomainLists = async () => {
  const ls = (await call("ListFirewallDomainLists", {})).FirewallDomainLists || [];
  return Promise.all(ls.map(async (l) => {
    const d = (await call("GetFirewallDomainList", { FirewallDomainListId: l.Id })).FirewallDomainList;
    const doms = (await call("ListFirewallDomains", { FirewallDomainListId: l.Id })).Domains || [];
    return { Id: d.Id, Name: d.Name, Count: d.DomainCount, Status: d.Status, Domains: doms, Modified: d.ModificationTime };
  }));
};
export const createDomainList = async (v) => {
  const r = await call("CreateFirewallDomainList", { Name: v.name });
  const doms = (v.domains || "").split(/[\s,]+/).filter(Boolean);
  if (doms.length) await call("UpdateFirewallDomains", { FirewallDomainListId: r.FirewallDomainList.Id, Operation: "ADD", Domains: doms }).catch(async (e) => { await call("DeleteFirewallDomainList", { FirewallDomainListId: r.FirewallDomainList.Id }); throw e; });
  return r;
};
export const updateDomains = (l, op, domains) => call("UpdateFirewallDomains", { FirewallDomainListId: l.Id, Operation: op, Domains: domains.split(/[\s,]+/).filter(Boolean) });
export const deleteDomainList = (l) => call("DeleteFirewallDomainList", { FirewallDomainListId: l.Id });

export const listRuleGroups = async () => {
  const gs = (await call("ListFirewallRuleGroups", {})).FirewallRuleGroups || [];
  const assocs = (await call("ListFirewallRuleGroupAssociations", {})).FirewallRuleGroupAssociations || [];
  return Promise.all(gs.map(async (g) => {
    const d = (await call("GetFirewallRuleGroup", { FirewallRuleGroupId: g.Id })).FirewallRuleGroup;
    const rules = (await call("ListFirewallRules", { FirewallRuleGroupId: g.Id })).FirewallRules || [];
    return { Id: d.Id, Name: d.Name, Status: d.Status, RuleCount: d.RuleCount, Rules: rules, Assocs: assocs.filter((a) => a.FirewallRuleGroupId === g.Id), Owner: d.OwnerId, Share: d.ShareStatus };
  }));
};
export const createRuleGroup = (v) => call("CreateFirewallRuleGroup", { Name: v.name });
export const deleteRuleGroup = (g) => call("DeleteFirewallRuleGroup", { FirewallRuleGroupId: g.Id });
export const createRule = (g, v) => call("CreateFirewallRule", { FirewallRuleGroupId: g.Id, FirewallDomainListId: v.list, Priority: Number(v.priority), Action: v.action, Name: v.name,
  BlockResponse: v.action === "BLOCK" ? v.blockResponse || "NXDOMAIN" : undefined, BlockOverrideDomain: v.blockResponse === "OVERRIDE" ? v.overrideDomain : undefined, BlockOverrideDnsType: v.blockResponse === "OVERRIDE" ? "CNAME" : undefined });
export const deleteRule = (g, r) => call("DeleteFirewallRule", { FirewallRuleGroupId: g.Id, FirewallDomainListId: r.FirewallDomainListId });
export const associate = (g, v) => call("AssociateFirewallRuleGroup", { FirewallRuleGroupId: g.Id, VpcId: v.vpc, Priority: Number(v.priority), Name: v.name });
export const disassociate = (a) => call("DisassociateFirewallRuleGroup", { FirewallRuleGroupAssociationId: a.Id });
