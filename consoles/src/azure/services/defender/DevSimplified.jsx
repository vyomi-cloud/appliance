/* Defender for Cloud pages with no Microsoft detection pipeline behind them: Workload protections, Data security and
 * Firewall Manager. Each is a Dev Simplified view COMPUTED on every load from the live ARM state
 * (core/azure_devsimplified_core.py) - configuration checks only, never scanning or traffic analysis. */
import { Badge, Link, ToolbarButton } from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, InfoBar, Loading } from "../../kit/common.jsx";
import DefenderShell, { LABEL } from "./DefenderShell.jsx";
import * as api from "./api.js";
import { SeverityBadge } from "./Pages.jsx";

const NOTE = "Dev Simplified: these rows are configuration checks computed from your simulated resources each time the page loads. No sensitive-data scanning, traffic analysis or Microsoft threat intelligence runs behind them.";

function Frame({ id, kind, children }) {
  const d = useAsync(() => api.getInsight(kind), [kind]);
  return (
    <DefenderShell active={id}>
      <div className="vy-panel-title">{LABEL[id]}</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Commands"><ToolbarButton icon={<ArrowClockwise20Regular />} onClick={d.reload}>Refresh</ToolbarButton></div>
      <CapabilityContainer id="azure.defender.other" title={LABEL[id]}>
        <ErrorBar error={d.error} />
        {d.loading && !d.data ? <Loading /> : d.data && children(d.data)}
        <InfoBar>{NOTE}</InfoBar>
      </CapabilityContainer>
    </DefenderShell>
  );
}

const Workload = () => (
  <Frame id="workloadprotections" kind="workloadProtections">{(d) => (
    <BrowseGrid resourceName="Defender plan" rowKey={(r) => r.plan} items={d.plans} csvName="workload-protections.csv"
      columns={[
        { key: "plan", label: "Defender plan" }, { key: "resourceType", label: "Resource type" },
        { key: "resources", label: "Resources in subscription" },
        { key: "names", label: "Resources", value: (r) => r.names.join(", ") || "--" },
        { key: "cfg", label: "Plan settings", render: () => <Link href="#/defender/environment">Environment settings</Link>, value: () => "Environment settings" },
      ]} />
  )}</Frame>
);

const DataSecurity = () => (
  <Frame id="datasecurity" kind="dataSecurity">{(d) => (
    <BrowseGrid resourceName="finding" rowKey={(r) => `${r.resourceId}|${r.finding}`} items={d.findings} csvName="data-security-findings.csv"
      columns={[
        { key: "severity", label: "Severity", render: (r) => <SeverityBadge s={r.severity} />, value: (r) => r.severity },
        { key: "finding", label: "Finding" },
        { key: "resourceName", label: "Resource" },
        { key: "resourceType", label: "Resource type" },
        { key: "recommendation", label: "Recommended action" },
      ]} />
  )}</Frame>
);

const FirewallManager = () => (
  <Frame id="firewallmanager" kind="firewallManager">{(d) => (
    <>
      <h3>Azure Firewalls</h3>
      <BrowseGrid resourceName="firewall" rowKey={(r) => r.id} items={d.firewalls} csvName="firewalls.csv"
        columns={[{ key: "name", label: "Name" }, { key: "location", label: "Location" }, { key: "tier", label: "Tier" },
          { key: "threatIntelMode", label: "Threat intelligence mode" }, { key: "policy", label: "Policy", value: (r) => (r.policy || "").split("/").pop() || "--" }]} />
      <h3>Network security groups</h3>
      <BrowseGrid resourceName="network security group" rowKey={(r) => r.id} items={d.networkSecurityGroups} csvName="nsgs.csv"
        columns={[{ key: "name", label: "Name" }, { key: "location", label: "Location" }, { key: "rules", label: "Rules" },
          { key: "open", label: "Inbound rules open to any source", render: (r) => (r.openInboundRules.length ? <Badge color="warning" appearance="tint">{r.openInboundRules.join(", ")}</Badge> : "None"), value: (r) => r.openInboundRules.join(", ") }]} />
    </>
  )}</Frame>
);

export function DefenderPanel({ params }) {
  const id = params.panel;
  if (id === "workloadprotections") return <Workload />;
  if (id === "datasecurity") return <DataSecurity />;
  if (id === "firewallmanager") return <FirewallManager />;
  return (
    <DefenderShell active={id}>
      <div className="vy-panel-title">{LABEL[id] || id}</div>
      <CapabilityContainer id="azure.defender.other" title={LABEL[id] || id} />
    </DefenderShell>
  );
}
