/* Overview — the three "get started" cards the real console shows on Cloud Run's landing
 * page: deploy a web service, create a job/worker pool, or write a function. Every button
 * here is real navigation into a page that performs the action for real; only "Connect
 * repository" (continuous deployment from a source repo) has no Vyomi backend. */
import { Box, Button, Stack, Typography } from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/esm/CloudUpload.js";
import WorkIcon from "@mui/icons-material/esm/WorkOutline.js";
import DnsIcon from "@mui/icons-material/esm/Dns.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { NotSimulated, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Overview() {
  return (
    <Box>
      <PageHeader title="Overview" actions={<Button startIcon={<RefreshIcon />} onClick={() => location.reload()}>Refresh</Button>} />
      <Stack spacing={2}>
        <Section title="Deploy a web service">
          <Stack spacing={1.5}>
            <Typography variant="body2" color="text.secondary">Deploy a container image or continuously deploy from a repository.</Typography>
            <Stack direction="row" spacing={1}>
              <Button variant="contained" startIcon={<CloudUploadIcon />} href="#/run/create?source=container">Deploy container</Button>
              <Button href="#/run/create?source=repo">Connect repository</Button>
            </Stack>
            <NotSimulated compact feature="Connect repository" note="Vyomi has no Cloud Build or source-repository integration — continuous deployment from a repository isn't backed by a Vyomi backend yet." />
          </Stack>
        </Section>
        <Section title="Create a batch job or a background worker pool">
          <Stack spacing={1.5}>
            <Typography variant="body2" color="text.secondary">Run a container to completion, or run one that doesn't serve HTTP traffic.</Typography>
            <Stack direction="row" spacing={1}>
              <Button variant="contained" startIcon={<WorkIcon />} href="#/run/jobs/create">Create job</Button>
              <Button startIcon={<DnsIcon />} href="#/run/worker-pools">Create worker pool</Button>
            </Stack>
          </Stack>
        </Section>
        <Section title="Write a function">
          <Stack spacing={1.5}>
            <Typography variant="body2" color="text.secondary">Use an inline editor to create a function. Pick a language to get started.</Typography>
            <Typography variant="caption" color="text.secondary">Language</Typography>
            <Stack useFlexGap direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
              {api.RUNTIMES.map((r) => {
                const lang = r.split(" ")[0].replace(".", "");
                return <Button key={r} size="small" href={`#/run/create?source=function&runtime=${encodeURIComponent(r)}`}>{lang}</Button>;
              })}
            </Stack>
          </Stack>
        </Section>
      </Stack>
    </Box>
  );
}
