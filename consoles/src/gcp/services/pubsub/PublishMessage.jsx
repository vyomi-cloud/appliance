/* Publish message — one real topics.publish call. "Number of messages" sends that many
 * copies of the same body/attributes/ordering key, same as the native console. */
import { useState } from "react";
import { Box, Button, IconButton, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function PublishMessage({ params }) {
  const id = params.name;
  const notify = useNotify();
  const [count, setCount] = useState("1");
  const [bodyText, setBodyText] = useState("");
  const [attrs, setAttrs] = useState([]);
  const [orderingKey, setOrderingKey] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const bodyErr = touched && !bodyText.trim() ? "Message body is required." : null;

  const submit = async (ev) => {
    ev.preventDefault();
    setTouched(true);
    if (!bodyText.trim()) return;
    setBusy(true); setError(null);
    try {
      const n = Math.max(1, Number(count) || 1);
      const attributes = Object.fromEntries(attrs.filter((a) => a.key).map((a) => [a.key, a.value]));
      const data = api.encode(bodyText);
      const messages = Array.from({ length: n }, () => ({ data, attributes, ...(orderingKey ? { orderingKey } : {}) }));
      const r = await api.publish(id, messages);
      const now = new Date().toISOString();
      api.recordSentMessages(id, r.messageIds.map((messageId) => ({ messageId, publishTime: now, attributes, data, orderingKey })));
      notify.success(`Published ${n} message${n === 1 ? "" : "s"} to "${id}"`);
      location.hash = `/pubsub/topics/${encodeURIComponent(id)}`;
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 680 }}>
      <PageHeader title="Publish message" back={<IconButton aria-label="Back" href={`#/pubsub/topics/${encodeURIComponent(id)}`}><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to publish message" />

      <Section title="Message">
        <Stack spacing={2.5}>
          <TextField label="Number of messages" type="number" value={count} onChange={(e) => setCount(e.target.value)} inputProps={{ min: 1 }} sx={{ width: 220 }} />
          <TextField label="Message body" required multiline minRows={4} value={bodyText} onChange={(e) => setBodyText(e.target.value)} onBlur={() => setTouched(true)}
            error={!!bodyErr} helperText={bodyErr || " "} />
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Message attributes</Typography>
            <Stack spacing={1}>
              {attrs.map((a, i) => (
                <Stack key={i} direction="row" spacing={1} alignItems="center">
                  <TextField label="Key" value={a.key} onChange={(e) => setAttrs(attrs.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
                  <TextField label="Value" value={a.value} onChange={(e) => setAttrs(attrs.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
                  <IconButton aria-label={`Delete attribute ${i + 1}`} onClick={() => setAttrs(attrs.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
                </Stack>
              ))}
              <Box><Button startIcon={<AddIcon />} onClick={() => setAttrs([...attrs, { key: "", value: "" }])}>Add an attribute</Button></Box>
            </Stack>
          </Box>
          <TextField label="Ordering key" value={orderingKey} onChange={(e) => setOrderingKey(e.target.value)} sx={{ maxWidth: 360 }}
            helperText="Requires message ordering to be enabled on the subscription." />
        </Stack>
      </Section>

      <Stack direction="row" spacing={1} sx={{ pt: 3 }}>
        <Button type="submit" variant="contained" disabled={busy}>{busy ? "Publishing…" : "Publish"}</Button>
        <Button href={`#/pubsub/topics/${encodeURIComponent(id)}`}>Cancel</Button>
      </Stack>
    </Box>
  );
}
