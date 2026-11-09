/* Default Directory | Sign-in logs — azure.entra.sign_in_logs is limited: "Service
 * principal sign-ins" is real, driven by the oauth2/v2.0/token client_credentials grant
 * (core/azure_graph_core.py) — every row here is a genuine client-secret validation (see
 * Certificates & secrets' "Test sign-in" action), never sample data. All four tabs are backed by
 * a real flow: non-interactive = the ROPC password grant, interactive = the authorization-code
 * request (/oauth2/v2.0/authorize, Test interactive sign-in), managed identity = a token issued
 * by the IMDS simulation (a VM's Run command calling 169.254.169.254). */
import { useState } from "react";
import { Button, Input } from "@fluentui/react-components";
import {
  Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
  Tab, TabList, ToolbarButton,
} from "@fluentui/react-components";
import { ArrowClockwise20Regular } from "@fluentui/react-icons";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import EntraShell from "./EntraShell.jsx";
import * as api from "./api.js";
import { fmtDateTime } from "./api.js";

const OPTIONAL_COLUMNS = ["Request ID", "Application", "IP address", "Location", "Conditional Access", "Agent Type", "Authentication requirement"];
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

/** What Entra says about each failure code Vyomi can produce (the "Troubleshoot" pane). */
const TROUBLESHOOT = {
  50034: "The user account does not exist in the directory. Create the user under Users, or check the user principal name for typos.",
  50057: "The user account is disabled. Re-enable it on the user's Properties tab (Account enabled).",
  50126: "Wrong password. Reset the password on the user, or retry with the current one.",
  50076: "A Conditional Access policy requires multi-factor authentication. Vyomi has no authenticator enrolment, so this sign-in can only succeed when the policy is excluded for the user.",
  53000: "A Conditional Access policy blocked this sign-in (device not compliant). Vyomi does not evaluate real devices.",
  53003: "A Conditional Access policy blocked access (location, platform, risk or client app). Review the policy's conditions under Conditional Access.",
  700016: "The application was not found or the enterprise application is disabled. Check the client ID and the Enterprise applications blade.",
  7000215: "The client secret is invalid. Create a new secret under Certificates & secrets and use its value (not its ID).",
};

export default function SignInLogs() {
  const [tab, setTab] = useState("serviceprincipal");
  const { data, loading, error, reload } = useAsync(() => api.listSignInLogs(), []);
  const all = data || [];
  const EVENT = { interactive: "interactiveUser", noninteractive: "nonInteractiveUser", serviceprincipal: "servicePrincipal", managedidentity: "managedIdentity" };
  const rows = all.filter((r) => (r.signInEventTypes || []).includes(EVENT[tab]));
  const [hidden, setHidden] = useState(() => new Set());
  const [showCols, setShowCols] = useState(false);
  const [showTrouble, setShowTrouble] = useState(false);
  const failures = rows.filter((r) => r.status.errorCode !== 0);
  const [u, setU] = useState(""); const [pw, setPw] = useState(""); const [msg, setMsg] = useState(null);
  const tryUser = async () => { try { await (tab === "interactive" ? api.signInInteractive : api.signInWithPassword)(u, pw); setMsg("Sign-in succeeded - a real row was added below."); } catch (e) { setMsg(`Sign-in failed (${e.message}).`); } reload(); };
  return (
    <EntraShell active="signinlogs" title="Default Directory | Sign-in logs">
      <div className="vy-page">
        <div className="vy-cmdbar" role="toolbar" aria-label="Sign-in logs commands">
          <ToolbarButton onClick={() => downloadCsv(rows)}>Download</ToolbarButton>
          <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
        </div>
        <div className="vy-cmdbar" role="toolbar" aria-label="Sign-in logs view">
          <ToolbarButton onClick={() => { setShowCols((v) => !v); setShowTrouble(false); }}>Columns</ToolbarButton>
          <ToolbarButton onClick={() => { setShowTrouble((v) => !v); setShowCols(false); }}>Troubleshoot</ToolbarButton>
        </div>
        {showCols && (
          <div role="group" aria-label="Choose columns" style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "6px 0" }}>
            {OPTIONAL_COLUMNS.map((c) => (
              <label key={c}><input type="checkbox" checked={!hidden.has(c)} onChange={() => setHidden((h) => { const n = new Set(h); n.has(c) ? n.delete(c) : n.add(c); return n; })} /> {c}</label>
            ))}
          </div>)}
        {showTrouble && (
          <section aria-label="Troubleshoot sign-in failures" style={{ margin: "6px 0" }}>
            <h3>Troubleshoot</h3>
            {!failures.length ? <p>No failed sign-ins in this tab. Failed attempts are explained here by their error code.</p>
              : <ul>{[...new Set(failures.map((r) => r.status.errorCode))].map((code) => (
                  <li key={code}><b>AADSTS{code}</b> ({failures.filter((r) => r.status.errorCode === code).length}x): {TROUBLESHOOT[code] || "No guidance is recorded for this error code."}</li>))}</ul>}
          </section>)}
        <NotSimulatedContainer feature="Export Data Settings, Got feedback?"
          note="Export Data Settings (streaming tenant sign-in logs to a Log Analytics workspace or storage account) is not simulated: Vyomi keeps these logs in the directory only. Got feedback? is not simulated." />
        <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Sign-in logs">
          <Tab value="interactive">User sign-ins (interactive)</Tab>
          <Tab value="noninteractive">User sign-ins (non-interactive)</Tab>
          <Tab value="serviceprincipal">Service principal sign-ins</Tab>
          <Tab value="managedidentity">Managed identity sign-ins</Tab>
        </TabList>
        <CapabilityContainer id="azure.entra.sign_in_logs" title={{ interactive: "User sign-ins (interactive)", noninteractive: "User sign-ins (non-interactive)", serviceprincipal: "Service principal sign-ins", managedidentity: "Managed identity sign-ins" }[tab]}>
            {(tab === "noninteractive" || tab === "interactive") && (
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
                <Input placeholder="user principal name" value={u} onChange={(_, d) => setU(d.value)} aria-label="Test sign-in user" />
                <Input type="password" placeholder="password" value={pw} onChange={(_, d) => setPw(d.value)} aria-label="Test sign-in password" />
                <Button onClick={tryUser}>{tab === "interactive" ? "Test interactive sign-in" : "Test sign-in"}</Button>{msg && <span role="status">{msg}</span>}
              </div>)}
            {loading && <p>Loading...</p>}
            {error && <p>Failed to load sign-in logs.</p>}
            {!loading && !error && (
              <Table size="small">
                <TableHeader><TableRow>{COLUMNS.filter((c) => !hidden.has(c)).map((c) => <TableHeaderCell key={c}>{c}</TableHeaderCell>)}</TableRow></TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={r.id}>
                      {[
                        ["Date", fmtDateTime(r.createdDateTime)], ["Request ID", r.id], ["User", r.userDisplayName || "--"], ["Application", r.appDisplayName],
                        ["Status", r.status.errorCode === 0 ? "Success" : "Failure"], ["Sign-in error code", r.status.errorCode || "--"], ["IP address", r.ipAddress],
                        ["Location", "--"], ["Conditional Access", r.conditionalAccessStatus],
                        ["Agent Type", tab === "noninteractive" || tab === "interactive" ? "User" : tab === "managedidentity" ? "Managed identity" : "Application"],
                        ["Authentication requirement", r.authenticationRequirement],
                      ].filter(([c]) => !hidden.has(c)).map(([c, v]) => <TableCell key={c}>{v}</TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {!loading && !rows.length && <p>{{
              interactive: "No interactive sign-ins recorded yet. Use Test interactive sign-in with a directory user's password (it posts the authorization-code request to /oauth2/v2.0/authorize) to see one here.",
              noninteractive: "No user sign-ins recorded yet. Use Test sign-in with a directory user's password (or acquire a token with the password grant) to see one here.",
              managedidentity: "No managed identity sign-ins recorded yet. Enable a system-assigned identity on a virtual machine and, in its Run command, request a token from http://169.254.169.254/metadata/identity/oauth2/token to see one here.",
              serviceprincipal: "No service principal sign-ins recorded yet. Request a token with a real application client secret (App registrations | Certificates & secrets | Test sign-in) to see one here.",
            }[tab]}</p>}
          </CapabilityContainer>
      </div>
    </EntraShell>
  );
}
