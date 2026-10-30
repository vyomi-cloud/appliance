/* Declared gaps: Vyomi collects no telemetry for Cloud SQL and has no in-console SQL
 * editor backed by the native Admin API (see core/capabilities/gcp/sql.json: gcp.sql.insights). */
import { Box, Stack, Typography } from "@mui/material";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import InstanceNav from "./InstanceNav.jsx";

function Gap({ title, section }) {
  return function GapPage({ params }) {
    return (
      <Box>
        <InstanceNav name={params.name} active={section} />
        <Stack spacing={1.5}>
          <Typography variant="h2" component="h2" sx={{ fontSize: 20 }}>{title}</Typography>
          <CapabilityContainer id="gcp.sql.insights" title={title} />
        </Stack>
      </Box>
    );
  };
}

export const SystemInsights = Gap({ title: "System insights", section: "system-insights" });
export const QueryInsights = Gap({ title: "Query insights", section: "query-insights" });
export const CloudSqlStudio = Gap({ title: "Cloud SQL Studio", section: "studio" });
