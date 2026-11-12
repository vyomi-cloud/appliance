/* Insights — index recommendations and unused-index detection, both derived from real
 * :runQuery/findNearest activity recorded by the core as it happens (never synthetic). */
import { Box, Button, Grid, Paper, Stack, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
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

function recommendedFields(rec) {
  return rec.kinds.map((k) => {
    if (k.startsWith("VECTOR:")) return { fieldPath: rec.fieldPath, vectorConfig: { dimension: Number(k.split(":")[1]), flat: {} } };
    if (k === "CONTAINS") return { fieldPath: rec.fieldPath, arrayConfig: "CONTAINS" };
    return { fieldPath: rec.fieldPath, order: k === "DESCENDING" ? "DESCENDING" : "ASCENDING" };
  });
}

export default function Insights({ params }) {
  const db = params.name;
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.getInsights(db), [db]);

  const createRecommended = async (rec) => {
    try {
      await api.createIndex(db, rec.collectionGroup, { queryScope: "COLLECTION", fields: recommendedFields(rec) });
      notify.success(`Created index for "${rec.collectionGroup}"`);
      reload();
    } catch (e) { notify.error(e); }
  };

  return (
    <>
      <PageHeader title="Insights" />
      <ErrorAlert error={error} title="Failed to load insights" />
      <CapabilityContainer id="gcp.firestore.insights" title="Insights">
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} sm={6}><Stat label="Queries run" value={loading ? "…" : data?.totalQueries ?? 0} /></Grid>
          <Grid item xs={12} sm={6}><Stat label="Queries that failed on a missing index" value={loading ? "…" : data?.queriesMissingIndex ?? 0} /></Grid>
        </Grid>

        <Typography variant="subtitle1" sx={{ mb: 1 }}>Index recommendations</Typography>
        <Stack spacing={1.5} sx={{ mb: 3 }}>
          {(data?.indexRecommendations || []).map((r) => (
            <Paper key={`${r.collectionGroup}:${r.fieldPath}:${r.kinds.join(",")}`} variant="outlined"
              sx={{ p: 1.5, borderRadius: 2, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>{r.collectionGroup} — {r.fieldPath}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {r.occurrences} quer{r.occurrences === 1 ? "y" : "ies"} failed without an index on this field ({r.kinds.join(", ")})
                </Typography>
              </Box>
              <Button size="small" variant="contained" onClick={() => createRecommended(r)}>Create index</Button>
            </Paper>
          ))}
          {!loading && !(data?.indexRecommendations || []).length && (
            <Typography variant="body2" color="text.secondary">No missing-index queries detected yet.</Typography>
          )}
        </Stack>

        <Typography variant="subtitle1" sx={{ mb: 1 }}>Unused indexes</Typography>
        <Stack spacing={1.5}>
          {(data?.unusedIndexes || []).map((u) => (
            <Paper key={u.indexId} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>{u.collectionGroup} ({u.fields.join(", ")})</Typography>
              <Typography variant="caption" color="text.secondary">Index ID {u.indexId} has not matched any query yet.</Typography>
            </Paper>
          ))}
          {!loading && !(data?.unusedIndexes || []).length && (
            <Typography variant="body2" color="text.secondary">Every composite or vector index has matched at least one query.</Typography>
          )}
        </Stack>
      </CapabilityContainer>
    </>
  );
}
