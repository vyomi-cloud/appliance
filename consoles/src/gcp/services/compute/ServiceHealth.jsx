/* Google Cloud incidents - a SIMULATED Service Health feed (core/gcp_servicehealth_core) over the servicehealth v1
 * events REST path. Not Google's real status: it reports the simulated project, starts empty, and lets you inject,
 * update, resolve and delete test incidents. Everything shown is labelled "Simulated by Vyomi". */
import { useState } from "react";
import { Alert, Box, Button, Chip, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import AddIcon from "@mui/icons-material/esm/Add.js";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";
import { FormDialog } from "./Ext.jsx";

const STATUS_LABEL = { AVAILABLE: "Available", SERVICE_INFORMATION: "Service information", SERVICE_DISRUPTION: "Service disruption", SERVICE_OUTAGE: "Service outage" };
const STATUS_COLOR = { AVAILABLE: "success", SERVICE_INFORMATION: "info", SERVICE_DISRUPTION: "warning", SERVICE_OUTAGE: "error" };
const SEV_OPTS = [["INFORMATION", "Information"], ["DISRUPTION", "Disruption"], ["OUTAGE", "Outage"]];
const last = (v) => String(v || "").split("/").pop();

export default function ServiceHealth() {
  const project = useProject();
  const notify = useNotify();
  const [inject, setInject] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const { data, loading, error, reload } = useAsync(async () => {
    const [status, events] = await Promise.all([api.serviceHealthStatus(), api.serviceHealthEvents()]);
    return { services: status.services || [], events };
  }, [project]);
  const events = data?.events || [];
  const active = events.filter((e) => e.state === "ACTIVE");
  const closed = events.filter((e) => e.state !== "ACTIVE");
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); reload(); } catch (e) { notify.error(e); } };
  const shown = showHistory ? events : active;

  return (
    <CapabilityContainer id="gcp.compute.incidents" title="Google Cloud incidents"
      actions={<>
        <Button size="small" startIcon={<AddIcon />} onClick={() => setInject(true)}>Inject test incident</Button>
        <Button size="small" startIcon={<RefreshIcon />} onClick={reload}>Refresh</Button>
      </>}>
      <Stack spacing={2}>
        <Alert severity="info" icon={false} sx={{ py: 0.5 }}>
          <b>Simulated by Vyomi.</b> This is not Google's status feed. It reports the health of your simulated project: every
          service is Available and there is no incident history until you inject a test incident.
        </Alert>
        <ErrorAlert error={error} title="Could not load the service health feed" />
        <Box>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            {active.length ? `${active.length} active incident${active.length === 1 ? "" : "s"}` : "No active incidents"}
            {" "}<Chip size="small" variant="outlined" label="Simulated by Vyomi" />
          </Typography>
          {shown.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {loading ? "Loading…" : showHistory ? "Incident history is empty." : "Everything is operating normally in this simulated project."}
            </Typography>
          ) : (
            <Table size="small">
              <TableHead><TableRow>
                <TableCell>Incident</TableCell><TableCell>Impacted</TableCell><TableCell>State</TableCell><TableCell>Started</TableCell><TableCell align="right">Actions</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {shown.map((e) => {
                  const id = last(e.name);
                  const products = [...new Set((e.eventImpacts || []).map((i) => i.product?.productName))].join(", ");
                  return (
                    <TableRow key={id}>
                      <TableCell>
                        <Typography variant="body2" fontWeight={600}>{e.title}</Typography>
                        {e.description && <Typography variant="caption" color="text.secondary">{e.description}</Typography>}
                      </TableCell>
                      <TableCell>{products}</TableCell>
                      <TableCell><Chip size="small" color={e.state === "ACTIVE" ? STATUS_COLOR[`SERVICE_${e.vyomiSeverity === "INFORMATION" ? "INFORMATION" : e.vyomiSeverity}`] : "default"} label={e.state === "ACTIVE" ? e.vyomiSeverity.toLowerCase() : "resolved"} /></TableCell>
                      <TableCell>{fmtDate(e.startTime)}</TableCell>
                      <TableCell align="right">
                        {e.state === "ACTIVE" && <Button size="small" onClick={() => act(() => api.resolveServiceHealthEvent(id), "Incident resolved")}>Resolve</Button>}
                        <Button size="small" color="error" onClick={() => act(() => api.deleteServiceHealthEvent(id), "Incident deleted")}>Delete</Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          <Button size="small" sx={{ mt: 1 }} onClick={() => setShowHistory(!showHistory)}>
            {showHistory ? "Show active only" : `Show incident history (${closed.length} resolved)`}
          </Button>
        </Box>
        <Box>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Service status</Typography>
          <Table size="small">
            <TableHead><TableRow><TableCell>Service</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
            <TableBody>
              {(data?.services || []).map((s) => (
                <TableRow key={s.service}>
                  <TableCell>{s.service}</TableCell>
                  <TableCell><Chip size="small" color={STATUS_COLOR[s.status]} label={STATUS_LABEL[s.status] || s.status} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      </Stack>
      <FormDialog open={inject} title="Inject test incident" submitLabel="Inject" onClose={() => setInject(false)} fields={[
        { key: "title", label: "Title", default: "Elevated error rates", required: true },
        { key: "description", label: "Description", default: "" },
        { key: "service", label: "Impacted service", options: (data?.services || []).map((s) => [s.service, s.service]), default: "Compute Engine" },
        { key: "severity", label: "Severity", options: SEV_OPTS, default: "DISRUPTION" },
        { key: "location", label: "Location", options: api.SERVICE_HEALTH_LOCATIONS.map((l) => [l, l]), default: "global" },
      ]} onSubmit={async (v) => {
        await api.createServiceHealthEvent({ title: v.title, description: v.description, products: [v.service], severity: v.severity, locations: [v.location] });
        notify.success("Test incident injected"); reload();
      }} />
    </CapabilityContainer>
  );
}
