/* Create service — Cloud Run's create-service form. Every real setting goes into ONE
 * native services.create body (+ a follow-up setIamPolicy for authentication); settings
 * Vyomi doesn't model are declared gaps, not dead controls. */
import { useState } from "react";
import {
  Accordion, AccordionDetails, AccordionSummary, Box, Button, Checkbox, Divider, FormControl, FormControlLabel,
  IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import ExpandMoreIcon from "@mui/icons-material/esm/ExpandMore.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

const SourceOpt = ({ title, children }) => (
  <Box>
    <Typography variant="h3" component="h2" sx={{ mb: 1.5 }}>{title}</Typography>
    <Stack spacing={2}>{children}</Stack>
  </Box>
);

export default function CreateService({ query }) {
  const notify = useNotify();
  const [source, setSource] = useState(query?.source === "function" ? "function" : query?.source === "repo" ? "repo" : "image");
  const [runtime, setRuntime] = useState(query?.runtime && api.RUNTIMES.includes(query.runtime) ? query.runtime : api.RUNTIMES[0]);
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const [region, setRegion] = useState(api.getRegion());
  const [image, setImage] = useState(api.DEFAULT_IMAGE);
  const [authMode, setAuthMode] = useState("public");
  const [billing, setBilling] = useState("request");
  const [scalingMode, setScalingMode] = useState("auto");
  const [minInst, setMinInst] = useState("0");
  const [maxInst, setMaxInst] = useState("100");
  const [ingress, setIngress] = useState("all");
  const [allowAlb, setAllowAlb] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [port, setPort] = useState("8080");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [memory, setMemory] = useState("512Mi");
  const [cpu, setCpu] = useState("1");
  const [envVars, setEnvVars] = useState([]);
  const [timeout, setTimeoutS] = useState("300");
  const [concurrency, setConcurrency] = useState("80");
  const [execEnv, setExecEnv] = useState("gen2");
  const [serviceAccount, setServiceAccount] = useState("");
  const [cpuBoost, setCpuBoost] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validServiceName(name) : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validServiceName(name) || source === "repo") return;
    setBusy(true); setError(null);
    try {
      const container = {
        image: source === "function" ? api.functionImage(runtime, "handler", api.DEFAULT_FUNCTION_SOURCE[runtime] || "") : image,
        ports: [{ containerPort: Number(port) || 8080 }],
        resources: { limits: { cpu, memory }, cpuIdle: billing === "request", startupCpuBoost: cpuBoost },
      };
      if (command.trim()) container.command = [command.trim()];
      if (args.trim()) container.args = args.split(",").map((a) => a.trim()).filter(Boolean);
      if (envVars.some((v) => v.name)) container.env = envVars.filter((v) => v.name).map((v) => ({ name: v.name, value: v.value }));
      const min = Number(minInst) || 0;
      const max = scalingMode === "manual" ? min : (Number(maxInst) || 100);
      const body = {
        template: {
          containers: [container],
          scaling: { minInstanceCount: min, maxInstanceCount: max },
          maxInstanceRequestConcurrency: Number(concurrency) || 80,
          timeout: `${Number(timeout) || 300}s`,
          executionEnvironment: execEnv === "gen1" ? "EXECUTION_ENVIRONMENT_GEN1" : "EXECUTION_ENVIRONMENT_GEN2",
        },
        ingress: ingress === "internal" ? (allowAlb ? "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" : "INGRESS_TRAFFIC_INTERNAL_ONLY") : "INGRESS_TRAFFIC_ALL",
      };
      if (serviceAccount.trim()) body.template.serviceAccount = serviceAccount.trim();
      if (source === "function") {
        body.annotations = api.functionAnnotations(runtime, "handler", api.DEFAULT_FUNCTION_SOURCE[runtime] || "");
      }
      await api.createService(region, name, body);
      if (authMode === "public") await api.setPublic(region, name, true);
      api.setRegion(region);
      notify.success(`Deployed service "${name}"`);
      location.hash = `/run/detail/${region}/${name}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 880 }}>
      <PageHeader title="Create service" back={<IconButton aria-label="Back" href="#/run/services"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to deploy service" />
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Service name and region cannot be changed later.</Typography>

      <SourceOpt title="Source">
        <RadioGroup value={source} onChange={(e) => setSource(e.target.value)} aria-label="Deployment source">
          <FormControlLabel value="image" control={<Radio size="small" />} label="Deploy one revision from an existing container image" />
          <FormControlLabel value="repo" control={<Radio size="small" />} label="Continuously deploy from a repository (source or function)" />
          <FormControlLabel value="function" control={<Radio size="small" />} label="Use an inline editor to create a function" />
        </RadioGroup>
        {source === "repo" && <NotSimulated compact feature="Continuously deploy from a repository" note="Vyomi has no Cloud Build or source-repository integration." />}
        {source === "image" && (
          <TextField label="Container image URL" required value={image} onChange={(e) => setImage(e.target.value)} sx={{ maxWidth: 560 }} />
        )}
      </SourceOpt>
      <Divider />

      {source === "function" && (
        <>
          <SourceOpt title="Function">
            <FormControl sx={{ maxWidth: 320 }}>
              <InputLabel id="rt-l">Runtime</InputLabel>
              <Select labelId="rt-l" label="Runtime" value={runtime} onChange={(e) => setRuntime(e.target.value)} inputProps={{ "aria-label": "Runtime" }}>
                {api.RUNTIMES.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
              </Select>
            </FormControl>
            <Typography variant="body2" color="text.secondary">Use an inline editor to create a function. You can edit the entry point and source after the service is created, from the Source tab.</Typography>
            <NotSimulated compact feature="Trigger (optional)" note="Vyomi has no Eventarc backend; every service is reachable over HTTPS only." />
          </SourceOpt>
          <Divider />
        </>
      )}

      <SourceOpt title="Configure">
        <TextField label="Service name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} inputProps={{ "aria-label": "Service name" }} sx={{ maxWidth: 420 }} helperText={nameErr || " "} />
        <FormControl sx={{ maxWidth: 320 }}>
          <InputLabel id="rg-l">Region</InputLabel>
          <Select labelId="rg-l" label="Region" value={region} onChange={(e) => setRegion(e.target.value)} inputProps={{ "aria-label": "Region" }}>
            {api.REGIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </Select>
        </FormControl>
        <NotSimulated compact feature="Custom URLs" note="Vyomi has no custom-domain or load-balancer integration for Cloud Run services." />
        <Typography variant="body2" color="text.secondary">Endpoint URL: generated after you create the service.</Typography>
      </SourceOpt>
      <Divider />

      <SourceOpt title="Authentication">
        <RadioGroup value={authMode} onChange={(e) => setAuthMode(e.target.value)} aria-label="Authentication">
          <FormControlLabel value="public" control={<Radio size="small" />} label="Allow public access" />
          <FormControlLabel value="auth" control={<Radio size="small" />} label="Require authentication" />
        </RadioGroup>
      </SourceOpt>
      <Divider />

      <SourceOpt title="Billing">
        <RadioGroup value={billing} onChange={(e) => setBilling(e.target.value)} aria-label="Billing">
          <FormControlLabel value="request" control={<Radio size="small" />} label={<><b>Request-based</b> — CPU is only allocated while a request is being processed</>} />
          <FormControlLabel value="instance" control={<Radio size="small" />} label={<><b>Instance-based</b> — CPU is always allocated</>} />
        </RadioGroup>
      </SourceOpt>
      <Divider />

      <SourceOpt title="Service scaling">
        <RadioGroup value={scalingMode} onChange={(e) => setScalingMode(e.target.value)} aria-label="Service scaling">
          <FormControlLabel value="auto" control={<Radio size="small" />} label="Auto scaling" />
          <FormControlLabel value="manual" control={<Radio size="small" />} label="Manual scaling" />
        </RadioGroup>
        <Stack direction="row" spacing={2}>
          <TextField label="Minimum number of instances" type="number" value={minInst} onChange={(e) => setMinInst(e.target.value)}
            helperText="Set to 1 to reduce cold starts." sx={{ width: 260 }} />
          {scalingMode === "auto" && (
            <TextField label="Maximum number of instances" type="number" value={maxInst} onChange={(e) => setMaxInst(e.target.value)} sx={{ width: 260 }} />
          )}
        </Stack>
        <NotSimulated compact feature="Customize autoscaling factors" note="Target CPU / concurrency utilization isn't modelled; Vyomi scales strictly between the min and max instance counts." />
      </SourceOpt>
      <Divider />

      <SourceOpt title="Ingress">
        <RadioGroup value={ingress} onChange={(e) => setIngress(e.target.value)} aria-label="Ingress">
          <FormControlLabel value="internal" control={<Radio size="small" />} label="Internal" />
          <FormControlLabel value="all" control={<Radio size="small" />} label="All" />
        </RadioGroup>
        {ingress === "internal" && (
          <FormControlLabel control={<Checkbox size="small" checked={allowAlb} onChange={(e) => setAllowAlb(e.target.checked)} />}
            label="Allow traffic from external Application Load Balancers" />
        )}
      </SourceOpt>
      <Divider />

      <Accordion expanded={advanced} onChange={() => setAdvanced((v) => !v)} sx={{ "&:before": { display: "none" } }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} aria-controls="adv-content" id="adv-header">
          <Typography variant="h3" component="h2">Containers, Networking, Security</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Stack spacing={3}>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 500, mb: 1.5 }}>Containers</Typography>
              <Stack spacing={2}>
                <Stack direction="row" spacing={2}>
                  <TextField label="Container port" type="number" value={port} onChange={(e) => setPort(e.target.value)} sx={{ width: 200 }} />
                  <FormControl sx={{ width: 200 }}><InputLabel id="mem-l">Memory</InputLabel>
                    <Select labelId="mem-l" label="Memory" value={memory} onChange={(e) => setMemory(e.target.value)}>{api.MEMORIES.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}</Select>
                  </FormControl>
                  <FormControl sx={{ width: 160 }}><InputLabel id="cpu-l">CPU</InputLabel>
                    <Select labelId="cpu-l" label="CPU" value={cpu} onChange={(e) => setCpu(e.target.value)}>{api.CPUS.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}</Select>
                  </FormControl>
                </Stack>
                <TextField label="Container command" value={command} onChange={(e) => setCommand(e.target.value)} helperText="Leave blank to use the entry point command defined in the container image." />
                <TextField label="Container arguments" value={args} onChange={(e) => setArgs(e.target.value)} helperText="Comma-separated. Arguments passed to the entry point command." />
                <NotSimulated compact feature="Ephemeral disk" />
                <NotSimulated compact feature="GPU" />
                <NotSimulated compact feature="Health checks" />
                <Box>
                  <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Variables & Secrets</Typography>
                  <Stack spacing={1}>
                    {envVars.map((v, i) => (
                      <Stack key={i} direction="row" spacing={1} alignItems="center">
                        <TextField label="Name" size="small" value={v.name} onChange={(e) => setEnvVars(envVars.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />
                        <TextField label="Value" size="small" value={v.value} onChange={(e) => setEnvVars(envVars.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                        <IconButton size="small" aria-label={`Delete variable ${i + 1}`} onClick={() => setEnvVars(envVars.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
                      </Stack>
                    ))}
                    <Box><Button size="small" startIcon={<AddIcon />} onClick={() => setEnvVars([...envVars, { name: "", value: "" }])}>Add variable</Button></Box>
                  </Stack>
                </Box>
                <NotSimulated compact feature="Volumes" />
                <Stack direction="row" spacing={2}>
                  <TextField label="Request timeout" type="number" value={timeout} onChange={(e) => setTimeoutS(e.target.value)} helperText="seconds (maximum 3600)" sx={{ width: 260 }} />
                  <TextField label="Maximum concurrent requests per instance" type="number" value={concurrency} onChange={(e) => setConcurrency(e.target.value)} sx={{ width: 300 }} />
                </Stack>
                <RadioGroup row value={execEnv} onChange={(e) => setExecEnv(e.target.value)} aria-label="Execution environment">
                  <FormControlLabel value="default" control={<Radio size="small" />} label="Default" />
                  <FormControlLabel value="gen1" control={<Radio size="small" />} label="First generation" />
                  <FormControlLabel value="gen2" control={<Radio size="small" />} label="Second generation" />
                </RadioGroup>
                <Typography variant="body2"><b>Revision scaling</b> — set above, under Service scaling.</Typography>
                <FormControlLabel control={<Checkbox size="small" checked={cpuBoost} onChange={(e) => setCpuBoost(e.target.checked)} />} label="Startup CPU boost" />
                <NotSimulated compact feature="Cloud SQL connections" />
              </Stack>
            </Box>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 500, mb: 1.5 }}>Networking</Typography>
              <NotSimulated feature="Use HTTP/2 end-to-end, Session affinity, Connect to a VPC for outbound traffic, Join a Service Mesh."
                note="Vyomi has no VPC, service-mesh or HTTP/2 data plane to model these against." />
            </Box>
            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 500, mb: 1.5 }}>Security</Typography>
              <Stack spacing={2}>
                <TextField label="Service account" value={serviceAccount} onChange={(e) => setServiceAccount(e.target.value)}
                  helperText="Leave blank to use the default compute service account." sx={{ maxWidth: 480 }} />
                <NotSimulated feature="Verify container deployment with Binary Authorization, Encryption (Google-managed encryption key / Cloud KMS key)" />
              </Stack>
            </Box>
          </Stack>
        </AccordionDetails>
      </Accordion>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy || source === "repo"}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/run/services">Cancel</Button>
      </Stack>
    </Box>
  );
}
