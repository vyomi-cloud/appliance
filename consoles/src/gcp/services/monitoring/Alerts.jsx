/* Alerts — open/closed incidents. Honest gap: see gcp.monitoring.incidents. A real alert
 * policy fires only when a rule-evaluation engine watches time series continuously; Vyomi
 * has none, so this list can never have real contents — rendering empty column headers
 * here would be exactly the disabled-skeleton pattern the console build forbids. The
 * policies an alert would be filed under are real, so they're surfaced below as the
 * page's live, native-wire-backed content. */
import { Box, Button, Chip, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Alerts() {
  const project = useProject();
  const { data: policies = [] } = useAsync(() => api.listPolicies(), [project]);

  return (
    <Box>
      <PageHeader title="Alerts" actions={<Button href="#/monitoring/alerting/policies/create">Create policy</Button>} />
      <Stack spacing={2.5}>
        <CapabilityContainer id="gcp.monitoring.incidents" title="Open and closed alerts" />
        <Section title="Alert policies">
          {policies.length ? (
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
              {policies.map((p) => <Chip key={p.name} label={p.displayName} />)}
            </Stack>
          ) : (
            <Typography variant="body2" color="text.secondary">No alert policies yet — alerts will be filed under the policies you create.</Typography>
          )}
        </Section>
      </Stack>
    </Box>
  );
}
