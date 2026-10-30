/* "Select a project" dialog. Vyomi has no Resource Manager backend: a project here is the
 * project ID the console passes on project-scoped API calls. Said so in the dialog. */
import { useState } from "react";
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Radio, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, TextField,
} from "@mui/material";
import { knownProjects, setProject } from "../project.js";
import { NotSimulated } from "../kit/common.jsx";

const VALID = /^[a-z][a-z0-9-]{4,28}[a-z0-9]$/;

export default function ProjectPicker({ open, onClose, project }) {
  const [sel, setSel] = useState(project);
  const [q, setQ] = useState("");
  const [add, setAdd] = useState("");
  const list = knownProjects().filter((p) => p.includes(q.trim().toLowerCase()));
  const open_ = (p) => { setProject(p); onClose(); };
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth aria-labelledby="pp-title">
      <DialogTitle id="pp-title">Select a project</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <TextField placeholder="Search projects and folders" value={q} onChange={(e) => setQ(e.target.value)} inputProps={{ "aria-label": "Search projects" }} />
          <Table size="small">
            <TableHead><TableRow><TableCell padding="checkbox" /><TableCell>Name</TableCell><TableCell>ID</TableCell></TableRow></TableHead>
            <TableBody>
              {list.map((p) => (
                <TableRow key={p} hover selected={p === sel} onClick={() => setSel(p)} onDoubleClick={() => open_(p)} sx={{ cursor: "pointer" }}>
                  <TableCell padding="checkbox"><Radio size="small" checked={p === sel} inputProps={{ "aria-label": p }} /></TableCell>
                  <TableCell>{p}</TableCell>
                  <TableCell>{p}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Stack direction="row" spacing={1} alignItems="flex-start">
            <TextField label="Use another project ID" value={add} onChange={(e) => setAdd(e.target.value.trim())}
              error={!!add && !VALID.test(add)} helperText={add && !VALID.test(add) ? "6–30 characters: lowercase letters, digits, hyphens; start with a letter." : " "} />
            <Button variant="outlined" disabled={!VALID.test(add)} onClick={() => open_(add)}>Open</Button>
          </Stack>
          <Alert severity="info" variant="outlined">
            Vyomi uses the project ID on project-scoped API calls. Bucket names are global, as in Cloud Storage, so buckets created under any project ID are listed here.
          </Alert>
          <NotSimulated compact feature="Creating projects and folders (Resource Manager)" />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={() => open_(sel)}>Open</Button>
      </DialogActions>
    </Dialog>
  );
}
