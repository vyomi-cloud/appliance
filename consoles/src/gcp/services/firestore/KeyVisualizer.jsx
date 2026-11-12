/* Key Visualizer — a heatmap of real per-document access counts the core records on
 * every read/write/delete/query match, bucketed by collection and a hash of the document
 * key. No time dimension, and the buckets are a simple hash rather than production's
 * actual tablet key-range splits — see the capability badge. */
import { Box, Stack, Tooltip, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

function heat(n, max) {
  if (!max) return "rgba(66,133,244,0.06)";
  const t = Math.min(1, n / max);
  return `rgba(66,133,244,${(0.08 + t * 0.82).toFixed(2)})`;
}

export default function KeyVisualizer({ params }) {
  const db = params.name;
  const { data, loading, error } = useAsync(() => api.getKeyVisualizer(db), [db]);
  const rows = data?.rows || [];
  const max = rows.reduce((m, r) => Math.max(m, ...r.buckets), 0);

  return (
    <>
      <PageHeader title="Key Visualizer" />
      <ErrorAlert error={error} title="Failed to load Key Visualizer" />
      <CapabilityContainer id="gcp.firestore.key-visualizer" title="Key Visualizer">
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          A heatmap of real document access recorded by this database, bucketed by collection
          and a hash of the document key. Darker cells had more reads/writes.
        </Typography>
        {!loading && !rows.length && <Typography variant="body2" color="text.secondary">No document access recorded yet.</Typography>}
        {!!rows.length && (
          <Box sx={{ overflowX: "auto", mb: 3 }}>
            <Stack spacing={0.5}>
              {rows.map((r) => (
                <Stack key={r.collection} direction="row" spacing={0.5} alignItems="center">
                  <Typography variant="caption" sx={{ width: 240, flexShrink: 0, fontFamily: "monospace" }}>{r.collection}</Typography>
                  {r.buckets.map((n, i) => (
                    <Tooltip key={i} title={`${n} access${n === 1 ? "" : "es"}`}>
                      <Box sx={{ width: 28, height: 20, bgcolor: heat(n, max), border: 1, borderColor: "divider" }} />
                    </Tooltip>
                  ))}
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>{r.total}</Typography>
                </Stack>
              ))}
            </Stack>
          </Box>
        )}
        <Typography variant="subtitle2" sx={{ mb: 1 }}>Hottest keys</Typography>
        <Stack spacing={0.5}>
          {(data?.hottestKeys || []).map((k) => (
            <Stack key={k.key} direction="row" justifyContent="space-between" sx={{ maxWidth: 560 }}>
              <Typography variant="body2" sx={{ fontFamily: "monospace" }}>{k.key}</Typography>
              <Typography variant="body2" color="text.secondary">{k.count}</Typography>
            </Stack>
          ))}
          {!loading && !(data?.hottestKeys || []).length && <Typography variant="body2" color="text.secondary">No document access recorded yet.</Typography>}
        </Stack>
      </CapabilityContainer>
    </>
  );
}
