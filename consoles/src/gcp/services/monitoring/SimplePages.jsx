/* Title-only pages for products that sit next to Monitoring in the real console's nav but
 * are out of scope for this build (separate backends Vyomi doesn't model). */
import { Box } from "@mui/material";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const page = (title, id, note) => function Page() {
  return (
    <Box>
      <PageHeader title={title} />
      <CapabilityContainer id={id} title={note} />
    </Box>
  );
};

export const CostExplorer = page("Cost Explorer", "gcp.monitoring.cost-explorer", "Cost data");
export const ApplicationMonitoring = page("Application monitoring", "gcp.monitoring.application-monitoring", "Application monitoring (APM)");
export const TraceExplorer = page("Trace explorer", "gcp.monitoring.trace-explorer", "Distributed tracing");
