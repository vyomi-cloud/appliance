/* A single dashboard — name, labels, raw layout, and the tiles' charts rendered against
 * real stored time series (the same timeSeries.list query Metrics Explorer runs), not a
 * static shell. */
import { useState } from "react";
import { Box, Button, IconButton, Stack, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import DeleteDialog from "../../kit/DeleteDialog.jsx";
import { ErrorAlert, KeyValue, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

function Sparkline({ points }) {
  const vals = points.map((p) => Number(p.v));
  if (!vals.length) return null;
  const min = Math.min(...vals), max = Math.max(...vals);
  const norm = (v) => (max === min ? 20 : 40 - ((v - min) / (max - min)) * 40);
  const d = vals.map((v, i) => `${i === 0 ? "M" : "L"} ${(i / Math.max(vals.length - 1, 1)) * 160} ${norm(v)}`).join(" ");
  return <svg width={160} height={40} aria-hidden><path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} /></svg>;
}

async function loadTile(tile) {
  const tsf = tile.widget?.xyChart?.dataSets?.[0]?.timeSeriesQuery?.timeSeriesFilter;
  const title = tile.widget?.title || "Untitled";
  if (!tsf?.filter) return { title, series: null };
  const end = new Date();
  const series = await api.listTimeSeries({
    filter: tsf.filter, startTime: new Date(end - 3600000).toISOString(), endTime: end.toISOString(),
    aligner: tsf.aggregation?.perSeriesAligner, period: tsf.aggregation?.alignmentPeriod,
  });
  return { title, series };
}

export default function DashboardDetail({ params }) {
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const { data, loading, error } = useAsync(async () => {
    const dash = await api.getDashboard(params.id);
    const layoutKey = ["gridLayout", "mosaicLayout", "rowLayout", "columnLayout"].find((k) => dash[k]);
    const tiles = await Promise.all((dash[layoutKey]?.tiles || []).map(loadTile));
    return { dash, layoutKey, tiles };
  }, [params.id]);
  if (loading) return null;
  if (error || !data?.dash) return <ErrorAlert error={error || { message: "Dashboard not found" }} title="Failed to load dashboard" />;
  const { dash, layoutKey, tiles } = data;
  return (
    <Box>
      <PageHeader title={dash.displayName} back={<IconButton aria-label="Back" href="#/monitoring/dashboards"><ArrowBackIcon /></IconButton>}
        actions={<Button startIcon={<DeleteIcon />} onClick={() => setDel(true)}>Delete</Button>} />
      <Section title="Details">
        <KeyValue items={[
          ["Name", dash.name],
          ["Labels", Object.keys(dash.labels || {}).length ? Object.entries(dash.labels).map(([k, v]) => `${k}=${v}`).join(", ") : "—"],
          ["Layout", layoutKey ? `${layoutKey} (${tiles.length} tile(s))` : "—"],
          ["Etag", dash.etag],
        ]} />
      </Section>
      {tiles.length > 0 && (
        <Section title="Charts">
          <Stack spacing={2}>
            {tiles.map((t, i) => (
              <Stack key={i} spacing={0.5}>
                <Typography variant="subtitle2">{t.title}</Typography>
                {t.series === null ? (
                  <Typography variant="body2" color="text.secondary">This tile has no time series query.</Typography>
                ) : !t.series.length ? (
                  <Typography variant="body2" color="text.secondary">No time series matched this tile's query yet.</Typography>
                ) : (
                  <Sparkline points={(t.series[0].points || []).slice().reverse().map((p) => ({ v: Number(p.value.doubleValue ?? p.value.int64Value ?? 0) }))} />
                )}
              </Stack>
            ))}
          </Stack>
        </Section>
      )}
      <DeleteDialog open={del} onClose={() => setDel(false)} title="Delete dashboard?" confirmText={dash.displayName}
        onConfirm={async () => { await api.deleteDashboard(params.id); notify.success(`Deleted dashboard "${dash.displayName}"`); location.hash = "/monitoring/dashboards"; }}>
        Dashboard <b>{dash.displayName}</b> will be permanently deleted.
      </DeleteDialog>
    </Box>
  );
}
