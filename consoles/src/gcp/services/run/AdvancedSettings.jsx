/* Advanced Cloud Run / Functions revision settings shared by Create service (Run), Create
 * function (Functions) and Create job: autoscaling factors, ephemeral disk, health checks,
 * volumes, Cloud SQL connections, Binary Authorization and CMEK. Every control writes a
 * real field of the native v2 RevisionTemplate; the backend validates it (core/gcp_run_core.py)
 * and each section carries its capability badge, so nothing here is a dead control. */
import { useState } from "react";
import { Box, Button, Checkbox, FormControlLabel, IconButton, MenuItem, Radio, RadioGroup, Select, FormControl, InputLabel, Stack, TextField, Typography } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { getProject } from "../../project.js";

export const emptyAdvanced = () => ({
  targetUtil: "", cpuTarget: "",
  disk: false, diskSize: "10Gi", diskPath: "/mnt/disk",
  startup: { on: false, kind: "httpGet", path: "/", port: "8080", period: "10", timeout: "1", failure: "3", delay: "0" },
  liveness: { on: false, kind: "httpGet", path: "/", port: "8080", period: "10", timeout: "1", failure: "3", delay: "0" },
  volumes: [],            // { name, kind: emptyDir|secret|gcs|nfs, mountPath, a, b }
  sqlInstances: "",
  binauthz: false, binauthzPolicy: "",
  cmek: false, kmsKey: "",
  h2: false, affinity: false, vpcKind: "none", connector: "", network: "default", subnet: "", egress: "PRIVATE_RANGES_ONLY", tags: "", mesh: "",
  noDefaultUrl: false, audiences: "",
});

const Group = ({ title, capId, children }) => (
  <Box data-adv-section={title}>
    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
      <Typography variant="body2" sx={{ fontWeight: 500 }}>{title}</Typography>
      {capId && <CapabilityBadge id={capId} />}
    </Stack>
    <Stack spacing={1.5}>{children}</Stack>
  </Box>
);

export function AutoscalingFactors({ a, set }) {
  return (
    <Group title="Customize autoscaling factors" capId="gcp.run.template.autoscaling">
      <Stack direction="row" spacing={2}>
        <TextField size="small" label="Target concurrency utilization (%)" type="number" value={a.targetUtil} onChange={(e) => set({ targetUtil: e.target.value })}
          helperText="1-100, default 60" inputProps={{ "aria-label": "Target concurrency utilization" }} sx={{ width: 280 }} />
        <TextField size="small" label="Target CPU utilization (%)" type="number" value={a.cpuTarget} onChange={(e) => set({ cpuTarget: e.target.value })}
          helperText="1-100, default 60" inputProps={{ "aria-label": "Target CPU utilization" }} sx={{ width: 240 }} />
      </Stack>
    </Group>
  );
}

export function EphemeralDisk({ a, set }) {
  return (
    <Group title="Ephemeral disk" capId="gcp.run.template.ephemeral-disk">
      <FormControlLabel control={<Checkbox size="small" checked={a.disk} onChange={(e) => set({ disk: e.target.checked })} />} label="Attach an ephemeral disk (second generation)" />
      {a.disk && (
        <Stack direction="row" spacing={2}>
          <TextField size="small" label="Disk size" value={a.diskSize} onChange={(e) => set({ diskSize: e.target.value })} helperText="e.g. 10Gi" inputProps={{ "aria-label": "Disk size" }} sx={{ width: 180 }} />
          <TextField size="small" label="Mount path" value={a.diskPath} onChange={(e) => set({ diskPath: e.target.value })} inputProps={{ "aria-label": "Disk mount path" }} sx={{ width: 240 }} />
        </Stack>
      )}
    </Group>
  );
}

function ProbeEditor({ name, p, setP }) {
  const f = (k) => (e) => setP({ ...p, [k]: e.target.value });
  return (
    <Box>
      <FormControlLabel control={<Checkbox size="small" checked={p.on} onChange={(e) => setP({ ...p, on: e.target.checked })} />} label={`${name} probe`} />
      {p.on && (
        <Stack spacing={1.5} sx={{ pl: 3 }}>
          <RadioGroup row value={p.kind} onChange={f("kind")} aria-label={`${name} probe type`}>
            <FormControlLabel value="httpGet" control={<Radio size="small" />} label="HTTP" />
            <FormControlLabel value="tcpSocket" control={<Radio size="small" />} label="TCP" />
            <FormControlLabel value="grpc" control={<Radio size="small" />} label="gRPC" />
          </RadioGroup>
          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap>
            {p.kind === "httpGet" && <TextField size="small" label="Path" value={p.path} onChange={f("path")} inputProps={{ "aria-label": `${name} probe path` }} sx={{ width: 160 }} />}
            <TextField size="small" label="Port" type="number" value={p.port} onChange={f("port")} sx={{ width: 100 }} />
            <TextField size="small" label="Initial delay (s)" type="number" value={p.delay} onChange={f("delay")} sx={{ width: 140 }} />
            <TextField size="small" label="Period (s)" type="number" value={p.period} onChange={f("period")} sx={{ width: 110 }} />
            <TextField size="small" label="Timeout (s)" type="number" value={p.timeout} onChange={f("timeout")} sx={{ width: 110 }} />
            <TextField size="small" label="Failure threshold" type="number" value={p.failure} onChange={f("failure")} sx={{ width: 140 }} />
          </Stack>
        </Stack>
      )}
    </Box>
  );
}

export function HealthChecks({ a, set }) {
  return (
    <Group title="Health checks" capId="gcp.run.template.health-checks">
      <ProbeEditor name="Startup" p={a.startup} setP={(startup) => set({ startup })} />
      <ProbeEditor name="Liveness" p={a.liveness} setP={(liveness) => set({ liveness })} />
    </Group>
  );
}

const VOL_KINDS = [["emptyDir", "In-memory"], ["secret", "Secret Manager"], ["gcs", "Cloud Storage bucket"], ["nfs", "NFS"]];
export function VolumesPanel({ a, set }) {
  const upd = (i, patch) => set({ volumes: a.volumes.map((v, j) => (j === i ? { ...v, ...patch } : v)) });
  return (
    <Group title="Volumes" capId="gcp.run.template.volumes">
      {a.volumes.map((v, i) => (
        <Stack key={i} direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <TextField size="small" label="Name" value={v.name} onChange={(e) => upd(i, { name: e.target.value })} inputProps={{ "aria-label": `Volume ${i + 1} name` }} sx={{ width: 130 }} />
          <FormControl size="small" sx={{ width: 190 }}>
            <InputLabel id={`vk-${i}`}>Volume type</InputLabel>
            <Select labelId={`vk-${i}`} label="Volume type" value={v.kind} onChange={(e) => upd(i, { kind: e.target.value })}>
              {VOL_KINDS.map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}
            </Select>
          </FormControl>
          {v.kind === "emptyDir" && <TextField size="small" label="Size limit (optional)" value={v.a} onChange={(e) => upd(i, { a: e.target.value })} sx={{ width: 170 }} />}
          {v.kind === "secret" && <TextField size="small" label="Secret" value={v.a} onChange={(e) => upd(i, { a: e.target.value })} inputProps={{ "aria-label": `Volume ${i + 1} secret` }} sx={{ width: 170 }} />}
          {v.kind === "gcs" && <TextField size="small" label="Bucket" value={v.a} onChange={(e) => upd(i, { a: e.target.value })} inputProps={{ "aria-label": `Volume ${i + 1} bucket` }} sx={{ width: 170 }} />}
          {v.kind === "nfs" && (<>
            <TextField size="small" label="Server" value={v.a} onChange={(e) => upd(i, { a: e.target.value })} sx={{ width: 150 }} />
            <TextField size="small" label="Path" value={v.b} onChange={(e) => upd(i, { b: e.target.value })} sx={{ width: 130 }} />
          </>)}
          <TextField size="small" label="Mount path" value={v.mountPath} onChange={(e) => upd(i, { mountPath: e.target.value })} inputProps={{ "aria-label": `Volume ${i + 1} mount path` }} sx={{ width: 150 }} />
          <IconButton size="small" aria-label={`Delete volume ${i + 1}`} onClick={() => set({ volumes: a.volumes.filter((_, j) => j !== i) })}><DeleteIcon fontSize="small" /></IconButton>
        </Stack>
      ))}
      <Box><Button size="small" startIcon={<AddIcon />} onClick={() => set({ volumes: [...a.volumes, { name: `volume-${a.volumes.length + 1}`, kind: "emptyDir", mountPath: `/mnt/vol${a.volumes.length + 1}`, a: "", b: "" }] })}>Add volume</Button></Box>
    </Group>
  );
}

export function CloudSqlPanel({ a, set }) {
  return (
    <Group title="Cloud SQL connections" capId="gcp.run.template.cloudsql">
      <TextField size="small" label="Connection names" value={a.sqlInstances} onChange={(e) => set({ sqlInstances: e.target.value })}
        helperText="Comma-separated PROJECT:REGION:INSTANCE; each must be an existing Cloud SQL instance." inputProps={{ "aria-label": "Cloud SQL connections" }} sx={{ maxWidth: 520 }} />
    </Group>
  );
}

export function NetworkingPanel({ a, set, cap = "gcp.run.networking" }) {
  return (
    <Group title="Networking" capId={cap}>
      <FormControlLabel control={<Checkbox size="small" checked={a.h2} onChange={(e) => set({ h2: e.target.checked })} />} label="Use HTTP/2 end-to-end (container port is h2c)" />
      <FormControlLabel control={<Checkbox size="small" checked={a.affinity} onChange={(e) => set({ affinity: e.target.checked })} />} label="Session affinity" />
      <FormControl size="small" sx={{ maxWidth: 360 }}>
        <InputLabel id="vpc-kind">Connect to a VPC for outbound traffic</InputLabel>
        <Select labelId="vpc-kind" label="Connect to a VPC for outbound traffic" value={a.vpcKind} onChange={(e) => set({ vpcKind: e.target.value })} inputProps={{ "aria-label": "VPC outbound traffic" }}>
          <MenuItem value="none">None</MenuItem>
          <MenuItem value="connector">Serverless VPC Access connector</MenuItem>
          <MenuItem value="direct">Send traffic directly to a VPC</MenuItem>
        </Select>
      </FormControl>
      {a.vpcKind === "connector" && <TextField size="small" label="Connector" value={a.connector} onChange={(e) => set({ connector: e.target.value })}
        helperText="Name of a connector in the service's region (Networking > Serverless VPC access)." inputProps={{ "aria-label": "VPC connector" }} sx={{ maxWidth: 360 }} />}
      {a.vpcKind === "direct" && (<>
        <TextField size="small" label="Network" value={a.network} onChange={(e) => set({ network: e.target.value })} inputProps={{ "aria-label": "VPC network" }} sx={{ maxWidth: 360 }} />
        <TextField size="small" label="Subnet" value={a.subnet} onChange={(e) => set({ subnet: e.target.value })} helperText="Must exist in the service's region." inputProps={{ "aria-label": "VPC subnet" }} sx={{ maxWidth: 360 }} />
        <TextField size="small" label="Network tags (comma-separated)" value={a.tags} onChange={(e) => set({ tags: e.target.value })} inputProps={{ "aria-label": "Network tags" }} sx={{ maxWidth: 360 }} />
      </>)}
      {a.vpcKind !== "none" && (
        <RadioGroup value={a.egress} onChange={(e) => set({ egress: e.target.value })} aria-label="Traffic routing">
          <FormControlLabel value="PRIVATE_RANGES_ONLY" control={<Radio size="small" />} label="Route only requests to private IPs to the VPC" />
          <FormControlLabel value="ALL_TRAFFIC" control={<Radio size="small" />} label="Route all traffic to the VPC" />
        </RadioGroup>
      )}
      <TextField size="small" label="Service mesh (blank = none)" value={a.mesh} onChange={(e) => set({ mesh: e.target.value })}
        helperText="projects/PROJECT/locations/global/meshes/NAME" inputProps={{ "aria-label": "Service mesh" }} sx={{ maxWidth: 520 }} />
    </Group>
  );
}

export function CustomUrlsPanel({ a, set, cap = "gcp.run.networking" }) {
  return (
    <Group title="Custom URLs" capId={cap}>
      <FormControlLabel control={<Checkbox size="small" checked={a.noDefaultUrl} onChange={(e) => set({ noDefaultUrl: e.target.checked })} />} label="Disable the default run.app URL" />
      <TextField size="small" label="Custom audiences (comma-separated)" value={a.audiences} onChange={(e) => set({ audiences: e.target.value })}
        helperText="Audiences IAM-authenticated callers may mint ID tokens for. Map a custom domain from the Domain mappings page." inputProps={{ "aria-label": "Custom audiences" }} sx={{ maxWidth: 520 }} />
    </Group>
  );
}

export function SecurityPanel({ a, set }) {
  return (<>
    <Group title="Binary Authorization" capId="gcp.run.binary-authorization">
      <FormControlLabel control={<Checkbox size="small" checked={a.binauthz} onChange={(e) => set({ binauthz: e.target.checked })} />} label="Verify container deployment with Binary Authorization" />
      {a.binauthz && <TextField size="small" label="Policy (blank = default policy)" value={a.binauthzPolicy} onChange={(e) => set({ binauthzPolicy: e.target.value })}
        helperText="projects/PROJECT/platforms/cloudRun/policies/NAME" inputProps={{ "aria-label": "Binary Authorization policy" }} sx={{ maxWidth: 520 }} />}
    </Group>
    <Group title="Encryption" capId="gcp.run.template.cmek">
      <RadioGroup value={a.cmek ? "cmek" : "google"} onChange={(e) => set({ cmek: e.target.value === "cmek" })} aria-label="Encryption">
        <FormControlLabel value="google" control={<Radio size="small" />} label="Google-managed encryption key" />
        <FormControlLabel value="cmek" control={<Radio size="small" />} label="Cloud KMS key" />
      </RadioGroup>
      {a.cmek && <TextField size="small" label="Cloud KMS key" value={a.kmsKey} onChange={(e) => set({ kmsKey: e.target.value })}
        helperText="projects/P/locations/REGION/keyRings/R/cryptoKeys/K (same region as the service)" inputProps={{ "aria-label": "Cloud KMS key" }} sx={{ maxWidth: 560 }} />}
    </Group>
  </>);
}

const num = (v, d) => (v === "" || v == null || Number.isNaN(Number(v)) ? d : Number(v));
function probeBody(p) {
  const body = { periodSeconds: num(p.period, 10), timeoutSeconds: num(p.timeout, 1), failureThreshold: num(p.failure, 3), initialDelaySeconds: num(p.delay, 0) };
  const port = num(p.port, 8080);
  if (p.kind === "httpGet") body.httpGet = { path: p.path || "/", port };
  else if (p.kind === "tcpSocket") body.tcpSocket = { port };
  else body.grpc = { port };
  return body;
}

/** Fold the advanced state into the container + template (+ service body) being sent. */
export function applyAdvanced(a, { container, template, body, gen1, region }) {
  const volumes = [], mounts = [];
  if (a.targetUtil || a.cpuTarget) {
    const ann = { ...(template.annotations || {}) };
    if (a.targetUtil) ann["autoscaling.knative.dev/target-utilization-percentage"] = String(a.targetUtil);
    if (a.cpuTarget) ann["run.googleapis.com/autoscaling-target-cpu-utilization"] = String(a.cpuTarget);
    template.annotations = ann;
  }
  if (a.disk) {
    volumes.push({ name: "ephemeral-disk", emptyDir: { medium: "DISK", sizeLimit: a.diskSize } });
    mounts.push({ name: "ephemeral-disk", mountPath: a.diskPath });
  }
  for (const v of a.volumes) {
    const src = v.kind === "emptyDir" ? { emptyDir: v.a ? { medium: "MEMORY", sizeLimit: v.a } : { medium: "MEMORY" } }
      : v.kind === "secret" ? { secret: { secret: v.a, items: [{ path: "latest", version: "latest" }] } }
      : v.kind === "gcs" ? { gcs: { bucket: v.a } } : { nfs: { server: v.a, path: v.b } };
    volumes.push({ name: v.name, ...src });
    mounts.push({ name: v.name, mountPath: v.mountPath });
  }
  const sql = a.sqlInstances.split(",").map((s) => s.trim()).filter(Boolean);
  if (sql.length) {
    volumes.push({ name: "cloudsql", cloudSqlInstance: { instances: sql } });
    mounts.push({ name: "cloudsql", mountPath: "/cloudsql" });
  }
  if (volumes.length) { template.volumes = volumes; container.volumeMounts = mounts; }
  if (a.startup.on) container.startupProbe = probeBody(a.startup);
  if (a.liveness.on) container.livenessProbe = probeBody(a.liveness);
  if (body) {
    if (a.binauthz) body.binaryAuthorization = a.binauthzPolicy.trim() ? { policy: a.binauthzPolicy.trim() } : { useDefault: true };
  }
  if (a.cmek && a.kmsKey.trim()) template.encryptionKey = a.kmsKey.trim();
  if (body) {   // services only: jobs expose no port / affinity / mesh
    if (a.h2) container.ports = [{ name: "h2c", containerPort: container.ports?.[0]?.containerPort || 8080 }];
    if (a.affinity) template.sessionAffinity = true;
    if (a.mesh.trim()) template.serviceMesh = { mesh: a.mesh.trim() };
    if (a.noDefaultUrl) body.defaultUriDisabled = true;
    const aud = a.audiences.split(",").map((x) => x.trim()).filter(Boolean);
    if (aud.length) body.customAudiences = aud;
  }
  if (a.vpcKind === "connector" && a.connector.trim()) {
    const c = a.connector.trim();
    template.vpcAccess = { connector: c.startsWith("projects/") ? c : `projects/${getProject()}/locations/${region}/connectors/${c}`, egress: a.egress };
  } else if (a.vpcKind === "direct") {
    template.vpcAccess = { networkInterfaces: [{ network: a.network.trim() || "default", ...(a.subnet.trim() ? { subnetwork: a.subnet.trim() } : {}),
      ...(a.tags.trim() ? { tags: a.tags.split(",").map((x) => x.trim()).filter(Boolean) } : {}) }], egress: a.egress };
  }
}

export function useAdvanced() {
  const [a, setA] = useState(emptyAdvanced);
  return [a, (patch) => setA((cur) => ({ ...cur, ...patch }))];
}
