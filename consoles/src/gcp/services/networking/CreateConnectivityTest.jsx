/* Create a Connectivity Test — a native connectivityTests.insert call (networkmanagement v1),
 * answered synchronously by the shared netsim evaluator: reachability, firewall/route hops
 * and the drop cause come back in the same create response the real API returns as a done LRO. */
import { useState } from "react";
import {
  Box, Button, FormControl, IconButton, InputLabel, MenuItem, Radio, RadioGroup, FormControlLabel,
  Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { getProject } from "../../project.js";
import * as computeApi from "../compute/api.js";
import * as api from "./api.js";

const PROTOCOLS = ["TCP", "UDP", "ICMP", "ESP", "AH", "SCTP"];

function EndpointFields({ label, type, setType, instance, setInstance, ip, setIp, options }) {
  return (
    <Stack spacing={1.5}>
      <Typography variant="h3" component="h2">{label}</Typography>
      <RadioGroup row value={type} onChange={(e) => setType(e.target.value)} aria-label={`${label} endpoint`}>
        <FormControlLabel value="Instance" control={<Radio size="small" />} label="Instance" />
        <FormControlLabel value="IP address" control={<Radio size="small" />} label="IP address" />
      </RadioGroup>
      {type === "Instance" ? (
        <FormControl required sx={{ maxWidth: 420 }}>
          <InputLabel id={`${label}-instance-label`}>{`${label} instance`}</InputLabel>
          <Select labelId={`${label}-instance-label`} label={`${label} instance`} value={instance} onChange={(e) => setInstance(e.target.value)}>
            {options.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
          </Select>
        </FormControl>
      ) : (
        <TextField label={`${label} IP address`} required value={ip} onChange={(e) => setIp(e.target.value.trim())} placeholder="203.0.113.1" sx={{ maxWidth: 420 }} />
      )}
    </Stack>
  );
}

export default function CreateConnectivityTest() {
  const notify = useNotify();
  const { data: instances = [] } = useAsync(() => computeApi.listInstancesAllZones(), []);
  const instanceOptions = instances.map((i) => ({
    value: `projects/${getProject()}/zones/${i._zoneScope}/instances/${i.name}`, label: `${i.name} (${i._zoneScope})`,
  }));
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [srcType, setSrcType] = useState("Instance");
  const [srcInstance, setSrcInstance] = useState("");
  const [srcIp, setSrcIp] = useState("");
  const [dstType, setDstType] = useState("IP address");
  const [dstInstance, setDstInstance] = useState("");
  const [dstIp, setDstIp] = useState("");
  const [port, setPort] = useState("");
  const [protocol, setProtocol] = useState("TCP");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const nameErr = touched ? api.validName(name, "Name") : null;
  const needsPort = protocol === "TCP" || protocol === "UDP";
  const srcOk = srcType === "Instance" ? !!srcInstance : !!srcIp;
  const dstOk = dstType === "Instance" ? !!dstInstance : !!dstIp;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (api.validName(name, "Name") || !srcOk || !dstOk || (needsPort && !port)) return;
    setBusy(true); setError(null);
    try {
      const source = srcType === "Instance" ? { instance: srcInstance } : { ipAddress: srcIp };
      const destination = {
        ...(dstType === "Instance" ? { instance: dstInstance } : { ipAddress: dstIp }),
        ...(needsPort && port ? { port: Number(port) } : {}),
      };
      await api.insertConnectivityTest(name, { description, source, destination, protocol });
      notify.success(`Created connectivity test "${name}"`);
      window.location.hash = `#/networking/connectivity-tests/details/${name}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 760 }}>
      <PageHeader title="Create Connectivity Test" back={<IconButton aria-label="Back" href="#/networking/connectivity-tests/list"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create connectivity test" />

      <Stack spacing={2.5}>
        <Typography variant="h3" component="h2">Test details</Typography>
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value.trim())} onBlur={() => setTouched(true)}
          error={!!nameErr} helperText={nameErr} sx={{ maxWidth: 480 }} />
        <TextField label="Description" value={description} onChange={(e) => setDescription(e.target.value)} sx={{ maxWidth: 480 }} />

        <EndpointFields label="Source" type={srcType} setType={setSrcType} instance={srcInstance} setInstance={setSrcInstance}
          ip={srcIp} setIp={setSrcIp} options={instanceOptions} />
        <EndpointFields label="Destination" type={dstType} setType={setDstType} instance={dstInstance} setInstance={setDstInstance}
          ip={dstIp} setIp={setDstIp} options={instanceOptions} />

        <Typography variant="h3" component="h2">Protocol</Typography>
        <Stack direction="row" spacing={2}>
          <FormControl sx={{ maxWidth: 200 }}>
            <InputLabel id="protocol-label">Protocol</InputLabel>
            <Select labelId="protocol-label" label="Protocol" value={protocol} onChange={(e) => setProtocol(e.target.value)}>
              {PROTOCOLS.map((p) => <MenuItem key={p} value={p}>{p}</MenuItem>)}
            </Select>
          </FormControl>
          {needsPort && (
            <TextField label="Port" required type="number" value={port} onChange={(e) => setPort(e.target.value)} sx={{ maxWidth: 160 }} />
          )}
        </Stack>
      </Stack>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/networking/connectivity-tests/list">Cancel</Button>
      </Stack>
    </Box>
  );
}
