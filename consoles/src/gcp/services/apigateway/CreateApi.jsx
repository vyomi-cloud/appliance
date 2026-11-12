import { useState } from "react";
import { Box, Button, IconButton, Stack, TextField } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { hashHref } from "../../link.jsx";
import * as api from "./api.js";

export default function CreateApi() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [display, setDisplay] = useState("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = touched && !api.ID.test(name) ? "1-63 characters: lowercase letters, numbers and hyphens, starting with a letter." : null;
  const submit = async (ev) => {
    ev.preventDefault(); setTouched(true);
    if (!api.ID.test(name)) return;
    setBusy(true); setError(null);
    try { await api.createApi(name, display.trim() ? { displayName: display.trim() } : {}); notify.success(`Created API "${name}"`); location.hash = hashHref("apigateway", "apis", name).slice(1); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 720 }}>
      <PageHeader title="Create API" back={<IconButton aria-label="Back" href="#/apigateway/apis"><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create API" />
      <Stack spacing={2.5} sx={{ py: 2 }}>
        <TextField required label="API ID" value={name} onChange={(e) => setName(e.target.value.trim())} error={!!nameErr} helperText={nameErr || "Lowercase letters, numbers and hyphens"} />
        <TextField label="Display name" value={display} onChange={(e) => setDisplay(e.target.value)} />
      </Stack>
      <Stack direction="row" spacing={1}><Button type="submit" variant="contained" disabled={busy}>{busy ? "Creating…" : "Create API"}</Button><Button href="#/apigateway/apis">Cancel</Button></Stack>
    </Box>
  );
}
