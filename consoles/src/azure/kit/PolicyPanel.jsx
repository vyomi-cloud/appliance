/* Azure Policy at any scope (subscription / resource group), shared by the Subscriptions "Manage
 * Policies" dialog, the resource group Policies blade and AKS Policies. Backed by the real
 * policy rule engine (core/azure_policy_core.py): built-in + custom policyDefinitions, scoped
 * policyAssignments, and PolicyInsights compliance. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Spinner, Tab, TabList, Textarea, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar } from "./common.jsx";
import { getSubscription } from "./arm.js";

const AV = "2022-06-01";
const subPath = () => `/subscriptions/${getSubscription()}`;
const scopePath = (rg) => (rg ? `${subPath()}/resourceGroups/${rg}` : subPath());
const listDefs = async () => (await restJson("GET", `${subPath()}/providers/Microsoft.Authorization/policyDefinitions`, { query: { "api-version": "2021-06-01" } })).value || [];
const listAssignments = async (rg) => (await restJson("GET", `${scopePath(rg)}/providers/Microsoft.Authorization/policyAssignments`, { query: { "api-version": AV } })).value || [];
const compliance = async (rg) => (await restJson("POST", `${scopePath(rg)}/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults`, { query: { "api-version": "2019-10-01" } })).value || [];

const SAMPLE_RULE = JSON.stringify({ if: { allOf: [{ field: "type", equals: "Microsoft.Storage/storageAccounts" }, { field: "tags['costcenter']", exists: "false" }] }, then: { effect: "deny" } }, null, 2);

export default function PolicyPanel({ rg, resourceId, title = "Policies" }) {
  const notify = useNotify();
  const [tab, setTab] = useState("compliance");
  const [add, setAdd] = useState(false);
  const [defOpen, setDefOpen] = useState(false);
  const assignments = useAsync(() => listAssignments(rg), [rg]);
  const states = useAsync(async () => {
    const all = await compliance(rg);
    return resourceId ? all.filter((r) => String(r.resourceId || "").toLowerCase().startsWith(resourceId.toLowerCase())) : all;
  }, [rg, resourceId]);
  const defs = useAsync(listDefs, []);
  const rows = assignments.data || [];
  const st = states.data || [];
  const bad = st.filter((r) => r.complianceState === "NonCompliant").length;
  return (
    <CapabilityContainer id="azure.subscriptions.policies" title={title}>
      <TabList selectedValue={tab} onTabSelect={(_, d) => { setTab(d.value); if (d.value === "compliance") states.reload(); }} aria-label="Policy tabs">
        <Tab value="compliance">Compliance</Tab>
        <Tab value="assignments">Assignments</Tab>
        <Tab value="definitions">Definitions</Tab>
      </TabList>
      {tab === "compliance" && (
        <>
          <ErrorBar error={states.error} />
          <p style={{ fontSize: 13 }} data-testid="policy-summary">{states.loading ? "Evaluating…" : `${st.length} evaluation${st.length === 1 ? "" : "s"}, ${bad} non-compliant.`}</p>
          <table className="vy-grid">
            <thead><tr><th>Resource</th><th>Policy</th><th>Effect</th><th>Compliance state</th></tr></thead>
            <tbody>
              {states.loading ? <tr><td colSpan={4}><Spinner size="tiny" /></td></tr> : st.length ? st.map((r, i) => (
                <tr key={i}><td>{r.resourceId?.split("/").pop()}</td><td>{r.policyDefinitionName || r.policyAssignmentName}</td><td>{r.policyDefinitionAction || "--"}</td><td>{r.complianceState}</td></tr>
              )) : <tr><td colSpan={4} className="vy-muted">No policy assignments to evaluate at this scope.</td></tr>}
            </tbody>
          </table>
        </>
      )}
      {tab === "assignments" && (
        <BrowseGrid
          resourceName="assignment" rowKey={(r) => r.name} items={rows} loading={assignments.loading} error={assignments.error} onRefresh={assignments.reload}
          extraCommands={<ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Assign policy</ToolbarButton>}
          onDelete={async (sel) => {
            for (const r of sel) await restJson("DELETE", `${scopePath(rg)}/providers/Microsoft.Authorization/policyAssignments/${encodeURIComponent(r.name)}`, { query: { "api-version": AV } });
            notify.success(`Deleted ${sel.length} assignment${sel.length === 1 ? "" : "s"}.`, "Delete succeeded"); assignments.reload();
          }}
          csvName="policy-assignments.csv" emptyAction={<span className="vy-muted">No policy assignments at this scope.</span>}
          columns={[
            { key: "name", label: "Assignment name" },
            { key: "def", label: "Definition", value: (r) => r.properties?.displayName || r.properties?.policyDefinitionId?.split("/").pop() },
            { key: "scope", label: "Scope", value: (r) => (r.id?.includes("/resourceGroups/") ? "Resource group" : "Subscription") },
            { key: "enf", label: "Enforcement", value: (r) => r.properties?.enforcementMode || "Default" },
          ]}
        />
      )}
      {tab === "definitions" && (
        <>
          <div style={{ margin: "8px 0" }}><Button onClick={() => setDefOpen(true)}>New policy definition</Button></div>
          <table className="vy-grid">
            <thead><tr><th>Name</th><th>Type</th><th>Effect</th></tr></thead>
            <tbody>{(defs.data || []).map((d) => (
              <tr key={d.name}><td>{d.properties?.displayName || d.name}</td><td>{d.properties?.policyType || "Custom"}</td><td>{String(d.properties?.policyRule?.then?.effect || "")}</td></tr>
            ))}</tbody>
          </table>
        </>
      )}
      <AssignDialog open={add} onClose={() => setAdd(false)} defs={defs.data || []} rg={rg} onDone={() => { assignments.reload(); states.reload(); }} />
      <DefinitionDialog open={defOpen} onClose={() => setDefOpen(false)} onDone={defs.reload} />
    </CapabilityContainer>
  );
}

function AssignDialog({ open, onClose, defs, rg, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [defName, setDefName] = useState("");
  const [vals, setVals] = useState({});
  const d = defs.find((x) => x.name === (defName || defs[0]?.name));
  const params = Object.entries(d?.properties?.parameters || {}).filter(([, s]) => !("defaultValue" in s));
  const go = async () => {
    try {
      const parameters = Object.fromEntries(params.map(([k, s]) => [k, { value: s.type === "Array" ? String(vals[k] || "").split(",").map((x) => x.trim()).filter(Boolean) : vals[k] }]));
      await restJson("PUT", `${scopePath(rg)}/providers/Microsoft.Authorization/policyAssignments/${encodeURIComponent(name)}`, {
        query: { "api-version": AV }, body: { properties: { displayName: d.properties?.displayName, policyDefinitionId: d.id, parameters } } });
      notify.success(`Policy '${name}' was assigned.`, "Assign policy"); setName(""); setVals({}); onClose(); onDone();
    } catch (e) { notify.error(e, "Failed to assign policy"); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, x) => !x.open && onClose()}>
      <DialogSurface aria-label="Assign policy"><DialogBody>
        <DialogTitle>Assign policy</DialogTitle>
        <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Policy definition"><Select value={d?.name || ""} onChange={(_, x) => { setDefName(x.value); setVals({}); }} aria-label="Policy definition">
            {defs.map((x) => <option key={x.name} value={x.name}>{x.properties?.displayName || x.name}</option>)}</Select></Field>
          <Field label="Assignment name" required><Input value={name} onChange={(_, x) => setName(x.value)} aria-label="Assignment name" /></Field>
          {params.map(([k, s]) => (
            <Field key={k} label={s.metadata?.displayName || k} hint={s.type === "Array" ? "Comma-separated values" : undefined}>
              <Input value={vals[k] || ""} onChange={(_, x) => setVals((v) => ({ ...v, [k]: x.value }))} aria-label={s.metadata?.displayName || k} /></Field>
          ))}
        </div></DialogContent>
        <DialogActions><Button appearance="primary" disabled={!name.trim() || !d} onClick={go}>Assign</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}

function DefinitionDialog({ open, onClose, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [rule, setRule] = useState(SAMPLE_RULE);
  const go = async () => {
    try {
      await restJson("PUT", `${subPath()}/providers/Microsoft.Authorization/policyDefinitions/${encodeURIComponent(name)}`, {
        query: { "api-version": "2021-06-01" }, body: { properties: { displayName: name, mode: "Indexed", policyRule: JSON.parse(rule) } } });
      notify.success(`Policy definition '${name}' was created.`, "Create definition"); setName(""); onClose(); onDone();
    } catch (e) { notify.error(e, "Failed to create policy definition"); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, x) => !x.open && onClose()}>
      <DialogSurface aria-label="New policy definition"><DialogBody>
        <DialogTitle>New policy definition</DialogTitle>
        <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Definition name" required><Input value={name} onChange={(_, x) => setName(x.value)} aria-label="Definition name" /></Field>
          <Field label="Policy rule (JSON)" hint="Effects evaluated: deny, audit, disabled. count and deployIfNotExists are not evaluated."><Textarea rows={10} value={rule} onChange={(_, x) => setRule(x.value)} aria-label="Policy rule" /></Field>
        </div></DialogContent>
        <DialogActions><Button appearance="primary" disabled={!name.trim()} onClick={go}>Create</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}
