/* Support + Troubleshooting / New support request, shared by every Azure blade: real
 * Microsoft.Support/supportTickets (core/azure_support_core.py) — tickets are filed with Vyomi
 * Support. Create (with the real service / problem-type pickers), list, reply, change severity, close. */
import { useState } from "react";
import { Button, Dropdown, Field, Input, Option, Select, Textarea } from "@fluentui/react-components";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { restJson } from "../../common/wire.js";
import { CapabilityContainer } from "./Capability.jsx";
import { ErrorBar, InfoBar, KV, Loading, fmtDate } from "./common.jsx";
import { useSubscription } from "./subscription.js";

const AV = "2020-04-01";
const q = { "api-version": AV };
const ROLE = "Microsoft.Support";
const SEVERITY = [["Minimal", "C - Minimal impact"], ["Moderate", "B - Moderate impact"], ["Critical", "A - Critical impact"]];
// ARM provider namespace of the resource the panel sits on -> support service key.
const SERVICE_HINT = { acr: "Container Registry", aks: "Kubernetes Service (AKS)", apim: "API Management", appconfiguration: "App Configuration",
  appservices: "App Service and Function Apps", functionapp: "App Service and Function Apps", cognitiveservices: "Azure AI services", cosmos: "Azure Cosmos DB",
  cost: "Cost Management", keyvaults: "Key Vault", monitor: "Azure Monitor", nsgs: "Virtual Network and security groups", vnets: "Virtual Network and security groups",
  resourcegroups: "Resource groups and deployments", servicebus: "Service Bus", sql: "Azure SQL Database", storage: "Storage accounts", vms: "Virtual machines",
  eventgrid: "Event Grid", subscriptions: "Subscription management" };

const Pre = { whiteSpace: "pre-wrap", fontSize: 13, margin: "4px 0" };

/** resourceId: the resource the panel sits on (optional; becomes technicalTicketDetails). service: SERVICE_HINT key. */
export default function SupportPanel({ resourceId, name, service, title, capabilityId }) {
  const { id: sub } = useSubscription();
  const base = `/subscriptions/${sub}/providers/${ROLE}`;
  const notify = useNotify();
  const list = useAsync(async () => (await restJson("GET", `${base}/supportTickets`, { query: q })).value || [], [sub]);
  const [view, setView] = useState(null);   // ticket name | "new" | null
  const rows = list.data || [];
  return (
    <>
      <div className="vy-panel-title">{title || (name ? `${name} | Support + Troubleshooting` : "New support request")}</div>
      <CapabilityContainer id={capabilityId || "azure.common.support"} title="Support requests">
        <InfoBar>Support requests are filed with Vyomi Support. {resourceId ? "This resource is attached to new requests." : ""}</InfoBar>
        <ErrorBar error={list.error} />
        {view === "new"
          ? <NewRequest base={base} resourceId={resourceId} service={service} onDone={(n) => { list.reload(); setView(n || null); }} />
          : view
            ? <Ticket base={base} name={view} onBack={() => { list.reload(); setView(null); }} />
            : (
              <>
                <div style={{ display: "flex", gap: 8, margin: "8px 0" }}>
                  <Button appearance="primary" onClick={() => setView("new")} aria-label="New support request">Create a support request</Button>
                  <Button onClick={list.reload}>Refresh</Button>
                </div>
                {list.loading && !list.data ? <Loading /> : !rows.length ? <p className="vy-muted">No support requests in this subscription.</p> : (
                  <table className="vy-table" aria-label="Support requests">
                    <thead><tr><th>Request</th><th>Title</th><th>Service</th><th>Severity</th><th>Status</th><th>Created</th></tr></thead>
                    <tbody>{rows.map((t) => (
                      <tr key={t.name}>
                        <td><a href="#" onClick={(e) => { e.preventDefault(); setView(t.name); }}>{t.properties.supportTicketId}</a></td>
                        <td>{t.properties.title}</td><td>{t.properties.serviceDisplayName}</td>
                        <td>{t.properties.severity}</td><td>{t.properties.status}</td><td>{fmtDate(t.properties.createdDate)}</td>
                      </tr>))}</tbody>
                  </table>
                )}
              </>
            )}
      </CapabilityContainer>
    </>
  );
}

function NewRequest({ base, resourceId, service, onDone }) {
  const notify = useNotify();
  const svcs = useAsync(async () => (await restJson("GET", `${base}/services`, { query: q })).value || [], [base]);
  const hint = SERVICE_HINT[service] || null;
  const [f, setF] = useState({ title: "", description: "", severity: "Moderate", serviceId: "", pcId: "", first: "", last: "", email: "", method: "Email", phone: "", tz: "UTC", country: "IND", lang: "en-US" });
  const set = (k) => (_, d) => setF((x) => ({ ...x, [k]: d.value }));
  const services = svcs.data || [];
  const selected = f.serviceId || services.find((s) => s.properties.displayName === hint)?.id || "";
  const pcs = useAsync(async () => selected ? (await restJson("GET", `${base}/services/${selected.split("/").pop()}/problemClassifications`, { query: q })).value || [] : [], [selected]);
  const pcList = pcs.data || [];
  const pc = f.pcId || pcList[0]?.id || "";
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const submit = async () => {
    setBusy(true); setErr(null);
    const name = `vyomi-${Date.now().toString(36)}`;
    try {
      await restJson("PUT", `${base}/supportTickets/${name}`, { query: q, body: { properties: {
        title: f.title, description: f.description, severity: f.severity, serviceId: selected, problemClassificationId: pc,
        ...(resourceId ? { technicalTicketDetails: { resourceId } } : {}),
        contactDetails: { firstName: f.first, lastName: f.last, preferredContactMethod: f.method, primaryEmailAddress: f.email,
          ...(f.phone ? { phoneNumber: f.phone } : {}), preferredTimeZone: f.tz, country: f.country, preferredSupportLanguage: f.lang } } } });
      notify.success("Your support request was filed with Vyomi Support.", "Support request created");
      onDone(name);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <section className="vy-section" aria-label="New support request form">
      <h3>New support request</h3>
      <ErrorBar error={err} title="Could not create the support request" />
      <div style={{ display: "grid", gap: 8, maxWidth: 560 }}>
        <Field label="Summary" required><Input value={f.title} onChange={set("title")} aria-label="Summary" /></Field>
        <Field label="Service">
          <Select value={selected} onChange={(_, d) => setF((x) => ({ ...x, serviceId: d.value, pcId: "" }))} aria-label="Service">
            {services.map((s) => <option key={s.id} value={s.id}>{s.properties.displayName}</option>)}
          </Select>
        </Field>
        <Field label="Problem type">
          <Select value={pc} onChange={set("pcId")} aria-label="Problem type">{pcList.map((c) => <option key={c.id} value={c.id}>{c.properties.displayName}</option>)}</Select>
        </Field>
        {resourceId && <KV label="Resource" value={resourceId} />}
        <Field label="Severity"><Select value={f.severity} onChange={set("severity")} aria-label="Severity">{SEVERITY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
        <Field label="Details" required><Textarea rows={5} value={f.description} onChange={set("description")} aria-label="Details" /></Field>
        <Field label="First name" required><Input value={f.first} onChange={set("first")} aria-label="First name" /></Field>
        <Field label="Last name" required><Input value={f.last} onChange={set("last")} aria-label="Last name" /></Field>
        <Field label="Email" required><Input value={f.email} onChange={set("email")} aria-label="Email" /></Field>
        <Field label="Preferred contact method"><Select value={f.method} onChange={set("method")} aria-label="Preferred contact method"><option>Email</option><option>Phone</option></Select></Field>
        {f.method === "Phone" && <Field label="Phone number" required><Input value={f.phone} onChange={set("phone")} aria-label="Phone number" /></Field>}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Button appearance="primary" disabled={busy} onClick={submit} aria-label="Create support request">Create</Button>
        <Button onClick={() => onDone(null)}>Cancel</Button>
      </div>
    </section>
  );
}

function Ticket({ base, name, onBack }) {
  const notify = useNotify();
  const t = useAsync(() => restJson("GET", `${base}/supportTickets/${name}`, { query: q }), [name]);
  const c = useAsync(async () => (await restJson("GET", `${base}/supportTickets/${name}/communications`, { query: q })).value || [], [name]);
  const [reply, setReply] = useState("");
  const act = async (fn, ok) => { try { await fn(); notify.success(ok, "Support request"); t.reload(); c.reload(); } catch (e) { notify.error(e, "Support request update failed"); } };
  if (t.loading && !t.data) return <Loading />;
  if (t.error) return <><ErrorBar error={t.error} /><Button onClick={onBack}>Back</Button></>;
  const p = t.data.properties;
  const open = p.status === "Open";
  return (
    <section className="vy-section">
      <Button onClick={onBack}>Back to requests</Button>
      <h3>{p.supportTicketId} - {p.title}</h3>
      <KV label="Status" value={p.status} /><KV label="Severity" value={p.severity} /><KV label="Service" value={p.serviceDisplayName} />
      <KV label="Problem type" value={p.problemClassificationDisplayName} /><KV label="Support engineer" value={p.supportEngineer?.emailAddress} />
      <KV label="First response target" value={fmtDate(p.serviceLevelAgreement?.expirationTime)} />
      {p.technicalTicketDetails?.resourceId && <KV label="Resource" value={p.technicalTicketDetails.resourceId} />}
      <p style={Pre}>{p.description}</p>
      {open && (
        <div style={{ display: "flex", gap: 8, margin: "8px 0", alignItems: "center" }}>
          <Select value={p.severity} onChange={(_, d) => act(() => restJson("PATCH", `${base}/supportTickets/${name}`, { query: q, body: { severity: d.value } }), "Severity updated.")} aria-label="Change severity">
            {SEVERITY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
          <Button onClick={() => act(() => restJson("PATCH", `${base}/supportTickets/${name}`, { query: q, body: { status: "Closed" } }), "Request closed.")}>Close request</Button>
        </div>
      )}
      <h4>Conversation</h4>
      {(c.data || []).map((m) => (
        <div key={m.name} style={{ borderLeft: "3px solid #8884", paddingLeft: 8, margin: "8px 0" }}>
          <b>{m.properties.sender || "You"}</b> <span className="vy-muted">{fmtDate(m.properties.createdDate)} ({m.properties.communicationDirection})</span>
          <div><i>{m.properties.subject}</i></div><div style={Pre}>{m.properties.body}</div>
        </div>))}
      {open && (
        <div style={{ maxWidth: 560 }}>
          <Textarea rows={3} value={reply} onChange={(_, d) => setReply(d.value)} aria-label="Reply" placeholder="Add a reply" />
          <Button appearance="primary" disabled={!reply.trim()} onClick={() => act(async () => {
            await restJson("PUT", `${base}/supportTickets/${name}/communications/r${Date.now().toString(36)}`, { query: q, body: { properties: { subject: `Re: ${p.title}`, body: reply } } }); setReply("");
          }, "Reply sent.")} aria-label="Send reply">Send</Button>
        </div>
      )}
    </section>
  );
}
