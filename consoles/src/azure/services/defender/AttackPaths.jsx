/* Defender for Cloud | Attack path analysis and Cloud Security Explorer: both computed live from the ARM state
 * (core/azure_attackpath_core.py); both need the Defender CSPM plan, which this page can switch on. */
import { useState } from "react";
import { Button, Field, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import DefenderShell from "./DefenderShell.jsx";
import * as api from "./api.js";

const NeedPlan = ({ reload }) => {
  const notify = useNotify();
  return (
    <div>
      <p>These pages need the <b>Defender CSPM</b> plan. It is off for this subscription.</p>
      <Button appearance="primary" onClick={async () => { try { await api.setPricing("CloudPosture", "Standard"); notify.success("Defender CSPM is on.", "Plans"); reload(); } catch (e) { notify.error(e, "Could not enable the plan"); } }}>Enable Defender CSPM</Button>
    </div>
  );
};
const planOff = (e) => e && (e.code === "PlanNotEnabled" || e.status === 403);

export function AttackPaths() {
  const d = useAsync(() => api.listAttackPaths(), []);
  const [open, setOpen] = useState(null);
  return (
    <DefenderShell active="attackpath">
      <div className="vy-panel-title">Attack path analysis</div>
      <p>Paths are derived from configuration right now: an internet-reachable management port, the VM's managed identity, and the role assignments that identity holds. They show what an attacker <i>could</i> do, not what happened.</p>
      {d.error && !planOff(d.error) && <ErrorBar error={d.error} title="Could not compute attack paths" />}
      {planOff(d.error) ? <NeedPlan reload={d.reload} /> : d.loading && !d.data ? <Loading /> : (
        <Table size="small" aria-label="Attack paths">
          <TableHeader><TableRow>{["Risk", "Attack path", "Entry point", "Target"].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
          <TableBody>
            {(d.data || []).length === 0 && <TableRow><TableCell colSpan={4}>No attack paths found.</TableCell></TableRow>}
            {(d.data || []).map((p) => (
              <TableRow key={p.id} onClick={() => setOpen(open === p.id ? null : p.id)} style={{ cursor: "pointer" }}>
                <TableCell>{p.riskLevel}</TableCell><TableCell>{p.displayName}</TableCell><TableCell>{p.entryPoint.split("/").pop()}</TableCell><TableCell>{p.target.split("/").pop()}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {(d.data || []).filter((p) => p.id === open).map((p) => (
        <div key={p.id} style={{ marginTop: 16 }}>
          <h3>{p.displayName}</h3>
          <ol>{p.steps.map((s, i) => <li key={i}><b>{s.node}</b> ({s.type}){s.via ? ` - ${s.via.map((v) => `port ${v.port} via rule '${v.rule}'`).join(", ")}` : ""}{s.role ? ` - ${s.role} at ${s.roleScope}` : ""}{(s.insights || []).length ? ` - ${s.insights.map((x) => x.name).join("; ")}` : ""}</li>)}</ol>
          <h4>Remediation</h4><ul>{p.remediation.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </div>
      ))}
    </DefenderShell>
  );
}

const TYPES = ["microsoft.compute/virtualmachines", "microsoft.storage/storageaccounts", "microsoft.keyvault/vaults", "microsoft.web/sites", "microsoft.sql/servers"];
const FILTERS = ["exposedToInternet", "hasIdentity", "hasRecommendation", "privileged", "canAccess:microsoft.keyvault/vaults", "canAccess:microsoft.storage/storageaccounts", "canAccess:microsoft.sql/servers"];
export function CloudSecurityExplorer() {
  const notify = useNotify();
  const [type, setType] = useState(TYPES[0]);
  const [sel, setSel] = useState(["exposedToInternet"]);
  const [res, setRes] = useState(null);
  const [off, setOff] = useState(false);
  const run = async () => { try { setRes(await api.exploreGraph({ nodeType: type, filters: sel })); setOff(false); } catch (e) { if (planOff(e)) setOff(true); else notify.error(e, "Query failed"); } };
  return (
    <DefenderShell active="explorer">
      <div className="vy-panel-title">Cloud Security Explorer</div>
      <p>Query the security graph built from your ARM resources, their network exposure, managed identities and role assignments.</p>
      {off ? <NeedPlan reload={run} /> : (
        <>
          <Field label="Find"><Select value={type} onChange={(_, d) => setType(d.value)}>{TYPES.map((t) => <option key={t}>{t}</option>)}</Select></Field>
          <fieldset style={{ border: "none", padding: 0, margin: "8px 0" }}><legend>That match all of</legend>
            {FILTERS.map((f) => <label key={f} style={{ display: "block" }}><input type="checkbox" checked={sel.includes(f)} onChange={(e) => setSel(e.target.checked ? [...sel, f] : sel.filter((x) => x !== f))} /> {f}</label>)}
          </fieldset>
          <Button appearance="primary" onClick={run}>Search</Button>
          {res && (
            <Table size="small" aria-label="Results" style={{ marginTop: 12 }}>
              <TableHeader><TableRow>{["Name", "Type", "Evidence"].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
              <TableBody>
                {res.results.length === 0 && <TableRow><TableCell colSpan={3}>No resources match.</TableCell></TableRow>}
                {res.results.map((r) => <TableRow key={r.id}><TableCell>{r.name}</TableCell><TableCell>{r.type}</TableCell><TableCell><code>{JSON.stringify(r.evidence)}</code></TableCell></TableRow>)}
              </TableBody>
            </Table>
          )}
        </>
      )}
    </DefenderShell>
  );
}
