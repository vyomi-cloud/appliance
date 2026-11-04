/* Project labels — native Resource Manager v3 PatchProject({labels}). */
import { useEffect, useState } from "react";
import { Button, IconButton, Stack, TextField } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import DeleteIcon from "@mui/icons-material/esm/Delete.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Labels() {
  const project = useAsync(() => api.getProjectMeta(), []);
  const notify = useNotify();
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!project.data) return;
    const entries = Object.entries(project.data.labels || {}).map(([key, value]) => ({ key, value }));
    setRows(entries.length ? entries : [{ key: "", value: "" }]);
  }, [project.data]);

  const save = async () => {
    setBusy(true);
    try {
      await api.patchProjectMeta({ labels: Object.fromEntries(rows.filter((r) => r.key).map((r) => [r.key, r.value])) });
      notify.success("Saved labels"); project.reload();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <>
      <PageHeader title="Labels" />
      <ErrorAlert error={project.error} title="Failed to load labels" />
      <Section title="Labels" actions={
        <Stack direction="row" spacing={1}>
          <Button disabled={busy} onClick={() => setRows([...rows, { key: "", value: "" }])} startIcon={<AddIcon />}>Add label</Button>
          <Button variant="contained" disabled={busy} onClick={save}>Save</Button>
          <Button disabled={busy} onClick={() => setRows(Object.entries(project.data?.labels || {}).map(([key, value]) => ({ key, value })))}>Discard changes</Button>
        </Stack>}>
        <Stack spacing={1.5}>
          {rows.map((r, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField label="Key" inputProps={{ "aria-label": `Key ${i + 1}` }} value={r.key} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
              <TextField label="Value" inputProps={{ "aria-label": `Value ${i + 1}` }} value={r.value} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
              <IconButton aria-label={`Delete label ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))}><DeleteIcon fontSize="small" /></IconButton>
            </Stack>
          ))}
        </Stack>
      </Section>
    </>
  );
}
