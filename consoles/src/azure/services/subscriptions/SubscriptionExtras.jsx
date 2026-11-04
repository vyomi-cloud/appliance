/* AZ-08 subscription pages: management certificates, partner information, quota increase requests, ownership-transfer
 * requests and top free services by usage. Backed by core/azure_billing_ext_core.py over ARM. */
import { useState } from "react";
import {
  Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Select, Textarea,
} from "@fluentui/react-components";
import { Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { arm, armList, subPath } from "../../kit/az08.js";
import { ErrorBar, InfoBar, Loading } from "../../kit/common.jsx";

const V = "2024-01-01";

// ── Management certificates (Microsoft.Subscription/managementCertificates) ──────────────
export function ManagementCertificates({ id, name }) {
  const notify = useNotify();
  const base = `${subPath(id)}/providers/Microsoft.Subscription/managementCertificates`;
  const { data, loading, error, reload } = useAsync(() => armList(base), [id]);
  const [open, setOpen] = useState(false);
  const [pem, setPem] = useState("");
  const upload = async () => {
    try { await arm("POST", base, { certificate: pem }, {}, V); notify.success("Management certificate uploaded.", "Upload succeeded"); setOpen(false); setPem(""); reload(); }
    catch (e) { notify.error(e, "Upload failed"); }
  };
  return (
    <CapabilityContainer id="azure.subscriptions.management_certificates" title={`${name} | Management certificates`}>
      <InfoBar>Management certificates belong to the retired classic deployment model. Vyomi parses the uploaded X.509 certificate (thumbprint, subject, validity) but does not authenticate classic API calls with it.</InfoBar>
      <div className="vy-cmdbar" role="toolbar" aria-label="Management certificate commands"><Button onClick={() => setOpen(true)}>Upload</Button><Button onClick={reload}>Refresh</Button></div>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <table className="vy-grid">
          <thead><tr><th>Thumbprint</th><th>Subject</th><th>Issuer</th><th>Created</th><th>Expires</th><th /></tr></thead>
          <tbody>{(data || []).length ? data.map((c) => (
            <tr key={c.name}><td>{c.properties.thumbprint}</td><td>{c.properties.subject}</td><td>{c.properties.issuer}</td><td>{c.properties.created}</td><td>{c.properties.expires}</td>
              <td><Button appearance="subtle" icon={<Delete20Regular />} aria-label={`Delete ${c.name}`} onClick={async () => { await arm("DELETE", c.id, undefined, {}, V); reload(); }} /></td></tr>
          )) : <tr><td colSpan={6} className="vy-muted">No management certificates.</td></tr>}</tbody>
        </table>
      )}
      <Dialog open={open} onOpenChange={(_, d) => !d.open && setOpen(false)}>
        <DialogSurface aria-label="Upload management certificate"><DialogBody>
          <DialogTitle>Upload management certificate</DialogTitle>
          <DialogContent><Field label="Certificate (base64 DER or PEM)"><Textarea value={pem} onChange={(_, d) => setPem(d.value)} rows={8} aria-label="Certificate data" /></Field></DialogContent>
          <DialogActions><Button appearance="primary" disabled={!pem} onClick={upload}>Upload</Button><Button onClick={() => setOpen(false)}>Cancel</Button></DialogActions>
        </DialogBody></DialogSurface>
      </Dialog>
    </CapabilityContainer>
  );
}

// ── Partner information (Microsoft.ManagementPartner/partners) ───────────────────────────
export function PartnerInformation({ id, name }) {
  const notify = useNotify();
  const base = `${subPath(id)}/providers/Microsoft.ManagementPartner/partners`;
  const { data, loading, error, reload } = useAsync(() => armList(base), [id]);
  const [mpn, setMpn] = useState("");
  const [pname, setPname] = useState("");
  const cur = (data || [])[0];
  return (
    <CapabilityContainer id="azure.subscriptions.partner_information" title={`${name} | Partner information`}>
      <ErrorBar error={error} />
      {loading ? <Loading /> : cur ? (
        <section className="vy-section" style={{ maxWidth: 560 }}>
          <div className="vy-kv"><span>Microsoft Partner Network ID</span><span>{cur.properties.partnerId}</span></div>
          <div className="vy-kv"><span>Partner name</span><span>{cur.properties.partnerName || "--"}</span></div>
          <div className="vy-kv"><span>Associated</span><span>{cur.properties.createdTime}</span></div>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <Field label="New partner name"><Input value={pname} onChange={(_, d) => setPname(d.value)} aria-label="Partner name" /></Field>
            <Button onClick={async () => { try { await arm("PUT", `${base}/${cur.name}`, { properties: { partnerName: pname } }, {}, V); reload(); } catch (e) { notify.error(e, "Update failed"); } }}>Update</Button>
            <Button onClick={async () => { await arm("DELETE", `${base}/${cur.name}`, undefined, {}, V); reload(); }}>Remove association</Button>
          </div>
        </section>
      ) : (
        <section className="vy-section" style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 10 }}>
          <p style={{ fontSize: 13 }}>Link your Microsoft Partner Network (MPN) ID to this account so partners get credit for the usage.</p>
          <Field label="MPN ID" hint="Digits only."><Input value={mpn} onChange={(_, d) => setMpn(d.value)} aria-label="MPN ID" /></Field>
          <Field label="Partner name (optional)"><Input value={pname} onChange={(_, d) => setPname(d.value)} aria-label="Partner name" /></Field>
          <div><Button appearance="primary" disabled={!mpn} onClick={async () => {
            try { await arm("PUT", `${base}/${mpn}`, { properties: { partnerName: pname } }, {}, V); notify.success("Partner associated.", "Saved"); reload(); } catch (e) { notify.error(e, "Association failed"); }
          }}>Link to a partner ID</Button></div>
        </section>
      )}
    </CapabilityContainer>
  );
}

// ── Quota increase request (Microsoft.Quota) ────────────────────────────────────────────
export function RequestIncreaseDialog({ open, onClose, id, rows, onDone }) {
  const notify = useNotify();
  const [pick, setPick] = useState("");
  const [value, setValue] = useState("");
  const [loc] = useState("eastus");
  const row = rows.find((r) => r.name.value === pick);
  const ns = row && (row.__ns || "Microsoft.Compute");
  const go = async () => {
    try {
      const r = await arm("PUT", `${subPath(id)}/providers/${ns}/locations/${loc}/providers/Microsoft.Quota/quotas/${pick}`, { properties: { limit: { limitObjectType: "LimitValue", value: Number(value) } } }, {}, V);
      notify.success(`The ${row.name.localizedValue} limit is now ${r.properties.limit.value}.`, "Quota increase approved"); onDone(); onClose();
    } catch (e) { notify.error(e, "Quota request failed"); }
  };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Request increase"><DialogBody>
        <DialogTitle>Request increase</DialogTitle>
        <DialogContent>
          <Field label="Quota"><Select value={pick} onChange={(_, d) => { setPick(d.value); const r = rows.find((x) => x.name.value === d.value); setValue(r ? String(r.limit) : ""); }} aria-label="Quota to increase">
            <option value="">Select a quota</option>{rows.map((r) => <option key={r.name.value} value={r.name.value}>{r.name.localizedValue} ({r.currentValue} / {r.limit})</option>)}</Select></Field>
          <Field label="New limit" hint="Increases up to 4x the default are approved automatically; larger ones need a support request."><Input type="number" value={value} onChange={(_, d) => setValue(d.value)} aria-label="New limit" /></Field>
        </DialogContent>
        <DialogActions><Button appearance="primary" disabled={!pick || !value} onClick={go}>Submit</Button><Button onClick={onClose}>Cancel</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}

export function QuotaRequests({ id }) {
  const { data, loading, error } = useAsync(() => armList(`${subPath(id)}/providers/Microsoft.Quota/quotaRequests`), [id]);
  return (
    <section className="vy-section" style={{ marginTop: 16 }}>
      <h3>Recent quota requests</h3>
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <table className="vy-grid">
          <thead><tr><th>Submitted</th><th>Quota</th><th>From</th><th>To</th><th>State</th><th>Message</th></tr></thead>
          <tbody>{(data || []).length ? data.map((r) => { const v = r.properties.value[0]; return (
            <tr key={r.name}><td>{r.properties.requestSubmitTime}</td><td>{v.name.localizedValue}</td><td>{v.previousLimit}</td><td>{v.limit.value}</td><td>{r.properties.provisioningState}</td><td>{r.properties.message || "--"}</td></tr>); })
            : <tr><td colSpan={6} className="vy-muted">No quota requests yet.</td></tr>}</tbody>
        </table>
      )}
    </section>
  );
}

// ── Ownership-transfer requests (Microsoft.Billing/transferRequests) ─────────────────────
export function TransferRequestsDialog({ open, onClose, id }) {
  const notify = useNotify();
  const base = `${subPath(id)}/providers/Microsoft.Billing/transferRequests`;
  const { data, loading, error, reload } = useAsync(() => armList(base), [id, open]);
  const [email, setEmail] = useState("");
  const act = async (r, a) => { try { await arm("POST", `${base}/${r.name}/${a}`, {}, {}, V); reload(); } catch (e) { notify.error(e, `${a} failed`); } };
  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface aria-label="Subscription ownership-transfer requests" style={{ maxWidth: 760 }}><DialogBody>
        <DialogTitle>Subscription ownership-transfer requests</DialogTitle>
        <DialogContent>
          <CapabilityContainer id="azure.subscriptions.transfer_requests" title="Ownership transfer">
          <ErrorBar error={error} />
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginBottom: 12 }}>
            <Field label="Transfer to (e-mail)"><Input value={email} onChange={(_, d) => setEmail(d.value)} aria-label="Recipient e-mail" /></Field>
            <Button appearance="primary" disabled={!email} onClick={async () => { try { await arm("POST", base, { recipientEmail: email }, {}, V); notify.success("Transfer request sent. It expires in 15 days.", "Request created"); setEmail(""); reload(); } catch (e) { notify.error(e, "Transfer request failed"); } }}>Request transfer</Button>
          </div>
          {loading ? <Loading /> : (
            <table className="vy-grid">
              <thead><tr><th>Recipient</th><th>Status</th><th>Created</th><th>Expires</th><th /></tr></thead>
              <tbody>{(data || []).length ? data.map((r) => (
                <tr key={r.name}><td>{r.properties.recipientEmail}</td><td>{r.properties.status}</td><td>{r.properties.createdTime}</td><td>{r.properties.expirationTime}</td>
                  <td>{r.properties.status === "Pending" && <>
                    <Button size="small" onClick={() => act(r, "accept")}>Accept</Button> <Button size="small" onClick={() => act(r, "decline")}>Decline</Button> <Button size="small" onClick={() => act(r, "cancel")}>Cancel</Button></>}</td></tr>
              )) : <tr><td colSpan={5} className="vy-muted">No transfer requests.</td></tr>}</tbody>
            </table>
          )}
          </CapabilityContainer>
        </DialogContent>
        <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
      </DialogBody></DialogSurface>
    </Dialog>
  );
}

// ── Top free services by usage (Microsoft.Billing/freeServices) ──────────────────────────
export function TopFreeServices({ id }) {
  const { data, loading, error } = useAsync(() => armList(`${subPath(id)}/providers/Microsoft.Billing/freeServices`), [id]);
  return (
    <CapabilityContainer id="azure.subscriptions.top_free_services" title="Top free services by usage">
      <ErrorBar error={error} />
      {loading ? <Loading /> : (
        <table className="vy-grid" aria-label="Top free services by usage">
          <thead><tr><th>Service</th><th>Included</th><th>Used</th><th>% used</th><th>Window</th><th>Measured</th></tr></thead>
          <tbody>{(data || []).map((r) => (
            <tr key={r.id}><td>{r.name}</td><td>{r.included.toLocaleString()} {r.unit}</td><td>{r.used}</td>
              <td><div style={{ background: "var(--colorNeutralBackground4)", borderRadius: 3, width: 120, height: 8 }}><div style={{ background: "var(--colorBrandBackground)", width: `${Math.min(r.percentUsed, 100)}%`, height: 8, borderRadius: 3 }} /></div> {r.percentUsed}%</td>
              <td>{r.window}</td><td>{r.measured ? "Yes" : "Not measurable"}</td></tr>))}</tbody>
        </table>
      )}
    </CapabilityContainer>
  );
}
