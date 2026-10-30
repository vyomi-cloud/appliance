/* Observability overview — the landing dashboard. Real tiles pull from the alerting and
 * uptime-check stores; sections that need telemetry Vyomi doesn't generate (SLO compliance,
 * uptime probe results, Ops Agent check-ins) are declared gaps via the capability registry. */
import { Box, Button, List, ListItem, ListItemIcon, ListItemText, Stack, Typography } from "@mui/material";
import DashboardIcon from "@mui/icons-material/esm/DashboardOutlined.js";
import NotificationsActiveIcon from "@mui/icons-material/esm/NotificationsActiveOutlined.js";
import TroubleshootIcon from "@mui/icons-material/esm/TroubleshootOutlined.js";
import SettingsSuggestIcon from "@mui/icons-material/esm/SettingsSuggestOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import { Section, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function Overview() {
  const project = useProject();
  const { data } = useAsync(async () => {
    const [policies, checks] = await Promise.all([api.listPolicies(), api.listUptimeChecks()]);
    return { policies, checks };
  }, [project]);

  return (
    <>
      <PageHeader title="Overview" />
      <Stack spacing={2.5}>
        <Section title="Set up your project's observability">
          <List dense>
            <ListItem disableGutters><ListItemIcon><NotificationsActiveIcon fontSize="small" /></ListItemIcon>
              <ListItemText primary={<a href="#/monitoring/alerting/policies/create">Create an alerting policy</a>} secondary="Get notified when a metric crosses a threshold." /></ListItem>
            <ListItem disableGutters><ListItemIcon><DashboardIcon fontSize="small" /></ListItemIcon>
              <ListItemText primary={<a href="#/monitoring/dashboards">Build a custom dashboard</a>} secondary="Chart the metrics that matter to your project." /></ListItem>
            <ListItem disableGutters><ListItemIcon><TroubleshootIcon fontSize="small" /></ListItemIcon>
              <ListItemText primary={<a href="#/monitoring/uptime/create">Add an uptime check</a>} secondary="Track whether an endpoint responds." /></ListItem>
          </List>
        </Section>

        <Section title="Alerts" actions={<Button size="small" href="#/monitoring/alerting/alerts">View alerts</Button>}>
          <Typography variant="body2" color="text.secondary">
            {data ? `${data.policies.filter((p) => p.enabled).length} of ${data.policies.length} alerting policies enabled.` : "Loading…"}
          </Typography>
        </Section>

        <CapabilityContainer id="gcp.monitoring.slos" title="Services with SLO out of budget" />

        <CapabilityContainer id="gcp.monitoring.uptime-checks.probing" title="Failed uptime checks" />

        <CapabilityContainer id="gcp.monitoring.ops-agent" title="VMs with Ops Agent" />

        <Section title="Get Started with Cloud Observability">
          <Typography variant="body2" color="text.secondary">
            Cloud Observability brings together metrics, alerting, uptime checks and dashboards for your Google Cloud
            and hybrid workloads. Start by exploring a built-in metric or creating your first alerting policy.
          </Typography>
        </Section>

        <Section title="Dashboards and Integrations" actions={<SettingsSuggestIcon fontSize="small" color="disabled" />}>
          <Typography variant="body2" color="text.secondary">
            {data ? "Browse your dashboards or wire up an integration from the catalog." : "Loading…"}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Button size="small" variant="outlined" href="#/monitoring/dashboards">Dashboards</Button>
            <Button size="small" variant="outlined" href="#/monitoring/integrations">Integrations</Button>
          </Stack>
        </Section>
      </Stack>
    </>
  );
}
