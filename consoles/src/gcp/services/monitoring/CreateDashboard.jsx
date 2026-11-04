/* New dashboard — the console's dashboard builder, simplified to the real Dashboards API
 * fields: a name and one starting widget placed on a mosaic layout. The widget's tile
 * carries a real xyChart.dataSets[].timeSeriesQuery.timeSeriesFilter (the same shape the
 * real Dashboards API stores), so the dashboard detail page can query real time series for
 * it instead of rendering a static chart shell. */
import { useState } from "react";
import { Box, Button, FormControl, IconButton, InputLabel, MenuItem, Select, Stack, TextField } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

const WIDGET_TYPES = ["Line chart", "Stacked bar chart", "Heatmap chart", "Table", "Scorecard", "Text", "Alert chart", "Logs panel"];

export default function CreateDashboard() {
  const notify = useNotify();
  const [name, setName] = useState("New Dashboard");
  const [widget, setWidget] = useState("Line chart");
  const [metricType, setMetricType] = useState(api.BUILTIN_METRICS[0][0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (ev) => {
    ev.preventDefault();
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try {
      const resourceType = api.BUILTIN_METRICS.find(([t]) => t === metricType)?.[3] || "global";
      const d = await api.createDashboard({
        displayName: name,
        mosaicLayout: { columns: 12, tiles: [{
          xPos: 0, yPos: 0, width: 6, height: 4,
          widget: { title: widget, xyChart: { dataSets: [{
            plotType: "LINE",
            timeSeriesQuery: { timeSeriesFilter: {
              filter: `metric.type = "${metricType}" AND resource.type = "${resourceType}"`,
              aggregation: { perSeriesAligner: "ALIGN_MEAN", alignmentPeriod: "60s" },
            } },
          }] } },
        }] },
      });
      notify.success(`Created dashboard "${name}"`);
      location.hash = `/monitoring/dashboards/${d.name.split("/").pop()}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 640 }}>
      <PageHeader title="New dashboard" back={<IconButton aria-label="Back" href="#/monitoring/dashboards"><ArrowBackIcon /></IconButton>}
        actions={<Button variant="outlined" disabled>Add widget</Button>} />
      <ErrorAlert error={error} title="Failed to create dashboard" />
      <Section title="Dashboard">
        <Stack spacing={2.5} sx={{ maxWidth: 420 }}>
          <TextField label="Dashboard name" required value={name} onChange={(e) => setName(e.target.value)} inputProps={{ "aria-label": "Dashboard name" }} />
          <FormControl>
            <InputLabel id="widget-type-label">Widget type</InputLabel>
            <Select labelId="widget-type-label" label="Widget type" value={widget} onChange={(e) => setWidget(e.target.value)}>
              {WIDGET_TYPES.map((w) => <MenuItem key={w} value={w}>{w}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl>
            <InputLabel id="metric-label">Metric</InputLabel>
            <Select labelId="metric-label" label="Metric" value={metricType} onChange={(e) => setMetricType(e.target.value)}>
              {api.BUILTIN_METRICS.map(([type, , display]) => <MenuItem key={type} value={type}>{display}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </Section>
      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy || !name.trim()}>{busy ? "Saving…" : "Save"}</Button>
        <Button href="#/monitoring/dashboards">Cancel</Button>
      </Stack>
    </Box>
  );
}
