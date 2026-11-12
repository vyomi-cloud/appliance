/* Monitor's top-level "Diagnostic settings" page is a resource picker in the real portal (a
 * diagnostic setting is a resource-scoped extension — Microsoft.Insights/diagnosticSettings —
 * so there is no subscription-wide LIST api; the browse grid instead lists every resource and
 * a "Diagnostics status" column for whether it has one configured). Selecting a row opens that
 * resource's own Diagnostic settings blade (DiagnosticSettingsResource.jsx). */
import { useEffect, useState } from "react";
import { Button } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { listAllResources, listDiagnosticSettings } from "./api.js";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

export default function DiagnosticSettings() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const load = () => {
    setError(null);
    listAllResources()
      .then(async (resources) => {
        const counts = await Promise.all(resources.map((r) => listDiagnosticSettings(r.id).then((s) => s.length).catch(() => 0)));
        setItems(resources.map((r, i) => ({ ...r, diagCount: counts[i] })));
      })
      .catch(setError);
  };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "type", label: "Resource type", value: (r) => r.typeLabel },
    { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
    { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
    { key: "status", label: "Diagnostics status", render: (r) => r.diagCount ? `Enabled (${r.diagCount})` : "Not configured" },
    { key: "configure", label: "", render: (r) => (
      <Button size="small" as="a"
        href={`#/monitor/diagnosticsettingsresource?id=${encodeURIComponent(r.id)}&name=${encodeURIComponent(r.name)}&type=${encodeURIComponent(r.typeLabel)}`}>
        Configure
      </Button>
    ) },
  ];

  return (
    <MonitorShell active="diagnosticsettings">
      <CapabilityContainer id="azure.monitor.diagnostic_settings" title="Diagnostic settings">
        {items === null ? <Loading /> : (
          <BrowseGrid resourceName="resource" items={items} columns={columns} loading={false} error={error}
            onRefresh={load} csvName="diagnostic-settings.csv" />
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
