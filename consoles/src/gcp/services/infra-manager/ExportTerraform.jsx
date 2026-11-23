/* Vyomi extra: export the whole project as Terraform (google provider), split by service, downloadable as a zip, or turned into a deployment. */
import { useState } from "react";
import { Box, Button, Chip, IconButton, Stack, Tab, Tabs, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import DownloadIcon from "@mui/icons-material/esm/FileDownloadOutlined.js";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import { handoff } from "./api.js";
import { exportProject, zipOf } from "./tfgcp.js";

export default function ExportTerraform() {
  const project = useProject();
  const r = useAsync(() => exportProject(project), [project]);
  const [file, setFile] = useState("");
  const save = (blob, name) => { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); };
  const names = r.data ? Object.keys(r.data.files) : [];
  const cur = file && names.includes(file) ? file : names.find((n) => n === "network.tf") || names[0];
  return (
    <>
      <PageHeader title="Export project as Terraform" back={<IconButton aria-label="Back" href="#/infra-manager"><ArrowBackIcon /></IconButton>}
        actions={r.data && <>
          <Button startIcon={<DownloadIcon />} data-testid="download-zip" onClick={async () => save(await zipOf(r.data.files), `${project}-terraform.zip`)}>Download .zip</Button>
          <Button variant="contained" data-testid="make-deployment" onClick={() => { handoff.set(r.data.files); location.hash = "#/infra-manager/deployments/new"; }}>Create deployment from this export</Button>
        </>} />
      {r.error && <ErrorAlert error={r.error} title="Export failed" />}
      {r.loading && <Typography color="text.secondary">Reading the project's resources through the Google APIs…</Typography>}
      {r.data && (
        <>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }} data-testid="tf-kinds">
            <Typography sx={{ mr: 1 }} data-testid="tf-count">{r.data.count} resource{r.data.count === 1 ? "" : "s"} · {names.length} files</Typography>
            {Object.keys(r.data.kinds).sort().map((k) => <Chip key={k} size="small" variant="outlined" label={`${k} × ${r.data.kinds[k]}`} />)}
          </Stack>
          <Tabs value={cur} onChange={(_, v) => setFile(v)} variant="scrollable" sx={{ borderBottom: 1, borderColor: "divider" }} aria-label="Terraform files">
            {names.map((n) => <Tab key={n} value={n} label={n} />)}
          </Tabs>
          <Section title={cur}><Box component="pre" data-testid="tf-text" sx={{ m: 0, p: 2, maxHeight: 520, overflow: "auto", fontSize: 12 }}>{r.data.files[cur]}</Box></Section>
        </>
      )}
    </>
  );
}
