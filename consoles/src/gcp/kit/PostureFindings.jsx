/* Rule-based security posture findings over real stored resources (core/gcp_posture_core). */
import { Chip, Stack, Typography } from "@mui/material";
import { restJson } from "../../common/wire.js";
import { useAsync } from "../../common/useAsync.js";
import ResourceTable from "./ResourceTable.jsx";
import { useProject } from "../project.js";

const COLOR = { CRITICAL: "error", HIGH: "error", MEDIUM: "warning", LOW: "default" };

export default function PostureFindings({ kind }) {
  const project = useProject();
  const { data, loading, error, reload } = useAsync(() => restJson("GET", `/v1/projects/${encodeURIComponent(project)}/securityPosture/${kind}`), [project, kind]);
  const by = data?.summary?.bySeverity || {};
  return (
    <>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }} data-testid="posture-summary">
        {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => <Chip key={s} color={COLOR[s]} variant={by[s] ? "filled" : "outlined"} label={`${s}: ${by[s] || 0}`} />)}
      </Stack>
      <ResourceTable
        resourceName="findings"
        items={data?.findings || []}
        loading={loading}
        error={error}
        onRetry={reload}
        rowKey={(f) => f.name}
        columns={[
          { id: "sev", header: "Severity", cell: (f) => <Chip size="small" color={COLOR[f.severity]} label={f.severity} /> },
          { id: "cat", header: "Category", cell: (f) => f.category },
          { id: "res", header: "Resource", cell: (f) => f.resourceName.replace(/^\/\/\w+\.googleapis\.com\//, "") },
          { id: "desc", header: "Finding", cell: (f) => f.description },
          { id: "rec", header: "Recommendation", cell: (f) => f.recommendation },
        ]}
        empty={<Typography variant="body2" color="text.secondary">No findings: no misconfigured resources detected in this project.</Typography>}
      />
    </>
  );
}
