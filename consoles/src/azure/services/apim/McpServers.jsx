/* MCP Servers panel: a real API (service/apis, apiType "mcp") filtered to that type — the
 * same ARM sub-resource APIs uses, just a different view (azure.apim.mcpservers). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import * as api from "./api.js";

const ID_RE = /^[a-zA-Z0-9][a-zA-Z0-9-]{0,255}$/;

export default function McpServers({ rg, svc }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.Apis.list(rg, svc), [rg, svc]);
  const [add, setAdd] = useState(false);
  const rows = (data || []).filter((r) => r.properties?.apiType === "mcp");
  return (
    <CapabilityContainer id="azure.apim.mcpservers" title={`${svc} | MCP Servers`}>
      <p style={{ fontSize: 13 }}>Expose a backend as a Model Context Protocol server through this gateway.</p>
      <div className="vy-cmdbar" role="toolbar" aria-label="MCP Servers commands">
        <ToolbarButton icon={<Add20Regular />} onClick={() => setAdd(true)}>Create MCP server</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <table className="vy-grid" style={{ width: "100%" }}>
          <thead><tr><th>Name</th><th>Display name</th><th>Backend URL</th><th>API URL suffix</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td>{r.properties?.displayName}</td>
                <td>{r.properties?.serviceUrl || "--"}</td>
                <td>{r.properties?.path}</td>
                <td><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Delete ${r.name}`} onClick={async () => {
                  await api.Apis.remove(rg, svc, r.name);
                  notify.success(`MCP server '${r.name}' was deleted.`, "Delete succeeded");
                  reload();
                }} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!loading && !rows.length && <div className="vy-empty"><h3>No MCP servers to display</h3></div>}
      <AddMcpServerDialog open={add} onClose={() => setAdd(false)} existing={data || []}
        onCreate={async (id, body) => { await api.Apis.put(rg, svc, id, body); reload(); }} />
    </CapabilityContainer>
  );
}

function AddMcpServerDialog({ open, onClose, onCreate, existing }) {
  const notify = useNotify();
  const [f, setF] = useState({ displayName: "", name: "", serviceUrl: "", path: "" });
  const [busy, setBusy] = useState(false);
  const valid = ID_RE.test(f.name) && f.displayName.trim() && !existing.some((a) => a.name.toLowerCase() === f.name.toLowerCase());
  const go = async () => {
    setBusy(true);
    try {
      await onCreate(f.name, { properties: {
        displayName: f.displayName, serviceUrl: f.serviceUrl || undefined, path: f.path, apiType: "mcp",
        protocols: ["https"], apiRevision: "1", subscriptionRequired: true, isCurrent: true,
      } });
      notify.success(`MCP server '${f.displayName}' was created.`, "Create succeeded");
      setF({ displayName: "", name: "", serviceUrl: "", path: "" });
      onClose();
    } catch (e) { notify.error(e, "Create failed"); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Create MCP server">
        <DialogBody>
          <DialogTitle>Create MCP server</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Display name" required><Input value={f.displayName} onChange={(_, d) => setF((x) => ({ ...x, displayName: d.value, name: x.name || d.value.toLowerCase().replace(/[^a-z0-9-]+/g, "-") }))} aria-label="Display name" /></Field>
              <Field label="Name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Name" /></Field>
              <Field label="Backend URL"><Input value={f.serviceUrl} onChange={(_, d) => setF((x) => ({ ...x, serviceUrl: d.value }))} placeholder="https://..." aria-label="Backend URL" /></Field>
              <Field label="API URL suffix"><Input value={f.path} onChange={(_, d) => setF((x) => ({ ...x, path: d.value }))} aria-label="API URL suffix" /></Field>
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!valid || busy} onClick={go}>Create</Button>
            <Button onClick={onClose}>Cancel</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
