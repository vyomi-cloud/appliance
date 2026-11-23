/* Infrastructure Manager (Google's Terraform service): Deployments. Vyomi adds "Export project as Terraform" and a layered view on top of it. */
import { useState } from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import DownloadIcon from "@mui/icons-material/esm/FileDownloadOutlined.js";
import { PageHeader } from "../../kit/common.jsx";
import { useProject } from "../../project.js";
import { exportProject } from "./tfgcp.js";

export default function Deployments() {
  const project = useProject();
  const [res, setRes] = useState(null), [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setRes(await exportProject(project)); } finally { setBusy(false); } };
  const download = () => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([res.files["main.tf"]], { type: "text/plain" })); a.download = `${project}-main.tf`; a.click(); };
  return (
    <Box sx={{ p: 2 }}>
      <PageHeader title="Infrastructure Manager" actions={<Button variant="contained" onClick={run} disabled={busy}>{busy ? "Exporting…" : "Export project as Terraform"}</Button>} />
      <Typography variant="h6" sx={{ mt: 2 }}>Deployments</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>No deployments. Vyomi can export the resources in this project as a Terraform configuration (google provider) you can deploy with Infrastructure Manager or apply on real Google Cloud.</Typography>
      {res && (
        <Box>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
            <Typography>{res.count} resource{res.count === 1 ? "" : "s"} exported · main.tf</Typography>
            <Button startIcon={<DownloadIcon />} onClick={download}>Download .tf</Button>
          </Stack>
          {res.unsupported.map((u) => <Typography key={u} color="text.secondary" variant="body2">{u}</Typography>)}
          <Box component="pre" data-testid="tf-text" sx={{ mt: 1, p: 2, bgcolor: "#f6f8fa", border: "1px solid #dadce0", borderRadius: 1, maxHeight: 460, overflow: "auto", fontSize: 12 }}>{res.files["main.tf"]}</Box>
        </Box>
      )}
    </Box>
  );
}
