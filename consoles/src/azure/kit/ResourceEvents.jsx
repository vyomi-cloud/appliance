/* Event Grid subscriptions on a resource's own system events (storage, key vault, App Configuration,
 * API Management, resource group): Microsoft.EventGrid/eventSubscriptions scoped to the resource id
 * (core/azure_eventgrid_core.py scoped_dispatch). Includes a simulator-internal "Send test event". */
import { useState } from "react";
import { Button, Checkbox, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, InfoBar } from "./common.jsx";

const AV = "2022-06-15";
export const EVENT_TYPES = {
  storage: ["Microsoft.Storage.BlobCreated", "Microsoft.Storage.BlobDeleted", "Microsoft.Storage.BlobRenamed", "Microsoft.Storage.DirectoryCreated", "Microsoft.Storage.DirectoryDeleted"],
  keyvault: ["Microsoft.KeyVault.SecretNewVersionCreated", "Microsoft.KeyVault.SecretNearExpiry", "Microsoft.KeyVault.SecretExpired", "Microsoft.KeyVault.KeyNewVersionCreated", "Microsoft.KeyVault.KeyNearExpiry", "Microsoft.KeyVault.KeyExpired", "Microsoft.KeyVault.CertificateNewVersionCreated", "Microsoft.KeyVault.CertificateNearExpiry", "Microsoft.KeyVault.CertificateExpired"],
  appconfiguration: ["Microsoft.AppConfiguration.KeyValueModified", "Microsoft.AppConfiguration.KeyValueDeleted", "Microsoft.AppConfiguration.SnapshotCreated", "Microsoft.AppConfiguration.SnapshotModified"],
  apim: ["Microsoft.ApiManagement.APICreated", "Microsoft.ApiManagement.APIUpdated", "Microsoft.ApiManagement.APIDeleted", "Microsoft.ApiManagement.ProductCreated", "Microsoft.ApiManagement.ProductUpdated", "Microsoft.ApiManagement.ProductDeleted", "Microsoft.ApiManagement.UserCreated", "Microsoft.ApiManagement.SubscriptionCreated"],
  resourcegroup: ["Microsoft.Resources.ResourceWriteSuccess", "Microsoft.Resources.ResourceDeleteSuccess", "Microsoft.Resources.ResourceActionSuccess", "Microsoft.Resources.ResourceWriteFailure"],
};
const base = (scopeId) => `${scopeId}/providers/Microsoft.EventGrid/eventSubscriptions`;

export default function ResourceEvents({ scopeId, kind, title = "Events" }) {
  const notify = useNotify();
  const types = EVENT_TYPES[kind] || [];
  const subs = useAsync(async () => {
    const rows = (await restJson("GET", base(scopeId), { query: { "api-version": AV } })).value || [];
    return Promise.all(rows.map(async (r) => ({ ...r, _d: await restJson("GET", `${base(scopeId)}/${r.name}/deliveryStatus`, { query: { "api-version": AV } }).catch(() => ({})) })));
  }, [scopeId]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", types: new Set(), endpointType: "WebHook", endpoint: "" });
  const [test, setTest] = useState(types[0] || "");
  const create = async () => {
    const dest = f.endpointType === "ServiceBusQueue"
      ? { endpointType: "ServiceBusQueue", properties: { queueName: f.endpoint } }
      : { endpointType: f.endpointType, properties: { endpointUrl: f.endpoint } };
    try {
      await restJson("PUT", `${base(scopeId)}/${encodeURIComponent(f.name)}`, { query: { "api-version": AV },
        body: { properties: { destination: dest, filter: f.types.size ? { includedEventTypes: [...f.types] } : {} } } });
      notify.success(`Event subscription '${f.name}' was created.`, "Create event subscription");
      setOpen(false); setF({ name: "", types: new Set(), endpointType: "WebHook", endpoint: "" }); subs.reload();
    } catch (e) { notify.error(e, "Creating the event subscription failed"); }
  };
  const sendTest = async () => {
    try {
      const r = await restJson("POST", `${base(scopeId)}/simulateEvent`, { query: { "api-version": AV }, body: { eventType: test, subject: scopeId, data: { api: "Simulated" } } });
      notify.success(`${test} raised: ${(r.deliveries || []).length} matching subscription(s).`, "Test event sent"); subs.reload();
    } catch (e) { notify.error(e, "Sending the test event failed"); }
  };
  const remove = async (n) => { try { await restJson("DELETE", `${base(scopeId)}/${encodeURIComponent(n)}`, { query: { "api-version": AV } }); subs.reload(); } catch (e) { notify.error(e, "Delete failed"); } };
  const rows = subs.data || [];
  return (
    <CapabilityContainer id="azure.eventgrid.resourceevents" title={title}>
      <ErrorBar error={subs.error} />
      <InfoBar>Event subscriptions on this resource's system events. Event types are validated against what this resource type raises.</InfoBar>
      <div style={{ display: "flex", gap: 8, margin: "8px 0", alignItems: "center", flexWrap: "wrap" }}>
        <Button appearance="primary" onClick={() => setOpen(true)} aria-label="Add event subscription">+ Event Subscription</Button>
        <Select value={test} onChange={(_, d) => setTest(d.value)} aria-label="Test event type" style={{ minWidth: 280 }}>{types.map((t) => <option key={t} value={t}>{t}</option>)}</Select>
        <Button onClick={sendTest} aria-label="Send test event">Send test event</Button>
        <Button onClick={subs.reload}>Refresh</Button>
      </div>
      <table className="vy-grid" aria-label="Event subscriptions">
        <thead><tr><th>Name</th><th>Event types</th><th>Endpoint type</th><th>Matched</th><th>Delivered</th><th>Failed</th><th /></tr></thead>
        <tbody>
          {rows.length ? rows.map((r) => (
            <tr key={r.name}><td>{r.name}</td><td>{(r.properties?.filter?.includedEventTypes || ["All"]).join(", ")}</td><td>{r.properties?.destination?.endpointType}</td>
              <td>{r._d?.matched ?? 0}</td><td>{r._d?.delivered ?? 0}</td><td>{r._d?.failed ?? 0}</td>
              <td><Button size="small" aria-label={`Delete event subscription ${r.name}`} onClick={() => remove(r.name)}>Delete</Button></td></tr>
          )) : <tr><td colSpan={7} className="vy-muted">No event subscriptions.</td></tr>}
        </tbody>
      </table>
      <Dialog open={open} onOpenChange={(_, d) => !d.open && setOpen(false)}>
        <DialogSurface aria-label="Create event subscription"><DialogBody>
          <DialogTitle>Create event subscription</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <Field label="Name" required><Input value={f.name} onChange={(_, d) => setF((x) => ({ ...x, name: d.value }))} aria-label="Event subscription name" /></Field>
            <Field label="Filter to event types (none = all)">
              <div style={{ display: "flex", flexDirection: "column" }}>{types.map((t) => (
                <Checkbox key={t} label={t} checked={f.types.has(t)} onChange={(_, d) => setF((x) => { const n = new Set(x.types); d.checked ? n.add(t) : n.delete(t); return { ...x, types: n }; })} />
              ))}</div></Field>
            <Field label="Endpoint type"><Select value={f.endpointType} onChange={(_, d) => setF((x) => ({ ...x, endpointType: d.value }))} aria-label="Endpoint type">
              <option value="WebHook">Web Hook</option><option value="ServiceBusQueue">Service Bus Queue</option><option value="StorageQueue">Storage Queue</option><option value="EventHub">Event Hub</option></Select></Field>
            <Field label={f.endpointType === "ServiceBusQueue" ? "Queue name" : "Endpoint"} required><Input value={f.endpoint} onChange={(_, d) => setF((x) => ({ ...x, endpoint: d.value }))} aria-label="Endpoint" /></Field>
          </div></DialogContent>
          <DialogActions><Button appearance="primary" disabled={!f.name.trim() || !f.endpoint.trim()} onClick={create}>Create</Button><Button onClick={() => setOpen(false)}>Cancel</Button></DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}
