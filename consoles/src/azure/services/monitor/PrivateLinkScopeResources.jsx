/* A private link scope's own "Azure Monitor Resources" blade — list / add / remove the
 * Microsoft.Insights/privateLinkScopes/{name}/scopedResources extension resources that link a
 * Log Analytics workspace INTO the scope (reached from the row in PrivateLinkScopes.jsx). */
import { useEffect, useState } from "react";
import { Button, Select } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { deleteScopedResource, listScopedResources, listWorkspaces, putScopedResource } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

export default function PrivateLinkScopeResources() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const rg = params.get("rg") || "";
  const scopeName = params.get("name") || "";
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [workspaces, setWorkspaces] = useState([]);
  const [workspace, setWorkspace] = useState("");

  const load = () => { setError(null); listScopedResources(rg, scopeName).then(setItems).catch(setError); };
  useEffect(load, [rg, scopeName]);
  useEffect(() => { listWorkspaces().then((ws) => { setWorkspaces(ws); setWorkspace(ws[0]?.id || ""); }).catch(() => setWorkspaces([])); }, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "linked", label: "Linked resource", value: (r) => r.properties.linkedResourceId.split("/").pop() },
    { key: "type", label: "Resource type", value: (r) => r.properties.linkedResourceId.split("/providers/")[1]?.split("/").slice(0, 2).join("/") || "--" },
  ];

  return (
    <MonitorShell active="privatelinkscopes" pageTitle={`Azure Monitor Resources | ${scopeName}`}>
      <p>Azure Monitor Private Link Scope <b>{scopeName}</b></p>
      <CapabilityContainer id="azure.monitor.private_link_scopes" title="Azure Monitor Resources">
        {items === null ? <Loading /> : (
          <BrowseGrid resourceName="resource" items={items} columns={columns} loading={false} error={error}
            onRefresh={load} onCreate={() => setAdding(true)}
            onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteScopedResource(rg, scopeName, r.name))); load(); }}
            csvName="scoped-resources.csv" />
        )}
        {adding && (
          <section className="vy-form-section">
            <h3>Add a resource to the scope</h3>
            <div className="vy-form-row"><label>Log Analytics workspace</label>
              {workspaces.length ? (
                <Select value={workspace} onChange={(_, d) => setWorkspace(d.value)} aria-label="Log Analytics workspace">
                  {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </Select>
              ) : <p>No Log Analytics workspace yet. <a href="#/monitor/createloganalyticsworkspace">Create one</a></p>}
            </div>
            <div className="vy-cmdbar">
              <Button appearance="primary" disabled={!workspace} onClick={async () => {
                const name = workspace.split("/").pop();
                await putScopedResource(rg, scopeName, name, workspace);
                setAdding(false); load();
              }}>Save</Button>
              <Button onClick={() => setAdding(false)}>Cancel</Button>
            </div>
          </section>
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
