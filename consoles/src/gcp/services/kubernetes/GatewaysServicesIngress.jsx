/* Gateways, Services & Ingress — Kubernetes-native networking objects that live in a
 * cluster's API server. Vyomi runs no Kubernetes API server behind a cluster's endpoint,
 * so every tab here is an honest gap. */
import { useState } from "react";
import { Box, Tab, Tabs } from "@mui/material";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const TABS = [["gateways", "Gateways"], ["services", "Services"], ["ingress", "Ingress"]];
const COLUMNS = "Name, Status, Type, Endpoints, Pods, Namespace, Cluster.";

export default function GatewaysServicesIngress() {
  const [tab, setTab] = useState("gateways");
  return (
    <>
      <PageHeader title="Gateways, Services & Ingress" />
      <Tabs value={tab} onChange={(_, t) => setTab(t)} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }} aria-label="Discovery tabs">
        {TABS.map(([id, label]) => <Tab key={id} value={id} label={label} />)}
      </Tabs>
      <Box>
        {TABS.map(([id, label]) => tab === id && (
          <CapabilityContainer key={id} id="gcp.kubernetes.discovery" title={label} description={`Would list ${COLUMNS}`} />
        ))}
      </Box>
    </>
  );
}
