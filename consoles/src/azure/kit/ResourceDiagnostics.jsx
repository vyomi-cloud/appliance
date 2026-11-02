/* Diagnostic settings blade body shared by blades that have no panel of their own: real
 * Microsoft.Insights/diagnosticSettings extension resources (core/azure_monitor_core.py)
 * scoped to `resPath`, destination = a Vyomi Log Analytics workspace. */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { armType } from "./arm.js";
import BrowseGrid from "./BrowseGrid.jsx";
import { CapabilityContainer } from "./Capability.jsx";

const DIAG_API = "2021-05-01-preview";
const WORKSPACES = armType("Microsoft.OperationalInsights", "workspaces", "2022-10-01");
const diagPath = (resPath) => `${resPath}/providers/Microsoft.Insights/diagnosticSettings`;

export default function ResourceDiagnostics({ resPath, name, capId }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(async () => (await restJson("GET", diagPath(resPath), { query: { "api-version": DIAG_API } })).value || [], [resPath]);
  const workspaces = useAsync(() => WORKSPACES.list(), []);
  const [adding, setAdding] = useState(false);
  const [dsName, setDsName] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const create = async () => {
    setBusy(true);
    try {
      await restJson("PUT", `${diagPath(resPath)}/${encodeURIComponent(dsName)}`, { query: { "api-version": DIAG_API },
        body: { properties: { workspaceId: workspace, logs: [{ categoryGroup: "allLogs", enabled: true }], metrics: [{ category: "AllMetrics", enabled: true }] } } });
      notify.success(`Diagnostic setting '${dsName}' was created.`, "Save succeeded");
      setAdding(false); setDsName(""); reload();
    } catch (e) { notify.error(e, "Save failed"); }
    finally { setBusy(false); }
  };
  return (
    <>
      <div className="vy-panel-title">{name} | Diagnostic settings</div>
      <CapabilityContainer id={capId} title="Diagnostic settings">
        <p style={{ fontSize: 13 }}>Diagnostic settings specify a destination for platform logs and metrics from this resource.</p>
        <BrowseGrid
          resourceName="diagnostic setting" items={data || []} loading={loading} error={error} onRefresh={reload}
          onCreate={() => setAdding(true)}
          onDelete={async (rows) => { for (const r of rows) await restJson("DELETE", `${diagPath(resPath)}/${encodeURIComponent(r.name)}`, { query: { "api-version": DIAG_API } }); notify.success("Diagnostic setting(s) deleted.", "Delete succeeded"); reload(); }}
          columns={[
            { key: "name", label: "Name" },
            { key: "dest", label: "Destination details", value: (s) => (s.properties?.workspaceId ? "Log Analytics workspace" : "--") },
            { key: "logs", label: "Log categories", value: (s) => (s.properties?.logs || []).filter((l) => l.enabled).length },
            { key: "metrics", label: "Metric categories", value: (s) => (s.properties?.metrics || []).filter((m) => m.enabled).length },
          ]}
        />
      </CapabilityContainer>
      <Dialog open={adding} onOpenChange={(_, d) => !d.open && setAdding(false)}>
        <DialogSurface aria-label="Add diagnostic setting">
          <DialogBody>
            <DialogTitle>Add diagnostic setting</DialogTitle>
            <DialogContent>
              <Field label="Diagnostic setting name" required><Input value={dsName} onChange={(_, d) => setDsName(d.value)} /></Field>
              <Field label="Log Analytics workspace" required>
                {(workspaces.data || []).length ? (
                  <Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
                    <option value="">Select a workspace...</option>
                    {workspaces.data.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </Select>
                ) : <p style={{ fontSize: 13 }}>No Log Analytics workspace yet. Create one from the Log Analytics console.</p>}
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!dsName || !workspace || busy} onClick={create}>{busy ? "Saving..." : "Save"}</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}
