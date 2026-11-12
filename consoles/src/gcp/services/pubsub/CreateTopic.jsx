/* Create a topic — the console's side-panel form. Every real setting goes into ONE
 * native topics.create body; ingestion (Cloud Storage source) and message transforms
 * (a documented JS subset) are REAL, enforced by core/gcp_pubsub_core.py — see
 * core/capabilities/gcp/pubsub.json. */
import { useState } from "react";
import {
  Box, Button, Checkbox, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem,
  Radio, RadioGroup, Select, Stack, TextField, Typography,
} from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";

const TRANSFORM_PLACEHOLDER = `function transform(message, metadata) {
  const data = JSON.parse(message.data);
  // mutate data, or "return null;" to drop the message
  message.data = JSON.stringify(data);
  return message;
}`;

export default function CreateTopic() {
  const notify = useNotify();
  const schemas = useAsync(() => api.listSchemas(), []);
  const [id, setId] = useState("");
  const [touched, setTouched] = useState(false);
  const [defaultSub, setDefaultSub] = useState(true);
  const [useSchema, setUseSchema] = useState(false);
  const [schema, setSchema] = useState("");
  const [encoding, setEncoding] = useState("JSON");
  const [retention, setRetention] = useState(false);
  const [retDays, setRetDays] = useState("7");
  const [encType, setEncType] = useState("google");
  const [kmsKey, setKmsKey] = useState("");
  const [ingest, setIngest] = useState(false);
  const [ingestBucket, setIngestBucket] = useState("");
  const [transform, setTransform] = useState(false);
  const [transformCode, setTransformCode] = useState(TRANSFORM_PLACEHOLDER);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const idErr = touched && !api.validId(id) ? "Topic ID must start with a letter and may contain letters, numbers, dashes, dots, underscores, tildes, plus and percent signs." : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (!api.validId(id)) return;
    setBusy(true); setError(null);
    try {
      const body = {};
      if (useSchema && schema) body.schemaSettings = { schema, encoding };
      if (retention) body.messageRetentionDuration = `${Number(retDays) * 86400}s`;
      if (encType === "kms" && kmsKey) body.kmsKeyName = kmsKey;
      if (ingest && ingestBucket.trim()) body.ingestionDataSourceSettings = { cloudStorage: { bucket: ingestBucket.trim() } };
      if (transform && transformCode.trim()) body.messageTransforms = [{ javascriptUdf: { functionName: "transform", code: transformCode } }];
      await api.createTopic(id, body);
      if (defaultSub) {
        try { await api.createSubscription(`${id}-sub`, { topic: api.topicName(id) }); }
        catch (e) { notify.error(e, "Topic created, but the default subscription failed"); }
      }
      notify.success(`Created topic "${id}"`);
      location.hash = hashHref("pubsub", "topics", id).slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 720 }}>
      <PageHeader title="Create topic" back={<IconButton aria-label="Back" href="#/pubsub/topics"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create topic" />

      <Section title="Topic">
        <Stack spacing={2.5}>
          <TextField label="Topic ID" required autoFocus value={id} onChange={(e) => setId(e.target.value.trim())} onBlur={() => setTouched(true)}
            error={!!idErr} helperText={idErr || `Topic name: projects/${"{project}"}/topics/${id || "{topic-id}"}`} sx={{ maxWidth: 480 }} />

          <FormControlLabel control={<Checkbox checked={defaultSub} onChange={(e) => setDefaultSub(e.target.checked)} />} label="Add a default subscription" />

          <Box>
            <FormControlLabel control={<Checkbox checked={useSchema} onChange={(e) => setUseSchema(e.target.checked)} />} label="Use a schema" />
            {useSchema && (
              <Stack direction="row" spacing={2} sx={{ mt: 1, pl: 4 }}>
                <FormControl sx={{ minWidth: 260 }}>
                  <InputLabel id="schema-l">Schema</InputLabel>
                  <Select labelId="schema-l" label="Schema" value={schema} onChange={(e) => setSchema(e.target.value)}>
                    {(schemas.data || []).map((s) => <MenuItem key={s.name} value={s.name}>{api.shortId(s.name)}</MenuItem>)}
                  </Select>
                </FormControl>
                <FormControl sx={{ minWidth: 160 }}>
                  <InputLabel id="enc-l">Encoding</InputLabel>
                  <Select labelId="enc-l" label="Encoding" value={encoding} onChange={(e) => setEncoding(e.target.value)}>
                    <MenuItem value="JSON">JSON</MenuItem>
                    <MenuItem value="BINARY">Binary</MenuItem>
                  </Select>
                </FormControl>
              </Stack>
            )}
          </Box>

          <Box>
            <Stack direction="row" spacing={1} alignItems="center">
              <FormControlLabel control={<Checkbox checked={ingest} onChange={(e) => setIngest(e.target.checked)} />} label="Enable ingestion" />
              <CapabilityBadge id="gcp.pubsub.topics.ingestion" />
            </Stack>
            {ingest && (
              <TextField sx={{ mt: 1, ml: 4, width: 420 }} label="Cloud Storage bucket" value={ingestBucket}
                onChange={(e) => setIngestBucket(e.target.value)} placeholder="my-bucket"
                helperText="Objects already in the bucket, and any added later, are ingested as messages the next time this topic is read, published to, or pulled from. AWS Kinesis, Azure Event Hubs, Kafka and CDC sources have no connector in Vyomi." />
            )}
          </Box>

          <Box>
            <FormControlLabel control={<Checkbox checked={retention} onChange={(e) => setRetention(e.target.checked)} />} label="Enable message retention" />
            {retention && (
              <TextField sx={{ mt: 1, ml: 4, width: 220 }} type="number" label="Message retention duration" value={retDays}
                onChange={(e) => setRetDays(e.target.value)} helperText="Days" inputProps={{ min: 1, max: 31 }} />
            )}
          </Box>

          <Box>
            <Stack direction="row" spacing={1} alignItems="center">
              <FormControlLabel control={<Checkbox checked={transform} onChange={(e) => setTransform(e.target.checked)} />} label="Enable message transforms" />
              <CapabilityBadge id="gcp.pubsub.topics.message-transforms" />
            </Stack>
            {transform && (
              <TextField sx={{ mt: 1, ml: 4, width: 560 }} label="JavaScript UDF code" value={transformCode}
                onChange={(e) => setTransformCode(e.target.value)} multiline minRows={6} InputProps={{ sx: { fontFamily: "monospace", fontSize: 13 } }}
                helperText="A documented subset of JavaScript is really parsed and run on every publish — see the badge for exactly what's covered. Returning null drops the message." />
            )}
          </Box>

          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Encryption</Typography>
            <RadioGroup value={encType} onChange={(e) => setEncType(e.target.value)} aria-label="Encryption">
              <FormControlLabel value="google" control={<Radio size="small" />} label="Google-managed encryption key" />
              <FormControlLabel value="kms" control={<Radio size="small" />} label="Cloud KMS key" />
            </RadioGroup>
            {encType === "kms" && (
              <TextField sx={{ mt: 1, ml: 4, width: 440 }} label="Cloud KMS key" value={kmsKey} onChange={(e) => setKmsKey(e.target.value)}
                placeholder="projects/p/locations/g/keyRings/r/cryptoKeys/k"
                helperText="Stored and returned as configured; Vyomi does not call Cloud KMS to encrypt message data." />
            )}
          </Box>
        </Stack>
      </Section>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create"}</Button>
        <Button href="#/pubsub/topics">Cancel</Button>
      </Stack>
    </Box>
  );
}
