/* Default Directory | Sign-in logs — azure.entra.sign_in_logs is limited: "Service
 * principal sign-ins" is real, driven by the oauth2/v2.0/token client_credentials grant
 * (core/azure_graph_core.py) — every row here is a genuine client-secret validation (see
 * Certificates & secrets' "Test sign-in" action), never sample data. The three sign-in
 * types Vyomi has no flow to generate (interactive/non-interactive user sign-ins,
 * managed identity sign-ins) stay honest gaps rather than a skeleton of empty rows. */
import { useState } from "react";
import {
  Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
  Tab, TabList, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";
import { fmtDateTime } from "./api.js";

const COLUMNS = ["Date", "Request ID", "User", "Application", "Status", "Sign-in error code", "IP address", "Location", "Conditional Access", "Agent Type", "Authentication requirement"];

function downloadCsv(rows) {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const text = [COLUMNS.join(","), ...rows.map((r) => [
    fmtDateTime(r.createdDateTime), r.id, r.userDisplayName || "--", r.appDisplayName,
    r.status.errorCode === 0 ? "Success" : "Failure", r.status.errorCode || "--",
    r.ipAddress, "--", r.conditionalAccessStatus, "Application", r.authenticationRequirement,
  ].map(esc).join(","))].join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = "sign-in-logs.csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

export default function SignInLogs() {
  const [tab, setTab] = useState("serviceprincipal");
  const { data, loading, error, reload } = useAsync(() => api.listSignInLogs(), []);
  const rows = data || [];
  return (
    <EntraShell active="signinlogs" title="Default Directory | Sign-in logs">
      <div className="vy-page">
        <div className="vy-cmdbar" role="toolbar" aria-label="Sign-in logs commands">
          <ToolbarButton onClick={() => downloadCsv(rows)}>Download</ToolbarButton>
          <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        </div>
        <NotSimulatedContainer feature="Export Data Settings, Troubleshoot, Columns, Got feedback?"
          note="Export Data Settings. Troubleshoot. Columns. Got feedback? Not simulated in Vyomi." />
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Sign-in logs">
          <Tab value="interactive">User sign-ins (interactive)</Tab>
          <Tab value="noninteractive">User sign-ins (non-interactive)</Tab>
          <Tab value="serviceprincipal">Service principal sign-ins</Tab>
          <Tab value="managedidentity">Managed identity sign-ins</Tab>
        </TabList>
        {tab === "serviceprincipal" && (
          <CapabilityContainer id="azure.entra.sign_in_logs" title="Service principal sign-ins">
            {loading && <p>Loading...</p>}
            {error && <p>Failed to load sign-in logs.</p>}
            {!loading && !error && (
              <Table size="small">
                <TableHeader><TableRow>{COLUMNS.map((c) => <TableHeaderCell key={c}>{c}</TableHeaderCell>)}</TableRow></TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>{fmtDateTime(r.createdDateTime)}</TableCell>
                      <TableCell>{r.id}</TableCell>
                      <TableCell>{r.userDisplayName || "--"}</TableCell>
                      <TableCell>{r.appDisplayName}</TableCell>
                      <TableCell>{r.status.errorCode === 0 ? "Success" : "Failure"}</TableCell>
                      <TableCell>{r.status.errorCode || "--"}</TableCell>
                      <TableCell>{r.ipAddress}</TableCell>
                      <TableCell>--</TableCell>
                      <TableCell>{r.conditionalAccessStatus}</TableCell>
                      <TableCell>Application</TableCell>
                      <TableCell>{r.authenticationRequirement}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {!loading && !rows.length && <p>No service principal sign-ins recorded yet. Request a token with a real application client secret (App registrations | Certificates &amp; secrets | Test sign-in) to see one here.</p>}
          </CapabilityContainer>
        )}
        {tab === "interactive" && <NotSimulated feature="User sign-ins (interactive)" note="Vyomi has no interactive browser sign-in flow to generate this telemetry from." />}
        {tab === "noninteractive" && <NotSimulated feature="User sign-ins (non-interactive)" note="Vyomi has no silent token-refresh flow (no browser session) to generate this telemetry from." />}
        {tab === "managedidentity" && <NotSimulated feature="Managed identity sign-ins" note="Vyomi does not simulate the Azure Instance Metadata Service (IMDS) a managed identity calls to get a token." />}
      </div>
    </EntraShell>
  );
}
