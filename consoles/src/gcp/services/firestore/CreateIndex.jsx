/* Create a composite index — collection, one or more field paths with index options, and
 * a query scope, in one native collectionGroups.indexes.create call. */
import { useState } from "react";
import { Box, Button, FormControl, FormControlLabel, IconButton, InputLabel, MenuItem, Radio, RadioGroup, Select, Stack, TextField, Typography } from "@mui/material";
import ArrowBackIcon from "@mui/icons-material/esm/ArrowBack.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import * as api from "./api.js";

const OPTIONS = ["Ascending", "Descending", "Arrays"];

export default function CreateIndex({ params }) {
  const db = params.name;
  const notify = useNotify();
  const [collectionId, setCollectionId] = useState("");
  const [scope, setScope] = useState("COLLECTION");
  const [rows, setRows] = useState([{ path: "", option: "Ascending" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const back = `#/firestore/databases/${encodeURIComponent(db)}/indexes`;
  const valid = collectionId.trim() && rows.every((r) => r.path.trim());

  const submit = async (ev) => {
    ev.preventDefault();
    if (!valid) return;
    setBusy(true); setError(null);
    try {
      const fields = rows.map((r) => r.option === "Arrays"
        ? { fieldPath: r.path, arrayConfig: "CONTAINS" }
        : { fieldPath: r.path, order: r.option.toUpperCase() });
      await api.createIndex(db, collectionId.trim(), { queryScope: scope, fields });
      notify.success(`Created index for "${collectionId}"`);
      location.hash = back.slice(1);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  return (
    <Box component="form" onSubmit={submit} noValidate sx={{ maxWidth: 720 }}>
      <PageHeader title="Create a composite index" back={<IconButton aria-label="Back" href={back}><ArrowBackIcon /></IconButton>} />
      <ErrorAlert error={error} title="Failed to create index" />
      <Stack spacing={2.5}>
        <Typography variant="h3" component="h2">Index</Typography>
        <TextField label="Collection ID" required value={collectionId} onChange={(e) => setCollectionId(e.target.value.trim())} inputProps={{ "aria-label": "Collection ID" }} sx={{ maxWidth: 420 }} />
        {rows.map((r, i) => (
          <Stack key={i} direction="row" spacing={1} alignItems="center">
            <TextField label="Field path" required value={r.path} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, path: e.target.value.trim() } : x))} />
            <FormControl sx={{ width: 180 }}>
              <InputLabel id={`opt-${i}`}>Index options</InputLabel>
              <Select labelId={`opt-${i}`} label="Index options" value={r.option} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, option: e.target.value } : x))}>
                {OPTIONS.map((o) => <MenuItem key={o} value={o}>{o}</MenuItem>)}
              </Select>
            </FormControl>
            {rows.length > 1 && <IconButton aria-label={`Remove field ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>}
          </Stack>
        ))}
        <Box><Button startIcon={<AddIcon />} onClick={() => setRows([...rows, { path: "", option: "Ascending" }])}>Add field</Button></Box>
        <Typography variant="body2" sx={{ fontWeight: 500 }}>Query scope</Typography>
        <RadioGroup value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Query scope">
          <FormControlLabel value="COLLECTION" control={<Radio size="small" />} label="Collection" />
          <FormControlLabel value="COLLECTION_GROUP" control={<Radio size="small" />} label="Collection group" />
        </RadioGroup>
        <Stack direction="row" spacing={1}>
          <Button type="submit" variant="contained" disabled={busy || !valid}>{busy ? "Creating…" : "Create"}</Button>
          <Button href={back}>Cancel</Button>
        </Stack>
      </Stack>
    </Box>
  );
}
