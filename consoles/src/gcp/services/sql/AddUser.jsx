/* Add a user account to an instance. */
import { useState } from "react";
import { Box, Button, FormControlLabel, Radio, RadioGroup, Stack, TextField, Typography } from "@mui/material";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function AddUser({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [auth, setAuth] = useState("Built-in authentication");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [host, setHost] = useState("Allow any host (%)");
  const [hostIp, setHostIp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (ev) => {
    ev.preventDefault();
    if (!user) return;
    setBusy(true); setError(null);
    try {
      await api.insertUser(name, {
        name: user, password, host: host.startsWith("Allow") ? "%" : (hostIp || "%"),
        type: auth === "Cloud IAM" ? "CLOUD_IAM_USER" : "BUILT_IN",
      });
      notify.success(`Added user "${user}"`);
      location.hash = `#/sql/instances/${encodeURIComponent(name)}/users`;
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 720 }}>
      <PageHeader title={`Add a user account to instance ${name}`} />
      <ErrorAlert error={error} title="Failed to add user" />
      <Section title="User">
        <Stack spacing={2.5}>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Authentication</Typography>
            <RadioGroup value={auth} onChange={(e) => setAuth(e.target.value)} aria-label="Authentication">
              <FormControlLabel value="Built-in authentication" control={<Radio size="small" />} label="Built-in authentication" />
              <FormControlLabel value="Cloud IAM" control={<Radio size="small" />} label="Cloud IAM" />
            </RadioGroup>
          </Box>
          <TextField label="User name" required value={user} onChange={(e) => setUser(e.target.value.trim())} sx={{ maxWidth: 420 }} />
          {auth !== "Cloud IAM" && <TextField label="Password" required type="password" value={password} onChange={(e) => setPassword(e.target.value)} sx={{ maxWidth: 420 }} />}
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 500, mb: 1 }}>Host name</Typography>
            <RadioGroup value={host} onChange={(e) => setHost(e.target.value)} aria-label="Host name">
              <FormControlLabel value="Allow any host (%)" control={<Radio size="small" />} label="Allow any host (%)" />
              <FormControlLabel value="Restrict host by IP address or address range" control={<Radio size="small" />} label="Restrict host by IP address or address range" />
            </RadioGroup>
            {host.startsWith("Restrict") && <TextField sx={{ mt: 1, maxWidth: 300 }} label="Host" value={hostIp} onChange={(e) => setHostIp(e.target.value)} />}
          </Box>
        </Stack>
      </Section>
      <Stack direction="row" spacing={1} sx={{ pt: 2.5 }}>
        <Button type="submit" variant="contained" disabled={busy || !user}>{busy ? "Adding…" : "Add"}</Button>
        <Button href={`#/sql/instances/${encodeURIComponent(name)}/users`}>Cancel</Button>
      </Stack>
    </Box>
  );
}
