/* Object enrichments: REAL local extraction on upload (core/gcp_enrich_core), results written to the object's custom
 * metadata under vyomi-enrich-*. Not Document AI: no ML classification or form parsing. */
import { useState } from "react";
import { Alert, Box, Button, Checkbox, Chip, FormControlLabel, FormGroup, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography, Dialog, DialogActions, DialogContent, DialogTitle } from "@mui/material";
import AddIcon from "@mui/icons-material/esm/Add.js";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { restJson } from "../../../common/wire.js";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

const e = encodeURIComponent;
const EXTRACTORS = [["metadata", "Size, SHA-256, detected type"], ["text", "Text, JSON and CSV facts"], ["image", "Image dimensions"], ["pdf", "PDF page count and title"], ["ocr", "Image text (OCR, needs tesseract on the host)"]];
const rulesOf = async (bucket) => (await restJson("GET", `/storage/v1/b/${e(bucket)}/vyomiEnrichmentRules`)).items || [];

export default function ObjectEnrichments() {
  const project = useProject();
  const notify = useNotify();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ bucket: "", id: "", prefix: "", suffix: "", ex: { metadata: true, text: true, image: true, pdf: true, ocr: false } });
  const { data, error, reload } = useAsync(async () => {
    const buckets = await api.listBuckets();
    const rules = (await Promise.all(buckets.map((b) => rulesOf(b.name)))).flat();
    return { buckets, rules };
  }, [project]);
  const d = data || { buckets: [], rules: [] };
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); reload(); } catch (x) { notify.error(x); } };
  const create = () => act(async () => {
    await restJson("POST", `/storage/v1/b/${e(f.bucket)}/vyomiEnrichmentRules`, { query: { ruleId: f.id }, body: { prefix: f.prefix, suffix: f.suffix, extractors: Object.keys(f.ex).filter((k) => f.ex[k]) } });
    setOpen(false);
  }, "Enrichment rule created");
  return (
    <Box sx={{ pt: 2 }}>
      <PageHeader title="Object enrichments" actions={<>
        <Button size="small" startIcon={<AddIcon />} disabled={!d.buckets.length} onClick={() => { setF({ ...f, bucket: f.bucket || d.buckets[0].name, id: "" }); setOpen(true); }}>Create rule</Button>
        <Button size="small" startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>} />
      <Stack spacing={2}>
        <Alert severity="info" icon={false} sx={{ py: 0.5 }}>
          Not in scope: Document AI classification and extraction models. Vyomi offers local extraction instead: when an object matching a rule is
          uploaded, Vyomi reads its bytes and writes size, hash, detected type, text/JSON/CSV facts, image dimensions, PDF page count and (if the host has
          tesseract) OCR text into the object's custom metadata as <code>vyomi-enrich-*</code> keys.
        </Alert>
        <ErrorAlert error={error} title="Could not load enrichment rules" />
        <Section title="Enrichment rules" actions={<CapabilityBadge id="gcp.storage.object-enrichments" />}>
          {d.rules.length === 0 ? <Typography variant="body2" color="text.secondary">No rules. Create one to enrich new uploads.</Typography> : (
            <Table size="small"><TableHead><TableRow><TableCell>Rule</TableCell><TableCell>Bucket</TableCell><TableCell>Match</TableCell><TableCell>Extractors</TableCell><TableCell>Objects processed</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
              <TableBody>{d.rules.map((r) => (
                <TableRow key={`${r.bucket}/${r.id}`}>
                  <TableCell>{r.id}</TableCell><TableCell>{r.bucket}</TableCell>
                  <TableCell>{r.prefix || r.suffix ? `${r.prefix}*${r.suffix}` : "all objects"}</TableCell>
                  <TableCell>{r.extractors.map((x) => <Chip key={x} size="small" label={x} sx={{ mr: 0.5 }} />)}</TableCell>
                  <TableCell>{r.processed}</TableCell>
                  <TableCell align="right"><Button size="small" color="error" onClick={() => act(() => restJson("DELETE", `/storage/v1/b/${e(r.bucket)}/vyomiEnrichmentRules/${e(r.id)}`), "Rule deleted")}>Delete</Button></TableCell>
                </TableRow>))}</TableBody></Table>)}
        </Section>
      </Stack>
      <Dialog open={open} onClose={() => setOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Create enrichment rule</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField select size="small" label="Bucket" value={f.bucket} onChange={(x) => setF({ ...f, bucket: x.target.value })}>{d.buckets.map((b) => <MenuItem key={b.name} value={b.name}>{b.name}</MenuItem>)}</TextField>
            <TextField size="small" label="Rule ID" value={f.id} onChange={(x) => setF({ ...f, id: x.target.value })} helperText="lowercase letters, digits, hyphens" />
            <Stack direction="row" spacing={2}>
              <TextField size="small" label="Object prefix (optional)" value={f.prefix} onChange={(x) => setF({ ...f, prefix: x.target.value })} />
              <TextField size="small" label="Object suffix (optional)" value={f.suffix} onChange={(x) => setF({ ...f, suffix: x.target.value })} />
            </Stack>
            <FormGroup>{EXTRACTORS.map(([k, label]) => (
              <FormControlLabel key={k} control={<Checkbox size="small" checked={!!f.ex[k]} onChange={(x) => setF({ ...f, ex: { ...f.ex, [k]: x.target.checked } })} />} label={label} />))}</FormGroup>
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="contained" disabled={!f.id || !f.bucket} onClick={create}>Create</Button></DialogActions>
      </Dialog>
    </Box>
  );
}
