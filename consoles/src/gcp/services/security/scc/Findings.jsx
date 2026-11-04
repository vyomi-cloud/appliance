/* Security Command Center: findings (severity summary, filter grammar, mute/state actions), sources and mute rules. */
import { useState } from "react";
import { Button, Chip, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import RefreshIcon from "@mui/icons-material/esm/Refresh.js";
import { useAsync } from "../../../../common/useAsync.js";
import { useNotify } from "../../../../common/notify.jsx";
import ResourceTable from "../../../kit/ResourceTable.jsx";
import FormDialog from "../../../kit/FormDialog.jsx";
import { PageHeader } from "../../../kit/common.jsx";
import { CapabilityContainer } from "../../../kit/Capability.jsx";
import { useProject } from "../../../project.js";
import * as api from "./api.js";

const SEV = { CRITICAL: "error", HIGH: "error", MEDIUM: "warning", LOW: "default" };

export default function Findings({ query }) {
  const tab = ["sources", "mute"].includes(query.tab) ? query.tab : "findings";
  const project = useProject();
  const notify = useNotify();
  const [filter, setFilter] = useState('state="ACTIVE" AND NOT mute="MUTED"');
  const [applied, setApplied] = useState(filter);
  const f = useAsync(() => api.listFindings(applied), [project, applied]);
  const src = useAsync(api.listSources, [project]);
  const mutes = useAsync(api.listMuteConfigs, [project]);
  const [dlg, setDlg] = useState(false);
  const act = async (fn, msg) => { try { await fn(); notify.success(msg); } catch (e) { notify.error(e.message); } f.reload(); mutes.reload(); };
  const by = (f.data || []).reduce((m, x) => ({ ...m, [x.severity]: (m[x.severity] || 0) + 1 }), {});

  return (
    <>
      <PageHeader title="Security Command Center" actions={<Button startIcon={<RefreshIcon />} onClick={() => { f.reload(); src.reload(); mutes.reload(); }}>Refresh</Button>} />
      <Tabs value={tab} onChange={(_, t) => { location.hash = "#/security/scc" + (t === "findings" ? "" : `?tab=${t}`); }} sx={{ borderBottom: 1, borderColor: "divider", mb: 2.5 }}>
        <Tab value="findings" label="Findings" /><Tab value="sources" label="Sources" /><Tab value="mute" label="Mute rules" />
      </Tabs>
      {tab === "findings" && (
        <CapabilityContainer id="gcp.scc.sources_findings" title="Findings">
          <Stack direction="row" spacing={1} sx={{ px: 2.5, pb: 1.5 }} data-testid="scc-summary">
            {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => <Chip key={s} color={SEV[s]} variant={by[s] ? "filled" : "outlined"} label={`${s}: ${by[s] || 0}`} />)}
          </Stack>
          <Stack direction="row" spacing={1} sx={{ px: 2.5, pb: 1.5 }}>
            <TextField size="small" fullWidth label="Findings query" value={filter} onChange={(e) => setFilter(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setApplied(filter)} />
            <Button variant="contained" onClick={() => setApplied(filter)}>Apply</Button>
          </Stack>
          <ResourceTable resourceName="findings" items={f.data || []} loading={f.loading} error={f.error} onRetry={f.reload} rowKey={(x) => x.name}
            columns={[
              { id: "sev", header: "Severity", sortValue: (x) => x.severity, cell: (x) => <Chip size="small" color={SEV[x.severity]} label={x.severity} /> },
              { id: "cat", header: "Category", cell: (x) => x.category },
              { id: "res", header: "Resource", cell: (x) => x.resourceName },
              { id: "src", header: "Source", cell: (x) => x.name.split("/sources/")[1]?.split("/")[0] },
              { id: "cls", header: "Class", cell: (x) => x.findingClass },
              { id: "state", header: "State", cell: (x) => `${x.state}${x.mute === "MUTED" ? " (muted)" : ""}` },
              { id: "act", header: "Actions", cell: (x) => <Stack direction="row" spacing={0.5}>
                <Button size="small" onClick={() => act(() => api.setMute(x.name, x.mute === "MUTED" ? "UNMUTED" : "MUTED"), x.mute === "MUTED" ? "Unmuted" : "Muted")}>{x.mute === "MUTED" ? "Unmute" : "Mute"}</Button>
                <Button size="small" onClick={() => act(() => api.setState(x.name, x.state === "ACTIVE" ? "INACTIVE" : "ACTIVE"), "State updated")}>{x.state === "ACTIVE" ? "Mark inactive" : "Mark active"}</Button></Stack> },
            ]}
            empty={<Typography variant="body2" color="text.secondary">No findings match this query.</Typography>} />
        </CapabilityContainer>
      )}
      {tab === "sources" && (
        <CapabilityContainer id="gcp.scc.sources_findings" title="Sources">
          <ResourceTable resourceName="sources" items={src.data || []} loading={src.loading} error={src.error} onRetry={src.reload} rowKey={(s) => s.name}
            columns={[{ id: "n", header: "Name", cell: (s) => s.displayName }, { id: "d", header: "Description", cell: (s) => s.description }, { id: "id", header: "Source ID", cell: (s) => s.name.split("/").pop() }]} />
        </CapabilityContainer>
      )}
      {tab === "mute" && (
        <CapabilityContainer id="gcp.scc.mute_configs" title="Mute rules" actions={<Button size="small" onClick={() => setDlg(true)}>Create mute rule</Button>}>
          <ResourceTable resourceName="mute rules" items={mutes.data || []} loading={mutes.loading} error={mutes.error} onRetry={mutes.reload} rowKey={(m) => m.name}
            columns={[{ id: "n", header: "Rule", cell: (m) => m.name.split("/").pop() }, { id: "f", header: "Filter", cell: (m) => m.filter }, { id: "d", header: "Description", cell: (m) => m.description },
              { id: "a", header: "Actions", cell: (m) => <Button size="small" color="error" onClick={() => act(() => api.deleteMuteConfig(m.name), "Deleted")}>Delete</Button> }]}
            empty={<Typography variant="body2" color="text.secondary">No mute rules.</Typography>} />
        </CapabilityContainer>
      )}
      <FormDialog open={dlg} title="Create mute rule" onClose={(ok) => { setDlg(false); if (ok) mutes.reload(); }}
        onSubmit={async (v) => { await api.createMuteConfig(v.id, { filter: v.filter, description: v.description, type: "STATIC" }); notify.success("Mute rule created"); }}
        fields={[{ key: "id", label: "Rule ID" }, { key: "filter", label: "Filter", default: 'severity="LOW"' }, { key: "description", label: "Description" }]} />
    </>
  );
}
