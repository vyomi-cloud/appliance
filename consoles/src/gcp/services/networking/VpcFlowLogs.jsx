/* VPC Flow Logs — Subnets / VLAN attachments / Cloud VPN tunnels tabs (one per resource
 * kind that can carry a flow log config in the real console). Requires the Network
 * Management API; Vyomi models the per-subnet flag only (no VLAN attachments or VPN
 * tunnels), so this reuses the real subnet data for its one real tab. */
import { useState } from "react";
import { Tab, Tabs, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function VpcFlowLogs() {
  const project = useProject();
  const [tab, setTab] = useState("subnets");
  const { data: subnets = [], loading } = useAsync(api.listAllSubnets, [project]);

  return (
    <>
      <PageHeader title="VPC flow logs" />
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Requires the Network Management API.</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="subnets" label="Subnets" />
        <Tab value="vlan" label="VLAN attachments" />
        <Tab value="vpn" label="Cloud VPN tunnels" />
      </Tabs>

      {tab === "subnets" && (
        <CapabilityContainer id="gcp.networking.subnet.crud" title="Subnets" description="Flow log state per subnet.">
          <ResourceTable
            resourceName="subnets"
            items={subnets}
            loading={loading}
            filterPlaceholder="Filter"
            columns={[
              { id: "name", header: "Name", cell: (s) => s.name },
              { id: "network", header: "Network", cell: (s) => api.nameOf(s.network) },
              { id: "region", header: "Region", cell: (s) => api.nameOf(s.region) },
              { id: "flowlogs", header: "Flow logs", cell: (s) => (s.logConfig?.enable ? "On" : "Off") },
            ]}
          />
        </CapabilityContainer>
      )}
      {tab === "vlan" && <CapabilityContainer id="gcp.networking.hybrid-connectivity" title="VLAN attachments" />}
      {tab === "vpn" && <CapabilityContainer id="gcp.networking.hybrid-connectivity" title="Cloud VPN tunnels" />}
    </>
  );
}
