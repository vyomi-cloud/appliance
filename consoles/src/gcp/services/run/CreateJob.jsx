/* Create job — a dedicated page (the real console's /run/jobs/create), mirroring the
 * create-service form's structure: container image, configure, then an expandable
 * advanced section. One native jobs.create body, with an optional immediate jobs.run. */
import { useState } from "react";
import {
  Accordion, AccordionDetails, AccordionSummary, Box, Button, Checkbox, Divider, FormControl, FormControlLabel,
  IconButton, InputLabel, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import ExpandMoreIcon from "@mui/icons-material/esm/ExpandMore.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

const SourceOpt = ({ title, children }) => (
  <Box>
    <Typography variant="h3" component="h2" sx={{ mb: 1.5 }}>{title}</Typography>
    <Stack spacing={2}>{children}</Stack>
  </Box>
);

export default function CreateJob() {
  const notify = useNotify();
  const [image, setImage] = useState(api.DEFAULT_IMAGE);
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [region, setRegion] = useState(api.getRegion());
  const [taskCount, setTaskCount] = useState("1");
  const [executeNow, setExecuteNow] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [memory, setMemory] = useState("512Mi");
  const [cpu, setCpu] = useState("1");
  const [taskTimeout, setTaskTimeout] = useState("10");
  const [retries, setRetries] = useState("3");
  const [parallelism, setParallelism] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validName(name, "Job") : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validName(name, "Job")) return;
    setBusy(true); setError(null);
    try {
      const body = {
        template: {
          taskCount: Number(taskCount) || 1,
          parallelism: Number(parallelism) || 1,
          template: {
            containers: [{ image, resources: { limits: { cpu, memory } } }],
            timeout: `${(Number(taskTimeout) || 10) * 60}s`,
            maxRetries: Number(retries) || 3,
          },
        },
      };
      await api.createJob(region, name, body);
      api.setRegion(region);
      if (executeNow) await api.runJob(region, name);
      notify.success(`Created job "${name}"`);
      location.hash = `/run/jobs/details/${region}/${name}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Create job" back={<IconButton aria-label="Back" href="#/run/jobs"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create job" />

      <SourceOpt title="Container image">
        <TextField label="Container image URL" required value={image} onChange={(e) => setImage(e.target.value)} sx={{ maxWidth: 560 }} />
        <Stack direction="row" spacing={1}>
          <NotSimulated compact feature="Select" note="Vyomi has no Artifact Registry image picker; paste an image URL directly." />
          <Button size="small" onClick={() => setImage(api.DEFAULT_IMAGE)}>Test with a sample container</Button>
        </Stack>
      </SourceOpt>
      <Divider />

      <SourceOpt title="Configure">
        <TextField label="Job name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} inputProps={{ "aria-label": "Job name" }} sx={{ maxWidth: 420 }} helperText={nameErr || " "} />
        <FormControl sx={{ maxWidth: 320 }}><InputLabel id="jrg-l">Region</InputLabel>
          <Select labelId="jrg-l" label="Region" value={region} onChange={(e) => setRegion(e.target.value)} inputProps={{ "aria-label": "Region" }}>
            {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <TextField label="Number of tasks" type="number" value={taskCount} onChange={(e) => setTaskCount(e.target.value)} sx={{ width: 260 }} />
        <FormControlLabel control={<Checkbox size="small" checked={executeNow} onChange={(e) => setExecuteNow(e.target.checked)} />} label="Execute job immediately" />
      </SourceOpt>
      <Divider />

      <Accordion expanded={advanced} onChange={() => setAdvanced((v) => !v)} sx={{ "&:before": { display: "none" } }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} aria-controls="adv-content" id="adv-header">
          <Typography variant="h3" component="h2">Containers, Volumes, Connections, Security</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={2}>
            <Stack direction="row" spacing={2}>
              <FormControl sx={{ width: 200 }}><InputLabel id="jmem-l">Memory</InputLabel>
                <Select labelId="jmem-l" label="Memory" value={memory} onChange={(e) => setMemory(e.target.value)}>{api.MEMORIES.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}</Select>
              </FormControl>
              <FormControl sx={{ width: 160 }}><InputLabel id="jcpu-l">CPU</InputLabel>
                <Select labelId="jcpu-l" label="CPU" value={cpu} onChange={(e) => setCpu(e.target.value)}>{api.CPUS.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}</Select>
              </FormControl>
            </Stack>
            <Stack direction="row" spacing={2}>
              <TextField label="Task timeout" type="number" value={taskTimeout} onChange={(e) => setTaskTimeout(e.target.value)} helperText="minutes" sx={{ width: 220 }} />
              <TextField label="Number of retries per failed task" type="number" value={retries} onChange={(e) => setRetries(e.target.value)} sx={{ width: 280 }} />
              <TextField label="Parallelism" type="number" value={parallelism} onChange={(e) => setParallelism(e.target.value)} sx={{ width: 180 }} />
            </Stack>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/run/jobs">Cancel</Button>
      </Stack>
    </Box>
  );
}
