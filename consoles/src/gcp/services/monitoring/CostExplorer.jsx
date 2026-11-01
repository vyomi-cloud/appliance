/* Cost Explorer — real GCP has no public REST method for a cost report (it reads a Cloud
 * Billing BigQuery export this appliance doesn't generate), but it DOES expose project spend
 * as a Cloud Monitoring metric (billing.googleapis.com/billing/total_cost, the same series a
 * Billing Budget alert evaluates) — that's the native-wire path used here, computed for real
 * from this project's actual resource inventory (see gcp.monitoring.cost-explorer). */
import { Box, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function CostExplorer() {
  const project = useProject();
  const { data } = useAsync(async () => {
    const series = await api.listTimeSeries({
      filter: 'metric.type = "billing.googleapis.com/billing/total_cost"', endTime: new Date().toISOString(),
    });
    return series
      .map((s) => ({ service: s.metric?.labels?.service || "Other", cost: s.points?.[0]?.value?.doubleValue || 0 }))
      .filter((r) => r.service !== "none")
      .sort((a, b) => b.cost - a.cost);
  }, [project]);
  const rows = data || [];
  const total = rows.reduce((sum, r) => sum + r.cost, 0);

  return (
    <Box>
      <PageHeader title="Cost Explorer" />
      <CapabilityContainer id="gcp.monitoring.cost-explorer" title="Month-to-date cost by service">
        <Typography variant="h4" sx={{ mb: 2 }}>${total.toFixed(2)}</Typography>
        {!data ? <Typography variant="body2" color="text.secondary">Loading…</Typography>
          : rows.length === 0 ? <Typography variant="body2" color="text.secondary">No billable resources in this project yet.</Typography>
          : (
            <Table size="small">
              <TableHead><TableRow><TableCell>Service</TableCell><TableCell align="right">Cost</TableCell></TableRow></TableHead>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.service}><TableCell>{r.service}</TableCell><TableCell align="right">${r.cost.toFixed(2)}</TableCell></TableRow>
                ))}
              </TableBody>
            </Table>
          )}
      </CapabilityContainer>
    </Box>
  );
}
