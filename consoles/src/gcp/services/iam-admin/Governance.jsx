/* Resource hierarchy + Organization Policy governance (organization > folders > projects).
 *  - Tree from GET /api/iam/gcp/governance/hierarchy (folders / projects from Resource Manager v3).
 *  - Per node: the constraint catalog (Org Policy v2 GET /v2/{node}/constraints), the policy set on the node (POST/PATCH/DELETE /v2/{node}/policies),
 *    the inheritance view (every ancestor's rule + the effective result) and a dry-run check (spec vs dryRunSpec).
 *  - IAM side of the node: allow bindings, deny policies and Principal Access Boundary links (native pages). */
import { useState } from "react";
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Switch, Tab, Tabs, TextField, Typography } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { restJson } from "../../../common/wire.js";
import { getProject } from "../../project.js";
import { gov } from "../../../common/governanceApi.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader, Section } from "../../kit/common.jsx";

const ICON = { organization: "\u{1F3E2}", folder: "\u{1F4C1}", project: "■" };
const cid = (c) => String(c).replace("constraints/", "");

function Tree({ node, selected, onSelect, depth = 0 }) {
  return (
    <div>
      <Box data-node={node.id} onClick={() => onSelect(node)} role="treeitem" aria-selected={selected === node.id}
        sx={{ pl: depth * 2.5, py: 0.5, cursor: "pointer", fontWeight: selected === node.id ? 600 : 400, bgcolor: selected === node.id ? "action.selected" : "transparent", borderRadius: 1 }}>
        {ICON[node.type]} {node.name} <Typography component="span" variant="caption" color="text.secondary">{node.id.startsWith("organizations") || node.id.startsWith("folders") ? node.id : (node.number || "")}{node.orgPolicies ? ` · ${node.orgPolicies} polic${node.orgPolicies === 1 ? "y" : "ies"}` : ""}</Typography>
      </Box>
      {node.children.map((c) => <Tree key={c.id} node={c} selected={selected} onSelect={onSelect} depth={depth + 1} />)}
    </div>
  );
}

const MODES = [["enforce", "Enforce"], ["not", "Not enforced"], ["allowAll", "Allow all values"], ["denyAll", "Deny all values"], ["custom", "Custom values"]];

function specFromForm(kind, f) {
  if (f.reset) return { reset: true };
  if (kind === "boolean") return { rules: [{ enforce: f.mode === "enforce" }] };
  const rules = [];
  if (f.mode === "allowAll") rules.push({ allowAll: true });
  else if (f.mode === "denyAll") rules.push({ denyAll: true });
  else {
    const split = (s) => s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
    const values = {};
    if (split(f.allowed).length) values.allowedValues = split(f.allowed);
    if (split(f.denied).length) values.deniedValues = split(f.denied);
    rules.push({ values });
  }
  return { inheritFromParent: !!f.inherit, rules };
}

function PolicyDialog({ node, constraint, existing, onClose, onSaved }) {
  const notify = useNotify();
  const kind = constraint.booleanConstraint ? "boolean" : "list";
  const spec0 = existing?.spec || {}, dry0 = existing?.dryRunSpec;
  const [f, setF] = useState({ mode: kind === "boolean" ? ((spec0.rules || [{}])[0].enforce ? "enforce" : "not") : "custom", allowed: "", denied: "", inherit: !!spec0.inheritFromParent, reset: false });
  const [dry, setDry] = useState(!!dry0);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const spec = specFromForm(kind, f);
      const body = dry ? { dryRunSpec: spec } : { spec };
      const c = cid(constraint.name);
      if (existing) await restJson("PATCH", `/v2/${node}/policies/${c}`, { body });
      else await restJson("POST", `/v2/${node}/policies`, { body: { name: `${node}/policies/${c}`, ...body } });
      notify.success(`${dry ? "Dry-run policy" : "Policy"} saved on ${node}.`); onSaved(); onClose();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Manage policy: {constraint.displayName}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">{constraint.description}</Typography>
          <FormControlLabel control={<Switch checked={f.reset} onChange={(e) => setF({ ...f, reset: e.target.checked })} />} label="Reset to default (ignore parent policies)" />
          {!f.reset && kind === "boolean" && (
            <TextField select size="small" label="Enforcement" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })} inputProps={{ "aria-label": "Enforcement" }}>
              <MenuItem value="enforce">Enforce</MenuItem><MenuItem value="not">Not enforced</MenuItem></TextField>)}
          {!f.reset && kind === "list" && (<>
            <TextField select size="small" label="Policy values" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })} inputProps={{ "aria-label": "Policy values" }}>
              {MODES.filter(([v]) => v !== "enforce" && v !== "not").map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}</TextField>
            {f.mode === "custom" && (<>
              <TextField size="small" multiline minRows={2} label="Allowed values" helperText="One per line. in:us-locations, under:folders/123, is:value" value={f.allowed} onChange={(e) => setF({ ...f, allowed: e.target.value })} inputProps={{ "aria-label": "Allowed values" }} />
              <TextField size="small" multiline minRows={2} label="Denied values" value={f.denied} onChange={(e) => setF({ ...f, denied: e.target.value })} inputProps={{ "aria-label": "Denied values" }} />
              <FormControlLabel control={<Switch checked={f.inherit} onChange={(e) => setF({ ...f, inherit: e.target.checked })} />} label="Inherit parent's policy (merge)" />
            </>)}
          </>)}
          <FormControlLabel control={<Switch checked={dry} onChange={(e) => setDry(e.target.checked)} />} label="Dry run: record what this policy would block, do not enforce it" />
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" disabled={busy} onClick={save}>Set policy</Button></DialogActions>
    </Dialog>
  );
}

function CheckPanel({ node, constraints }) {
  const [c, setC] = useState(""); const [v, setV] = useState(""); const [out, setOut] = useState(null); const [err, setErr] = useState(null);
  return (
    <Section title="Dry-run check" description="What the policies in force (and the dry-run policies) do to one value or operation at this node.">
      <Stack direction="row" spacing={1} alignItems="center">
        <TextField select size="small" label="Constraint" value={c} onChange={(e) => setC(e.target.value)} sx={{ minWidth: 340 }} inputProps={{ "aria-label": "Constraint" }}>
          {constraints.map((x) => <MenuItem key={x.name} value={cid(x.name)}>{cid(x.name)}</MenuItem>)}</TextField>
        <TextField size="small" label="Value (list constraints)" value={v} onChange={(e) => setV(e.target.value)} inputProps={{ "aria-label": "Value" }} />
        <Button variant="outlined" disabled={!c} onClick={async () => { try { setErr(null); setOut(await gov("gcp", "orgpolicy/check", { method: "POST", body: { node, constraint: c, value: v || undefined } })); } catch (e) { setErr(e); } }}>Check</Button>
      </Stack>
      {err && <ErrorAlert error={err} />}
      {out && <Alert sx={{ mt: 1 }} severity={out.wouldBlock ? "error" : out.dryRunWouldBlock ? "warning" : "success"} data-testid="check-result">
        {out.wouldBlock ? `Blocked now${out.reason ? ": " + out.reason : ""}.` : "Allowed now."} {out.dryRunWouldBlock ? `Dry run would block${out.dryRunReason ? ": " + out.dryRunReason : ""}.` : "Dry run would not block."}</Alert>}
    </Section>
  );
}

export default function Governance() {
  const notify = useNotify();
  const tree = useAsync(() => gov("gcp", "hierarchy", { query: { project: getProject() } }), []);
  const [node, setNode] = useState(null);
  const [tab, setTab] = useState(0);
  const [dlg, setDlg] = useState(null);
  const cur = node?.id || (tree.data ? "projects/" + ((function first(n) { return n.type === "project" ? n.id.slice(9) : (n.children.map(first).find(Boolean) || ""); })(tree.data)) : "");
  const org = tree.data?.id;
  const cons = useAsync(() => (org ? restJson("GET", `/v2/${org}/constraints`).then((r) => r.constraints || []) : Promise.resolve([])), [org]);
  const view = useAsync(() => (cur && cur !== "projects/" ? gov("gcp", "orgpolicy", { query: { node: cur } }) : Promise.resolve(null)), [cur]);
  const iam = useAsync(() => (cur && cur !== "projects/" ? gov("gcp", "iam-policies", { query: { node: cur } }) : Promise.resolve(null)), [cur]);
  const reload = () => { tree.reload(); view.reload(); iam.reload(); };
  const own = (c) => (view.data?.constraints || []).find((r) => r.constraint === c.name)?.levels.find((l) => l.node === cur);
  const rows = (cons.data || []).map((c) => ({ ...c, _view: (view.data?.constraints || []).find((r) => r.constraint === c.name), _own: own(c) }));
  return (
    <>
      <PageHeader title="Resource hierarchy & organization policies" />
      <ErrorAlert error={tree.error} title="Failed to load the hierarchy" />
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems="flex-start">
        <Box sx={{ minWidth: 300, maxWidth: 380 }}>
          <Section title="Hierarchy">{tree.data && <Tree node={tree.data} selected={cur} onSelect={setNode} />}</Section>
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle1" sx={{ mb: 1 }} data-testid="selected-node">Selected: <b>{cur}</b></Typography>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 1 }}>
            <Tab label="Constraints" /><Tab label="Inheritance" /><Tab label="IAM at this node" />
          </Tabs>
          {tab === 0 && (<>
            <Section title="Organization policy constraints" description="Predefined constraints (Org Policy v2). Set, change or reset the policy on the selected node.">
              <ErrorAlert error={cons.error} />
              <Box sx={{ overflowX: "auto" }}><ResourceTable resourceName="constraints" items={rows} rowKey={(c) => c.name} loading={cons.loading} filterPlaceholder="Filter constraints"
                columns={[
                  { id: "n", header: "Constraint", cell: (c) => <span title={c.description}>{c.displayName}<br /><Typography component="span" variant="caption" color="text.secondary">{c.name}</Typography></span> },
                  { id: "t", header: "Type", cell: (c) => (c.booleanConstraint ? "Boolean" : "List") },
                  { id: "e", header: "Effective here", cell: (c) => { const e = c._view?.effective; if (!e || e.default) return "Default (allow)"; return e.kind === "boolean" ? (e.enforce ? "Enforced" : "Not enforced") : e.denyAll ? "Deny all" : e.allowAll ? "Allow all" : `${(e.allowedValues || []).length} allowed, ${(e.deniedValues || []).length} denied`; } },
                  { id: "s", header: "Set at", cell: (c) => (c._view?.effective?.source || "-") },
                  { id: "v", header: "Enforced by Vyomi", cell: (c) => (c.vyomi?.enforcedBy ? "Yes" : "Evaluated only") },
                  { id: "a", header: "", cell: (c) => <Stack direction="row" spacing={1}>
                    <Button size="small" aria-label={`Manage policy ${cid(c.name)}`} onClick={() => setDlg({ c, existing: c._own && (c._own.spec || c._own.dryRunSpec) ? { spec: c._own.spec, dryRunSpec: c._own.dryRunSpec } : null })}>Manage policy</Button>
                    {c._own && (c._own.spec || c._own.dryRunSpec) && <Button size="small" color="error" aria-label={`Delete policy ${cid(c.name)}`} onClick={async () => { try { await restJson("DELETE", `/v2/${cur}/policies/${cid(c.name)}`); notify.success("Policy deleted."); reload(); } catch (e) { notify.error(e); } }}>Delete</Button>}</Stack> },
                ]} /></Box>
            </Section>
            <CheckPanel node={cur} constraints={cons.data || []} />
          </>)}
          {tab === 1 && (
            <Section title="Inheritance" description="Every constraint with a policy on this node or an ancestor: the rule at each level (root first) and the effective result.">
              <ErrorAlert error={view.error} />
              {(view.data?.constraints || []).length === 0 && <Typography color="text.secondary">No organization policies apply to this node.</Typography>}
              {(view.data?.constraints || []).map((r) => (
                <Box key={r.constraint} sx={{ mb: 2 }} data-constraint={r.constraint}>
                  <Typography variant="subtitle2">{r.displayName} <Chip size="small" label={r.kind === "boolean" ? (r.effective.enforce ? "Enforced" : "Not enforced") : "List"} /> {r.dryRunEffective && <Chip size="small" color="warning" label="dry run" />}</Typography>
                  <ResourceTable resourceName="levels" items={r.levels} rowKey={(l) => l.node} filterPlaceholder="" columns={[
                    { id: "n", header: "Node", cell: (l) => l.node },
                    { id: "s", header: "Policy", cell: (l) => (l.spec ? JSON.stringify(l.spec.reset ? { reset: true } : { rules: l.spec.rules, inheritFromParent: l.spec.inheritFromParent }) : "inherited") },
                    { id: "d", header: "Dry run", cell: (l) => (l.dryRunSpec ? JSON.stringify({ rules: l.dryRunSpec.rules }) : "-") },
                  ]} />
                </Box>))}
            </Section>)}
          {tab === 2 && (
            <Section title="IAM policies on this node and its ancestors" description="Allow bindings, deny policies and the Principal Access Boundary in the evaluation order PAB > deny > allow.">
              <ErrorAlert error={iam.error} />
              <ResourceTable resourceName="levels" items={iam.data?.levels || []} rowKey={(l) => l.node} filterPlaceholder="" columns={[
                { id: "n", header: "Node", cell: (l) => l.node }, { id: "a", header: "Allow bindings", cell: (l) => l.allowBindings },
                { id: "d", header: "Deny policies", cell: (l) => (l.denyPolicies.join(", ") || "-") }]} />
              <Typography sx={{ mt: 1 }} variant="body2">Principal Access Boundary: {(iam.data?.pabPolicies || []).length} polic{(iam.data?.pabPolicies || []).length === 1 ? "y" : "ies"}, {(iam.data?.pabBindings || []).length} binding(s). <a href="#/iam-admin/principal-access-boundary">Manage</a> {"·"} <a href="#/iam-admin/iam/deny">Deny policies</a></Typography>
            </Section>)}
        </Box>
      </Stack>
      {dlg && <PolicyDialog node={cur} constraint={dlg.c} existing={dlg.existing} onClose={() => setDlg(null)} onSaved={reload} />}
    </>
  );
}
