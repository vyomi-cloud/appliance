/* APIs panel: "Add API" quick-start tiles (HTTP is real; every other creation path is an
 * honest gap) + the APIs grid (real ARM sub-resource of the service). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Input, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorBar, Loading, NotSimulated } from "../../kit/common.jsx";
import * as api from "./api.js";

const QUICK_START = [
  { group: "Define a new API", items: ["HTTP", "WebSocket", "GraphQL", "gRPC"] },
  { group: "Create from definition", items: ["OpenAPI", "WSDL", "WADL"] },
  { group: "Create from Azure resource", items: ["API App", "Function App", "Container App", "Logic App"] },
];

export default function Apis({ rg, svc, self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.Apis.list(rg, svc), [rg, svc]);
  const [filter, setFilter] = useState("");
  const [gap, setGap] = useState(null);
  const f = filter.trim().toLowerCase();
  const rows = (data || []).filter((r) => !f || r.name.toLowerCase().includes(f) || (r.properties?.displayName || "").toLowerCase().includes(f));
  return (
    <>
      <div className="vy-panel-title">{svc} | APIs</div>
      {QUICK_START.map((g) => (
        <section key={g.group} className="vy-section" style={{ marginBottom: 8 }}>
          <h3>{g.group}</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {g.items.map((it) => it === "HTTP"
              ? <Button key={it} as="a" href={`${self}/apis/create`}>{it}</Button>
              : <Button key={it} onClick={() => setGap(it)}>{it}</Button>)}
          </div>
        </section>
      ))}
      <div className="vy-cmdbar" role="toolbar" aria-label="APIs commands">
        <ToolbarButton icon={<Add20Regular />} as="a" href={`${self}/apis/create`}>Add API</ToolbarButton>
        <ToolbarButton icon={<ArrowClockwise20Regular />} onClick={reload}>Refresh</ToolbarButton>
      </div>
      <Input size="small" style={{ width: 260, margin: "8px 0" }} placeholder="Search APIs" value={filter} onChange={(_, d) => setFilter(d.value)} aria-label="Search APIs" />
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <table className="vy-grid" style={{ width: "100%" }}>
          <thead><tr><th>Name</th><th>Display name</th><th>Revision</th><th>API URL suffix</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td>{r.properties?.displayName}</td>
                <td>{r.properties?.apiRevision || "1"}</td>
                <td>{r.properties?.path}</td>
                <td><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Delete ${r.name}`} onClick={async () => {
                  await api.Apis.remove(rg, svc, r.name);
                  notify.success(`API '${r.name}' was deleted.`, "Delete succeeded");
                  reload();
                }} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!loading && !rows.length && <div className="vy-empty"><h3>No APIs to display</h3></div>}

      <Dialog open={!!gap} onOpenChange={(_, d) => !d.open && setGap(null)}>
        <DialogSurface aria-label={gap || ""}>
          <DialogBody>
            <DialogTitle>{gap}</DialogTitle>
            <DialogContent><NotSimulated feature={`Creating an API from ${gap}`} /></DialogContent>
            <DialogActions><Button onClick={() => setGap(null)}>Close</Button></DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}
