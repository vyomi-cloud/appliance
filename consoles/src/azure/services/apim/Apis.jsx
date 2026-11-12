/* APIs panel: "Add API" quick-start tiles — HTTP/WebSocket/GraphQL/gRPC are real (the same
 * wizard, parameterized by apiType — CreateHttpApi.jsx); importing from a definition file or
 * an Azure resource, and restricting an API to specific gateways, are honest gaps — + the
 * APIs grid (real ARM sub-resource of the service). */
import { useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, ToolbarButton } from "@fluentui/react-components";
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular, PlugConnected20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { ErrorBar, Loading, NotSimulated } from "../../kit/common.jsx";
import * as api from "./api.js";

const QUICK_START = [
  { group: "Define a new API", items: ["HTTP", "WebSocket", "GraphQL", "gRPC"] },
  { group: "Create from definition", items: ["OpenAPI", "WSDL", "WADL"] },
  { group: "Create from Azure resource", items: ["API App", "Function App", "Container App", "Logic App"] },
];
const REAL_TYPES = { HTTP: "http", WebSocket: "websocket", GraphQL: "graphql", gRPC: "grpc" };

export default function Apis({ rg, svc, self }) {
  const notify = useNotify();
  const { data, loading, error, reload } = useAsync(() => api.Apis.list(rg, svc), [rg, svc]);
  const subs = useAsync(() => api.Subscriptions.list(rg, svc), [rg, svc]);
  const [filter, setFilter] = useState("");
  const [gap, setGap] = useState(null);
  const [test, setTest] = useState(null);
  const f = filter.trim().toLowerCase();
  const rows = (data || []).filter((r) => !f || r.name.toLowerCase().includes(f) || (r.properties?.displayName || "").toLowerCase().includes(f));
  return (
    <>
      <div className="vy-panel-title">{svc} | APIs</div>
      {QUICK_START.map((g) => (
        <section key={g.group} className="vy-section" style={{ marginBottom: 8 }}>
          <h3>{g.group}</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {g.items.map((it) => REAL_TYPES[it]
              ? <Button key={it} as="a" href={`${self}/apis/create${REAL_TYPES[it] === "http" ? "" : `/${REAL_TYPES[it]}`}`}>{it}</Button>
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
          <thead><tr><th>Name</th><th>Display name</th><th>Type</th><th>Revision</th><th>API URL suffix</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>{r.name}</td>
                <td>{r.properties?.displayName}</td>
                <td>{r.properties?.apiType || "http"}</td>
                <td>{r.properties?.apiRevision || "1"}</td>
                <td>{r.properties?.path}</td>
                <td>
                  <Button appearance="subtle" size="small" icon={<PlugConnected20Regular />} aria-label={`Test ${r.name}`} onClick={() => setTest(r)} />
                  <Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Delete ${r.name}`} onClick={async () => {
                    await api.Apis.remove(rg, svc, r.name);
                    notify.success(`API '${r.name}' was deleted.`, "Delete succeeded");
                    reload();
                  }} />
                </td>
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
      <TestConnectionDialog api={test} onClose={() => setTest(null)} rg={rg} svc={svc} subscriptions={subs.data || []} />
    </>
  );
}

// Replays the gateway's real client-TLS and subscription-key admission checks (see
// core/azure_arm_core.AzureArm._apim_test_connect) — so toggling Protocols + ciphers
// (azure.apim.service.protocols) has a genuine, observable effect here.
function TestConnectionDialog({ api: a, onClose, rg, svc, subscriptions }) {
  const [protocol, setProtocol] = useState("tls12");
  const [subscriptionKey, setSubscriptionKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const go = async () => {
    setBusy(true); setResult(null);
    try {
      const r = await api.testConnect(rg, svc, a.name, { protocol, subscriptionKey });
      setResult({ ok: true, message: `${r.message} (subscription: ${r.subscriptionId})` });
    } catch (e) { setResult({ ok: false, message: e.message }); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={!!a} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Test connection">
        <DialogBody>
          <DialogTitle>Test connection{a ? ` — ${a.name}` : ""}</DialogTitle>
          <DialogContent>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Field label="Client TLS protocol">
                <Select value={protocol} onChange={(_, d) => { setProtocol(d.value); setResult(null); }} aria-label="Client TLS protocol">
                  {api.CLIENT_PROTOCOLS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </Select>
              </Field>
              <Field label="Subscription key">
                <Select value={subscriptionKey} onChange={(_, d) => { setSubscriptionKey(d.value); setResult(null); }} aria-label="Subscription key">
                  <option value="">(none)</option>
                  {subscriptions.map((s) => <option key={s.name} value={s.properties?.primaryKey}>{s.properties?.displayName || s.name}</option>)}
                </Select>
              </Field>
              {result && <ErrorBar error={result.ok ? null : { message: result.message }} />}
              {result?.ok && <p style={{ fontSize: 13, color: "var(--colorPaletteGreenForeground1)" }}>{result.message}</p>}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy} onClick={go}>Send</Button>
            <Button onClick={onClose}>Close</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
