/* Create a database on an instance. */
import { useState } from "react";
import { Box, Button, FormControl, InputLabel, MenuItem, Select, Stack, TextField } from "@mui/material";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function CreateDatabase({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [db, setDb] = useState("");
  const [charset, setCharset] = useState("UTF8");
  const [collation, setCollation] = useState("Default collation");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (ev) => {
    ev.preventDefault();
    if (!db) return;
    setBusy(true); setError(null);
    try {
      await api.insertDatabase(name, { name: db, charset, collation: collation === "Default collation" ? "en_US.UTF8" : collation });
      notify.success(`Created database "${db}"`);
      location.hash = `#/sql/instances/${encodeURIComponent(name)}/databases`;
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 560 }}>
      <PageHeader title="Create a database" />
      <ErrorAlert error={error} title="Failed to create database" />
      <Section title="Database">
        <Stack spacing={2.5}>
          <TextField label="Database name" required value={db} onChange={(e) => setDb(e.target.value.trim())} />
          <FormControl>
            <InputLabel id="cd-charset">Character set</InputLabel>
            <Select labelId="cd-charset" label="Character set" value={charset} onChange={(e) => setCharset(e.target.value)}>
              <MenuItem value="UTF8">UTF8</MenuItem>
              <MenuItem value="LATIN1">LATIN1</MenuItem>
            </Select>
          </FormControl>
          <FormControl>
            <InputLabel id="cd-collation">Collation</InputLabel>
            <Select labelId="cd-collation" label="Collation" value={collation} onChange={(e) => setCollation(e.target.value)}>
              <MenuItem value="Default collation">Default collation</MenuItem>
              <MenuItem value="en_US.UTF8">en_US.UTF8</MenuItem>
            </Select>
          </FormControl>
        </Stack>
      </Section>
      <Stack direction="row" spacing={1} sx={{ pt: 2.5 }}>
        <Button type="submit" variant="contained" disabled={busy || !db}>{busy ? "Creating…" : "Create"}</Button>
        <Button href={`#/sql/instances/${encodeURIComponent(name)}/databases`}>Cancel</Button>
      </Stack>
    </Box>
  );
}
