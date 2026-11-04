/* Shared field groups for the job create wizard and the edit form: the schedule, the
 * target (HTTP / Pub/Sub / App Engine HTTP / Workflows via HTTP) and retry config. Both
 * forms hold one `state` object (see initialState()) and pass it + setState here. */
import {
  Box, Button, FormControl, FormHelperText, IconButton, InputLabel, MenuItem, Select, Stack,
  TextField, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { NotSimulated } from "../../kit/common.jsx";
import { DURATION_UNITS, LOCATIONS, timezones } from "./api.js";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";

export const HTTP_METHODS = ["POST", "GET", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"];
export const TARGET_TYPES = ["HTTP", "Pub/Sub", "App Engine HTTP", "Workflows via HTTP"];

export function initialState() {
  return {
    name: "", region: api.DEFAULT_REGION, description: "", schedule: "", timeZone: "Etc/UTC",
    targetType: "HTTP",
    httpUrl: "", httpMethod: "POST", headers: [], body: "", auth: "None", serviceAccount: "", audience: "",
    pubsubTopic: "", pubsubMessage: "",
    aeUrl: "/", aeMethod: "POST",
    retryCount: "0", maxRetryDuration: { n: "0", unit: "s" }, minBackoff: { n: "5", unit: "s" },
    maxBackoff: { n: "1", unit: "h" }, maxDoublings: "5", attemptDeadline: { n: "3", unit: "m" },
  };
}

/** Raw REST Job (from getJob) → the same shape initialState() produces, for the edit form. */
export function stateFromJob(job) {
  const s = initialState();
  s.name = api.jobId(job); s.region = api.jobRegion(job);
  s.description = job.description || ""; s.schedule = job.schedule || ""; s.timeZone = job.timeZone || "Etc/UTC";
  if (job.httpTarget) {
    s.targetType = "HTTP";
    s.httpUrl = job.httpTarget.uri || ""; s.httpMethod = job.httpTarget.httpMethod || "POST";
    s.headers = Object.entries(job.httpTarget.headers || {}).map(([key, value]) => ({ key, value }));
    s.body = job.httpTarget.body ? atob(job.httpTarget.body) : "";
    s.auth = job.httpTarget.oidcToken ? "Add OIDC token" : job.httpTarget.oauthToken ? "Add OAuth token" : "None";
    s.serviceAccount = (job.httpTarget.oidcToken || job.httpTarget.oauthToken || {}).serviceAccountEmail || "";
    s.audience = job.httpTarget.oidcToken?.audience || "";
  } else if (job.pubsubTarget) {
    s.targetType = "Pub/Sub";
    s.pubsubTopic = job.pubsubTarget.topicName || "";
    s.pubsubMessage = job.pubsubTarget.data ? atob(job.pubsubTarget.data) : "";
  } else if (job.appEngineHttpTarget) {
    s.targetType = "App Engine HTTP";
    s.aeUrl = job.appEngineHttpTarget.relativeUri || "/"; s.aeMethod = job.appEngineHttpTarget.httpMethod || "POST";
    s.headers = Object.entries(job.appEngineHttpTarget.headers || {}).map(([key, value]) => ({ key, value }));
    s.body = job.appEngineHttpTarget.body ? atob(job.appEngineHttpTarget.body) : "";
  }
  const rc = job.retryConfig || {};
  s.retryCount = String(rc.retryCount ?? 0);
  s.maxRetryDuration = api.splitDuration(rc.maxRetryDuration || "0s");
  s.minBackoff = api.splitDuration(rc.minBackoffDuration || "5s");
  s.maxBackoff = api.splitDuration(rc.maxBackoffDuration || "3600s");
  s.maxDoublings = String(rc.maxDoublings ?? 5);
  s.attemptDeadline = api.splitDuration(job.attemptDeadline || "180s");
  return s;
}

/** state → the REST Job body (minus `name`, added by the caller). */
export function jobBody(s) {
  const headers = s.headers.filter((h) => h.key).reduce((o, h) => ({ ...o, [h.key]: h.value }), {});
  const body = {
    schedule: s.schedule.trim(), timeZone: s.timeZone,
    ...(s.description ? { description: s.description } : {}),
    retryConfig: {
      retryCount: Number(s.retryCount) || 0,
      maxRetryDuration: api.joinDuration(s.maxRetryDuration.n, s.maxRetryDuration.unit),
      minBackoffDuration: api.joinDuration(s.minBackoff.n, s.minBackoff.unit),
      maxBackoffDuration: api.joinDuration(s.maxBackoff.n, s.maxBackoff.unit),
      maxDoublings: Number(s.maxDoublings) || 0,
    },
    attemptDeadline: api.joinDuration(s.attemptDeadline.n, s.attemptDeadline.unit),
  };
  if (s.targetType === "HTTP") {
    const auth = s.auth === "Add OAuth token" ? { oauthToken: { serviceAccountEmail: s.serviceAccount } }
      : s.auth === "Add OIDC token" ? { oidcToken: { serviceAccountEmail: s.serviceAccount, ...(s.audience ? { audience: s.audience } : {}) } } : {};
    body.httpTarget = {
      uri: s.httpUrl.trim(), httpMethod: s.httpMethod,
      ...(Object.keys(headers).length ? { headers } : {}),
      ...(s.body && !["GET", "HEAD"].includes(s.httpMethod) ? { body: btoa(s.body) } : {}),
      ...auth,
    };
  } else if (s.targetType === "Pub/Sub") {
    body.pubsubTarget = { topicName: s.pubsubTopic, ...(s.pubsubMessage ? { data: btoa(s.pubsubMessage) } : {}) };
  } else if (s.targetType === "App Engine HTTP") {
    body.appEngineHttpTarget = {
      relativeUri: s.aeUrl.trim() || "/", httpMethod: s.aeMethod,
      ...(Object.keys(headers).length ? { headers } : {}),
      ...(s.body && !["GET", "HEAD"].includes(s.aeMethod) ? { body: btoa(s.body) } : {}),
    };
  }
  return body;
}

export function targetError(s) {
  if (s.targetType === "Workflows via HTTP") return "Workflows via HTTP isn't simulated in Vyomi yet — choose another target type.";
  if (s.targetType === "HTTP" && !/^https?:\/\/[^\s/]+/.test(s.httpUrl)) return "Enter a valid http(s) URL.";
  if (s.targetType === "Pub/Sub" && !s.pubsubTopic) return "Select a Cloud Pub/Sub topic.";
  if (s.targetType === "App Engine HTTP" && !s.aeUrl) return "Enter a relative URL.";
  return null;
}

export function ScheduleFields({ s, set, editing }) {
  const tz = timezones();
  return (
    <>
      <TextField label="Name" required value={s.name} disabled={editing} onChange={(e) => set({ ...s, name: e.target.value.trim() })}
        sx={{ maxWidth: 420 }} helperText={editing ? undefined : "Letters, numbers, hyphens and underscores."} />
      <FormControl sx={{ maxWidth: 420 }}>
        <InputLabel id="region-l">Region</InputLabel>
        <Select labelId="region-l" label="Region" value={s.region} disabled={editing} onChange={(e) => set({ ...s, region: e.target.value })}>
          {LOCATIONS.map((r) => <MenuItem key={r} value={r}>{r}</MenuItem>)}
        </Select>
      </FormControl>
      <TextField label="Description" value={s.description} onChange={(e) => set({ ...s, description: e.target.value })} sx={{ maxWidth: 560 }} />
      <TextField label="Frequency" required value={s.schedule} onChange={(e) => set({ ...s, schedule: e.target.value })}
        helperText="unix-cron format, e.g. 0 * * * *" sx={{ maxWidth: 420 }} />
      <FormControl sx={{ maxWidth: 420 }}>
        <InputLabel id="tz-l">Timezone</InputLabel>
        <Select labelId="tz-l" label="Timezone" value={s.timeZone} onChange={(e) => set({ ...s, timeZone: e.target.value })} MenuProps={{ PaperProps: { sx: { maxHeight: 420 } } }}>
          {tz.map((z) => <MenuItem key={z} value={z}>{z}</MenuItem>)}
        </Select>
      </FormControl>
    </>
  );
}

function HeaderRows({ s, set }) {
  return (
    <Box>
      <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>HTTP headers</Typography>
      <Stack spacing={1}>
        {s.headers.map((h, i) => (
          <Stack key={i} direction="row" spacing={1} alignItems="center">
            <TextField label="Name" value={h.key} onChange={(e) => set({ ...s, headers: s.headers.map((x, j) => j === i ? { ...x, key: e.target.value } : x) })} />
            <TextField label="Value" value={h.value} onChange={(e) => set({ ...s, headers: s.headers.map((x, j) => j === i ? { ...x, value: e.target.value } : x) })} />
            <IconButton aria-label={`Delete header ${i + 1}`} onClick={() => set({ ...s, headers: s.headers.filter((_, j) => j !== i) })}><DeleteIcon fontSize="small" /></IconButton>
          </Stack>
        ))}
        <Box><Button startIcon={<AddIcon />} onClick={() => set({ ...s, headers: [...s.headers, { key: "", value: "" }] })}>Add a header</Button></Box>
      </Stack>
    </Box>
  );
}

function useTopics() {
  return useAsync(async () => {
    const r = await restJson("GET", `/v1/projects/${encodeURIComponent(getProject())}/topics`);
    return r.topics || [];
  }, []);
}

export function TargetFields({ s, set }) {
  const topics = useTopics();
  return (
    <>
      <FormControl sx={{ maxWidth: 420 }}>
        <InputLabel id="tt-l">Target type</InputLabel>
        <Select labelId="tt-l" label="Target type" value={s.targetType} onChange={(e) => set({ ...s, targetType: e.target.value })}>
          {TARGET_TYPES.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
        </Select>
      </FormControl>

      {s.targetType === "HTTP" && (
        <>
          <TextField label="URL" required value={s.httpUrl} onChange={(e) => set({ ...s, httpUrl: e.target.value })} sx={{ maxWidth: 560 }} placeholder="https://example.com/handler" />
          <FormControl sx={{ maxWidth: 240 }}>
            <InputLabel id="hm-l">HTTP method</InputLabel>
            <Select labelId="hm-l" label="HTTP method" value={s.httpMethod} onChange={(e) => set({ ...s, httpMethod: e.target.value })}>
              {HTTP_METHODS.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
            </Select>
          </FormControl>
          <HeaderRows s={s} set={set} />
          <TextField label="Body" value={s.body} onChange={(e) => set({ ...s, body: e.target.value })} multiline minRows={3} sx={{ maxWidth: 560 }}
            disabled={["GET", "HEAD"].includes(s.httpMethod)} helperText={["GET", "HEAD"].includes(s.httpMethod) ? `${s.httpMethod} requests can't have a body.` : " "} />
          <FormControl sx={{ maxWidth: 280 }}>
            <InputLabel id="auth-l">Auth header</InputLabel>
            <Select labelId="auth-l" label="Auth header" value={s.auth} onChange={(e) => set({ ...s, auth: e.target.value })}>
              {["None", "Add OAuth token", "Add OIDC token"].map((a) => <MenuItem key={a} value={a}>{a}</MenuItem>)}
            </Select>
          </FormControl>
          {s.auth !== "None" && (
            <Stack direction="row" spacing={1}>
              <TextField label="Service account" value={s.serviceAccount} onChange={(e) => set({ ...s, serviceAccount: e.target.value })}
                placeholder="app@project.iam.gserviceaccount.com" sx={{ minWidth: 320 }} />
              {s.auth === "Add OIDC token" && <TextField label="Audience (optional)" value={s.audience} onChange={(e) => set({ ...s, audience: e.target.value })} sx={{ minWidth: 240 }} />}
            </Stack>
          )}
        </>
      )}

      {s.targetType === "Pub/Sub" && (
        <>
          <FormControl sx={{ maxWidth: 420 }}>
            <InputLabel id="topic-l">Select a Cloud Pub/Sub topic</InputLabel>
            <Select labelId="topic-l" label="Select a Cloud Pub/Sub topic" value={s.pubsubTopic} onChange={(e) => set({ ...s, pubsubTopic: e.target.value })}>
              {(topics.data || []).map((t) => <MenuItem key={t.name} value={t.name}>{t.name}</MenuItem>)}
            </Select>
            {!topics.loading && !(topics.data || []).length && <FormHelperText>No topics in this project. Create one in Pub/Sub first.</FormHelperText>}
          </FormControl>
          <TextField label="Message body" value={s.pubsubMessage} onChange={(e) => set({ ...s, pubsubMessage: e.target.value })} multiline minRows={3} sx={{ maxWidth: 560 }} />
        </>
      )}

      {s.targetType === "App Engine HTTP" && (
        <>
          <TextField label="URL" required value={s.aeUrl} onChange={(e) => set({ ...s, aeUrl: e.target.value })} sx={{ maxWidth: 560 }} helperText="Relative to the App Engine default service, e.g. /tasks/run" />
          <FormControl sx={{ maxWidth: 240 }}>
            <InputLabel id="aem-l">HTTP method</InputLabel>
            <Select labelId="aem-l" label="HTTP method" value={s.aeMethod} onChange={(e) => set({ ...s, aeMethod: e.target.value })}>
              {HTTP_METHODS.map((m) => <MenuItem key={m} value={m}>{m}</MenuItem>)}
            </Select>
          </FormControl>
          <HeaderRows s={s} set={set} />
          <TextField label="Body" value={s.body} onChange={(e) => set({ ...s, body: e.target.value })} multiline minRows={3} sx={{ maxWidth: 560 }}
            disabled={["GET", "HEAD"].includes(s.aeMethod)} />
        </>
      )}

      {s.targetType === "Workflows via HTTP" && (
        <NotSimulated compact feature="Workflows via HTTP" note="Workflows isn't a Vyomi product yet, so there is nothing for this target to call. Choose HTTP, Pub/Sub or App Engine HTTP instead." />
      )}
    </>
  );
}

function DurationField({ label, value, onChange, help }) {
  return (
    <Stack direction="row" spacing={1} alignItems="flex-start">
      <TextField label={label} type="number" value={value.n} onChange={(e) => onChange({ ...value, n: e.target.value })} helperText={help || " "} sx={{ width: 180 }} />
      <FormControl sx={{ width: 140, mt: 0 }}>
        <InputLabel id={`${label}-u`}>Unit</InputLabel>
        <Select labelId={`${label}-u`} label="Unit" value={value.unit} onChange={(e) => onChange({ ...value, unit: e.target.value })}>
          {DURATION_UNITS.map(([u, l]) => <MenuItem key={u} value={u}>{l}</MenuItem>)}
        </Select>
      </FormControl>
    </Stack>
  );
}

export function RetryFields({ s, set }) {
  return (
    <>
      <TextField label="Max retry attempts" type="number" value={s.retryCount} onChange={(e) => set({ ...s, retryCount: e.target.value })}
        helperText="0-5" inputProps={{ min: 0, max: 5 }} sx={{ width: 200 }} />
      <DurationField label="Max retry duration" value={s.maxRetryDuration} onChange={(v) => set({ ...s, maxRetryDuration: v })} help="0 = retry forever" />
      <DurationField label="Min backoff duration" value={s.minBackoff} onChange={(v) => set({ ...s, minBackoff: v })} />
      <DurationField label="Max backoff duration" value={s.maxBackoff} onChange={(v) => set({ ...s, maxBackoff: v })} />
      <TextField label="Max doublings" type="number" value={s.maxDoublings} onChange={(e) => set({ ...s, maxDoublings: e.target.value })} sx={{ width: 200 }} />
      <DurationField label="Attempt deadline config" value={s.attemptDeadline} onChange={(v) => set({ ...s, attemptDeadline: v })} help="15s-30m" />
    </>
  );
}
