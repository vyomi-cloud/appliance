/* Usage — real metered running totals (reads/writes/deletes/document count/storage size)
 * from the native `:usage` endpoint. No time-series: see the capability badge. */
import { Grid, Paper, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

function Stat({ label, value }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="h2" component="div">{value}</Typography>
    </Paper>
  );
}

export default function Usage({ params }) {
  const db = params.name;
  const { data, loading, error } = useAsync(() => api.getUsage(db), [db]);
  const show = (v) => (loading || v === undefined ? "…" : v);

  return (
    <>
      <PageHeader title="Usage" />
      <ErrorAlert error={error} title="Failed to load usage" />
      <CapabilityContainer id="gcp.firestore.usage" title="Usage">
        <Grid container spacing={2}>
          <Grid item xs={12} sm={6} md={3}><Stat label="Document reads" value={show(data?.reads)} /></Grid>
          <Grid item xs={12} sm={6} md={3}><Stat label="Document writes" value={show(data?.writes)} /></Grid>
          <Grid item xs={12} sm={6} md={3}><Stat label="Document deletes" value={show(data?.deletes)} /></Grid>
          <Grid item xs={12} sm={6} md={3}><Stat label="Documents stored" value={show(data?.documentCount)} /></Grid>
        </Grid>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          Running totals since this database was created (~{show(data?.storageBytes)} bytes of document data currently stored). Vyomi does not retain a history, so these are current totals, not an over-time chart.
        </Typography>
      </CapabilityContainer>
    </>
  );
}
