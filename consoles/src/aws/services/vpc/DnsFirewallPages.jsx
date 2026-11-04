/* Route 53 Resolver DNS Firewall pages over the native JSON wire (core/dnsfw_core.py). */
import Box from "@cloudscape-design/components/box";
import Table from "@cloudscape-design/components/table";
import { ResourceList } from "./Crud.jsx";
import * as df from "./apiDnsFw.js";
import * as x from "./apiExtras.js";

const col = (id, header, cell, extra = {}) => ({ id, header, cell, ...extra });
const Sub = ({ title, items, columns, empty }) => <Table variant="container" header={<Box variant="h3">{title}</Box>} items={items} columnDefinitions={columns} empty={<Box textAlign="center">{empty || "None"}</Box>} />;
const listOpts = async () => (await df.listDomainLists()).map((l) => ({ value: l.Id, label: `${l.Name} (${l.Id})` }));
const vpcOpts = async () => (await x.describeVpcs()).map((v) => ({ value: v.VpcId, label: v.VpcId }));

export const DnsFirewallRuleGroups = () => (
  <ResourceList title="DNS Firewall rule groups" capId="aws.vpc.dns-firewall" trackBy="Id" load={df.listRuleGroups}
    columns={[col("n", "Name", (r) => r.Name, { isRowHeader: true }), col("id", "Rule group ID", (r) => r.Id), col("st", "Status", (r) => r.Status), col("c", "Rules", (r) => r.RuleCount), col("a", "VPC associations", (r) => r.Assocs.length), col("s", "Sharing", (r) => r.Share)]}
    create={{ label: "Add rule group", fields: [{ key: "name", label: "Name", required: true }], submit: (v) => df.createRuleGroup(v) }}
    actions={[
      { text: "Add rule", needs: "one", fields: [{ key: "name", label: "Rule name", required: true }, { key: "list", label: "Domain list", type: "select", required: true, options: listOpts }, { key: "priority", label: "Priority (1-10000)", required: true },
        { key: "action", label: "Action", type: "select", required: true, default: "BLOCK", options: ["ALLOW", "ALERT", "BLOCK"] },
        { key: "blockResponse", label: "Block response", type: "select", default: "NXDOMAIN", options: ["NODATA", "NXDOMAIN", "OVERRIDE"], showIf: (v) => v.action === "BLOCK" },
        { key: "overrideDomain", label: "Override CNAME domain", showIf: (v) => v.action === "BLOCK" && v.blockResponse === "OVERRIDE" }], submit: ([g], v) => df.createRule(g, v) },
      { text: "Associate VPC", needs: "one", fields: [{ key: "name", label: "Association name", required: true }, { key: "vpc", label: "VPC", type: "select", required: true, options: vpcOpts }, { key: "priority", label: "Priority (100-9900)", required: true, default: "101" }], submit: ([g], v) => df.associate(g, v) },
    ]}
    del={{ label: "Delete", type: "rule group", run: (r) => df.deleteRuleGroup(r) }}
    detail={(g) => [
      { id: "rules", label: "Rules", content: <Sub title="Rules" empty="No rules" items={g.Rules} columns={[col("p", "Priority", (r) => r.Priority), col("n", "Name", (r) => r.Name), col("l", "Domain list", (r) => r.FirewallDomainListId), col("a", "Action", (r) => r.Action), col("b", "Block response", (r) => r.BlockResponse || "-")]} /> },
      { id: "vpcs", label: "Associated VPCs", content: <Sub title="Associated VPCs" empty="Not associated with any VPC" items={g.Assocs} columns={[col("v", "VPC", (r) => r.VpcId), col("n", "Association", (r) => r.Name), col("p", "Priority", (r) => r.Priority), col("s", "Status", (r) => r.Status)]} /> },
    ]} />
);

export const DnsFirewallDomainLists = () => (
  <ResourceList title="DNS Firewall domain lists" capId="aws.vpc.dns-firewall" trackBy="Id" load={df.listDomainLists}
    columns={[col("n", "Name", (r) => r.Name, { isRowHeader: true }), col("id", "Domain list ID", (r) => r.Id), col("c", "Domains", (r) => r.Count), col("st", "Status", (r) => r.Status), col("m", "Last modified", (r) => r.Modified)]}
    create={{ label: "Add domain list", fields: [{ key: "name", label: "Name", required: true }, { key: "domains", label: "Domains (comma or space separated, wildcard as *.example.com)", type: "textarea", rows: 4 }], submit: (v) => df.createDomainList(v) }}
    actions={[{ text: "Add domains", needs: "one", fields: [{ key: "domains", label: "Domains", type: "textarea", required: true, rows: 4 }], submit: ([l], v) => df.updateDomains(l, "ADD", v.domains) },
      { text: "Remove domains", needs: "one", fields: [{ key: "domains", label: "Domains", type: "textarea", required: true, rows: 4 }], submit: ([l], v) => df.updateDomains(l, "REMOVE", v.domains) }]}
    del={{ label: "Delete", type: "domain list", run: (r) => df.deleteDomainList(r) }}
    detail={(l) => [{ id: "domains", label: "Domains", content: <Sub title="Domains" empty="No domains" items={l.Domains.map((d) => ({ d }))} columns={[col("d", "Domain", (r) => r.d)]} /> }]} />
);
