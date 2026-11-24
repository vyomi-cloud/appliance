/* A preview's plan, as Infrastructure Manager shows it: what would be created / is already there / cannot be applied here. */
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { idOf } from "./api.js";

const ACTION = { create: ["+ create", "success"], unchanged: ["no change", "default"] };

export function PlanBody({ preview }) {
  if (!preview) return null;
  if (preview.state === "FAILED") return <Alert severity="error">{preview.errorStatus?.message || "Preview failed"}</Alert>;
  const plan = preview.vyomiPlan || { resources: [], unsupported: [], summary: {} };
  const s = plan.summary || {};
  return (
    <Stack spacing={1.5} data-testid="plan-body">
      <Typography>Plan: <b>{s.create || 0}</b> to create, <b>{s.unchanged || 0}</b> already present{s.unsupported ? <>, <b>{s.unsupported}</b> not applicable on this simulator</> : null}.</Typography>
      <Table size="small" aria-label="Planned resources">
        <TableHead><TableRow><TableCell>Resource</TableCell><TableCell>Type</TableCell><TableCell>Action</TableCell></TableRow></TableHead>
        <TableBody>
          {plan.resources.map((r) => (
            <TableRow key={r.address}><TableCell sx={{ fontFamily: "monospace" }}>{r.address}</TableCell><TableCell>{r.type}</TableCell>
              <TableCell><Chip size="small" label={ACTION[r.action]?.[0] || r.action} color={ACTION[r.action]?.[1] || "default"} variant={r.action === "create" ? "filled" : "outlined"} /></TableCell></TableRow>
          ))}
          {plan.unsupported.map((r) => (
            <TableRow key={r.address}><TableCell sx={{ fontFamily: "monospace" }}>{r.address}</TableCell><TableCell>{r.type}</TableCell>
              <TableCell><Chip size="small" color="warning" label="not applied" title={r.reason} /></TableCell></TableRow>
          ))}
        </TableBody>
      </Table>
      {plan.unsupported.length > 0 && <Alert severity="warning">Resources of these types are listed but not applied: the simulator applies buckets, Pub/Sub topics and subscriptions, and VPC networks, subnetworks and firewall rules.</Alert>}
    </Stack>
  );
}

export function PlanDialog({ preview, onClose }) {
  return (
    <Dialog open={!!preview} onClose={onClose} maxWidth="md" fullWidth aria-labelledby="plan-title">
      <DialogTitle id="plan-title">Preview {preview ? idOf(preview.name) : ""}</DialogTitle>
      <DialogContent><Box sx={{ pt: 1 }}><PlanBody preview={preview} /></Box></DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}
