/* Create a subscription — one native subscriptions.create body. Push/dead-lettering/retry/
 * ordering/filter are all real (stored + enforced where Vyomi can — see the capability
 * badges); BigQuery/Cloud Storage delivery isn't a Vyomi product, so it's a declared gap. */
import { useState } from "react";
import {
  Box, Button, Checkbox, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { ErrorAlert, NotSimulated, PageHeader, Section } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";

function queryParam(name) {
  const m = new URLSearchParams((location.hash.split("?")[1] || "")).get(name);
  return m || "";
}

export default function CreateSubscription() {
  const notify = useNotify();
  const topics = useAsync(() => api.listTopics(), []);
  const [id, setId] = useState("");
  const [topic, setTopic] = useState(() => (queryParam("topic") ? api.topicName(queryParam("topic")) : ""));
  const [touched, setTouched] = useState(false);

  const [delivery, setDelivery] = useState("Pull");
  const [endpoint, setEndpoint] = useState("");

  const [retDays, setRetDays] = useState("7");
  const [retainAcked, setRetainAcked] = useState(false);

  const [expireMode, setExpireMode] = useState("days");
  const [expireDays, setExpireDays] = useState("31");

  const [ackDeadline, setAckDeadline] = useState("10");

  const [exactlyOnce, setExactlyOnce] = useState(false);
  const [ordering, setOrdering] = useState(false);

  const [dlqEnabled, setDlqEnabled] = useState(false);
  const [dlqTopic, setDlqTopic] = useState("");
  const [maxAttempts, setMaxAttempts] = useState("5");

  const [retryMode, setRetryMode] = useState("immediate");

  const [filter, setFilter] = useState("");

  const [labels, setLabels] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const idErr = touched && !api.validId(id) ? "Subscription ID must start with a letter and may contain letters, numbers, dashes, dots, underscores, tildes, plus and percent signs." : null;
  const topicErr = touched && !topic ? "Select a topic." : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (!api.validId(id) || !topic) return;
    setBusy(true); setError(null);
    try {
      const body = {
        topic,
        ackDeadlineSeconds: Number(ackDeadline) || 10,
        messageRetentionDuration: `${Number(retDays) * 86400}s`,
        retainAckedMessages: retainAcked,
        expirationPolicy: expireMode === "never" ? {} : { ttl: `${Number(expireDays) * 86400}s` },
        enableMessageOrdering: ordering,
        enableExactlyOnceDelivery: exactlyOnce,
        pushConfig: delivery === "Push" && endpoint ? { pushEndpoint: endpoint } : {},
        ...(labels.length ? { labels: Object.fromEntries(labels.filter((l) => l.key).map((l) => [l.key, l.value])) } : {}),
        ...(dlqEnabled && dlqTopic ? { deadLetterPolicy: { deadLetterTopic: dlqTopic, maxDeliveryAttempts: Number(maxAttempts) || 5 } } : {}),
        ...(retryMode === "backoff" ? { retryPolicy: { minimumBackoff: "10s", maximumBackoff: "600s" } } : {}),
        ...(filter.trim() ? { filter: filter.trim() } : {}),
      };
      await api.createSubscription(id, body);
      notify.success(`Created subscription "${id}"`);
      location.hash = hashHref("pubsub", "subscriptions", id).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 760 }}>
      <PageHeader title="Create subscription" back={<IconButton aria-label="Back" href="#/pubsub/subscriptions"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create subscription" />

      <Section title="Subscription">
        <Stack spacing={2.5}>
          <TextField label="Subscription ID" required autoFocus value={id} onChange={(e) => setId(e.target.value.trim())} onBlur={() => setTouched(true)}
            error={!!idErr} helperText={idErr || " "} sx={{ maxWidth: 480 }} />
          <FormControl sx={{ maxWidth: 480 }} error={!!topicErr}>
            <InputLabel id="topic-l">Select a Cloud Pub/Sub topic</InputLabel>
            <Select labelId="topic-l" label="Select a Cloud Pub/Sub topic" value={topic} onChange={(e) => setTopic(e.target.value)} onBlur={() => setTouched(true)}>
              {(topics.data || []).map((t) => <MenuItem key={t.name} value={t.name}>{api.shortId(t.name)}</MenuItem>)}
            </Select>
          </FormControl>
        </Stack>
      </Section>

      <Section title="Delivery type">
        <Stack spacing={2}>
          <RadioGroup row value={delivery} onChange={(e) => setDelivery(e.target.value)} aria-label="Delivery type">
            <FormControlLabel value="Pull" control={<Radio size="small" />} label="Pull" />
            <FormControlLabel value="Push" control={<Radio size="small" />} label="Push" />
          </RadioGroup>
          {delivery === "Push" && (
            <TextField label="Endpoint URL" value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="https://example.com/push"
              helperText="Stored and returned as configured; Vyomi never makes the outbound call. Use Pull to receive messages in Vyomi." sx={{ maxWidth: 480 }} />
          )}
          <NotSimulated compact feature="Write to BigQuery / Write to Cloud Storage delivery" note="BigQuery and Cloud Storage aren't Vyomi products yet." />
        </Stack>
      </Section>

      <Section title="Message retention duration">
        <Stack spacing={2}>
          <TextField label="Message retention duration" type="number" value={retDays} onChange={(e) => setRetDays(e.target.value)} helperText="Days" sx={{ width: 220 }} />
          <FormControlLabel control={<Checkbox checked={retainAcked} onChange={(e) => setRetainAcked(e.target.checked)} />} label="Retain acknowledged messages" />
        </Stack>
      </Section>

      <Section title="Expiration period">
        <Stack spacing={2}>
          <RadioGroup value={expireMode} onChange={(e) => setExpireMode(e.target.value)} aria-label="Expiration period">
            <FormControlLabel value="days" control={<Radio size="small" />} label="Expire after this many days of inactivity" />
            <FormControlLabel value="never" control={<Radio size="small" />} label="Never expire" />
          </RadioGroup>
          {expireMode === "days" && <TextField label="Days" type="number" value={expireDays} onChange={(e) => setExpireDays(e.target.value)} sx={{ width: 160 }} />}
        </Stack>
      </Section>

      <Section title="Acknowledgement deadline">
        <TextField label="Acknowledgement deadline" type="number" value={ackDeadline} onChange={(e) => setAckDeadline(e.target.value)}
          helperText="Seconds (10 - 600)" inputProps={{ min: 10, max: 600 }} sx={{ width: 220 }} />
      </Section>

      <Section title={<Stack direction="row" spacing={1} alignItems="center"><span>Subscription filter</span><CapabilityBadge id="gcp.pubsub.subscriptions.filter" /></Stack>}>
        <TextField label="Subscription filter" value={filter} onChange={(e) => setFilter(e.target.value)}
          placeholder='attributes.kind = "order" AND NOT attributes.test:"true"'
          helperText="Only messages matching this filter are delivered to the subscription. Leave blank to receive every message on the topic."
          sx={{ maxWidth: 560 }} />
      </Section>

      <Section title="Exactly once delivery">
        <FormControlLabel control={<Checkbox checked={exactlyOnce} onChange={(e) => setExactlyOnce(e.target.checked)} />} label="Enable exactly once delivery" />
      </Section>

      <Section title="Message ordering">
        <FormControlLabel control={<Checkbox checked={ordering} onChange={(e) => setOrdering(e.target.checked)} />} label="Order messages with an ordering key" />
      </Section>

      <Section title="Dead lettering">
        <Stack spacing={2}>
          <FormControlLabel control={<Checkbox checked={dlqEnabled} onChange={(e) => setDlqEnabled(e.target.checked)} />} label="Enable dead lettering" />
          {dlqEnabled && (
            <>
              <FormControl sx={{ maxWidth: 420 }}>
                <InputLabel id="dlt-l">Dead letter topic</InputLabel>
                <Select labelId="dlt-l" label="Dead letter topic" value={dlqTopic} onChange={(e) => setDlqTopic(e.target.value)}>
                  {(topics.data || []).map((t) => <MenuItem key={t.name} value={t.name}>{api.shortId(t.name)}</MenuItem>)}
                </Select>
              </FormControl>
              <TextField label="Maximum delivery attempts" type="number" value={maxAttempts} onChange={(e) => setMaxAttempts(e.target.value)}
                inputProps={{ min: 5, max: 100 }} sx={{ width: 240 }} />
            </>
          )}
        </Stack>
      </Section>

      <Section title="Retry policy">
        <RadioGroup value={retryMode} onChange={(e) => setRetryMode(e.target.value)} aria-label="Retry policy">
          <FormControlLabel value="immediate" control={<Radio size="small" />} label="Retry immediately" />
          <FormControlLabel value="backoff" control={<Radio size="small" />} label="Retry after exponential backoff delay" />
        </RadioGroup>
      </Section>

      <Section title="Labels">
        <Stack spacing={1}>
          {labels.map((l, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField label={`Key ${i + 1}`} value={l.key} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
              <TextField label={`Value ${i + 1}`} value={l.value} onChange={(e) => setLabels(labels.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
              <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setLabels(labels.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
          <Box><Button startIcon={<AddIcon />} onClick={() => setLabels([...labels, { key: "", value: "" }])}>Add label</Button></Box>
        </Stack>
      </Section>

      <Stack direction="row" spacing={1} sx={{ pt: 1 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/pubsub/subscriptions">Cancel</Button>
      </Stack>
    </Box>
  );
}
