/* VPC Flow Logs — Subnets / VLAN attachments / Cloud VPN tunnels tabs (one per resource
 * kind that can carry a flow log config in the real console). Requires the Network
 * Management API; Vyomi models the per-subnet flag only (no VLAN attachments or VPN
 * tunnels), so this reuses the real subnet data for its one real tab. */
import { useState } from "react";
import { Alert, Box, Button, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";
import { VlanAttachments } from "./HybridConnectivity.jsx";

export default function VpcFlowLogs() {
  const project = useProject();
  const [tab, setTab] = useState("subnets");
  const { data: subnets = [], loading } = useAsync(api.listAllSubnets, [project]);
  const [flow, setFlow] = useState({ src: "", dst: "", port: "443", packets: "100" });
  const [flowMsg, setFlowMsg] = useState(null);
  const sendFlow = async () => {
    setFlowMsg(null);
    try {
      const r = await api.sendEvaluatedFlow({ source: { ipAddress: flow.src }, destination: { ipAddress: flow.dst, port: Number(flow.port) },
        protocol: "TCP", packets: Number(flow.packets), bytes: Number(flow.packets) * 512 });
      setFlowMsg({ severity: r.result === "ACCEPT" ? "success" : "warning", text: `${r.result}: ${r.reason || "delivered"}; ${r.logged} flow log record(s) written.` });
      reloadEntries();
    } catch (err) { setFlowMsg({ severity: "error", text: String(err.message || err) }); }
  };
  const { data: entries = [], loading: entriesLoading, reload: reloadEntries } = useAsync(api.listFlowLogEntries, [project]);

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
        <>
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
          <Box sx={{ mt: 2 }}>
            <CapabilityContainer id="gcp.networking.vpc-flow-logs" title="Flow log records"
              description="Records for subnets with flow logs on: real traffic through the appliance's network enforcer (offline), or flows you evaluate here (Nano has no packets).">
              <Stack direction="row" spacing={1} sx={{ mb: 1.5 }} alignItems="center" flexWrap="wrap">
                <TextField size="small" label="Source VM IP" value={flow.src} onChange={(e) => setFlow({ ...flow, src: e.target.value })} />
                <TextField size="small" label="Destination VM IP" value={flow.dst} onChange={(e) => setFlow({ ...flow, dst: e.target.value })} />
                <TextField size="small" label="Port" sx={{ width: 90 }} value={flow.port} onChange={(e) => setFlow({ ...flow, port: e.target.value })} />
                <TextField size="small" label="Packets" sx={{ width: 100 }} value={flow.packets} onChange={(e) => setFlow({ ...flow, packets: e.target.value })} />
                <Button variant="outlined" size="small" disabled={!flow.src || !flow.dst} onClick={sendFlow}>Evaluate and log flow</Button>
              </Stack>
              {flowMsg && <Alert severity={flowMsg.severity} sx={{ mb: 1.5 }}>{flowMsg.text}</Alert>}
              <ResourceTable
                resourceName="log entries"
                items={entries}
                rowKey={(e) => e.insertId}
                loading={entriesLoading}
                onRetry={reloadEntries}
                filterPlaceholder="Filter"
                empty={<Typography variant="body2" color="text.secondary">No flow log entries yet — enable flow logs on a subnet and evaluate a flow above (offline: they also appear once real traffic crosses the network enforcer).</Typography>}
                columns={[
                  { id: "time", header: "Timestamp", cell: (e) => e.timestamp },
                  { id: "src", header: "Source", cell: (e) => `${e.jsonPayload?.connection?.src_ip}:${e.jsonPayload?.connection?.src_port}` },
                  { id: "dst", header: "Destination", cell: (e) => `${e.jsonPayload?.connection?.dest_ip}:${e.jsonPayload?.connection?.dest_port}` },
                  { id: "bytes", header: "Bytes", cell: (e) => e.jsonPayload?.bytes_sent },
                ]}
              />
            </CapabilityContainer>
          </Box>
        </>
      )}
      {tab === "vlan" && <VlanAttachments title="VLAN attachments" />}
      {tab === "vpn" && <CapabilityContainer id="gcp.networking.hybrid-connectivity" title="Cloud VPN tunnels" />}
    </>
  );
}
