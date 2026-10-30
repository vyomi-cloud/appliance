/* Error reporting — Google groups deduplicated error signatures out of Cloud Logging
 * entries; Vyomi has no log-based error grouping (see gcp.monitoring.error-reporting), so
 * this shows the real ERROR+ severity entries from Cloud Logging as a flat, ungrouped list
 * instead of faking group counts/charts the console can't compute. */
import { Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { PageHeader, Section } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useProject } from "../../project.js";
import * as api from "./api.js";

export default function ErrorReporting() {
  const project = useProject();
  const { data: entries = [] } = useAsync(() => api.listErrorEntries(), [project]);

  return (
    <>
      <PageHeader title="Error reporting" />
      <CapabilityContainer id="gcp.monitoring.error-reporting" title="Error groups">
        <Section title="Recent errors" noPad>
          <Table size="small">
            <TableHead><TableRow><TableCell>Timestamp</TableCell><TableCell>Log</TableCell><TableCell>Message</TableCell></TableRow></TableHead>
            <TableBody>
              {entries.length ? entries.map((e, i) => (
                <TableRow key={i}>
                  <TableCell>{e.timestamp ? new Date(e.timestamp).toLocaleString() : "—"}</TableCell>
                  <TableCell>{(e.logName || "").split("/logs/")[1] || "—"}</TableCell>
                  <TableCell>{e.textPayload || e.jsonPayload?.message || JSON.stringify(e.jsonPayload || e.protoPayload || "")}</TableCell>
                </TableRow>
              )) : <TableRow><TableCell colSpan={3}><Typography variant="body2" color="text.secondary">No ERROR-severity log entries yet.</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Section>
      </CapabilityContainer>
    </>
  );
}
