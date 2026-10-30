/* Alerts — open/closed incidents. Honest gap: see gcp.monitoring.incidents. A real alert
 * policy fires only when a rule-evaluation engine watches time series continuously; Vyomi
 * has none, so this list can never have real contents — rendering empty column headers
 * here would be exactly the disabled-skeleton pattern the console build forbids. */
import { Box, Button } from "@mui/material";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

export default function Alerts() {
  return (
    <Box>
      <PageHeader title="Alerts" actions={<Button href="#/monitoring/alerting/policies/create">Create policy</Button>} />
      <CapabilityContainer id="gcp.monitoring.incidents" title="Open and closed alerts" />
    </Box>
  );
}
