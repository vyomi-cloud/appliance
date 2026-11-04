/* Vyomi Marketplace: browse Vyomi's own SaaS-simulator offers and subscribe (Microsoft.SaaS/resources).
 * Used by "Creating a new resource from the Marketplace" (subscription + resource group) and Storage "Partner solutions".
 * Backed by core/azure_marketplace_core.py. */
import { useState } from "react";
import { Button, Field, Input, Select } from "@fluentui/react-components";
import { Delete20Regular, Key20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../common/notify.jsx";
import { useAsync } from "../../common/useAsync.js";
import { CapabilityContainer } from "./Capability.jsx";
import { listResourceGroups } from "./arm.js";
import { arm, armList, rgPath, subPath } from "./az08.js";
import { ErrorBar, InfoBar, Loading } from "./common.jsx";

export default function MarketplaceBrowser({ capId, title, fixedRg, categories }) {
  const notify = useNotify();
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [pick, setPick] = useState(null);
  const [form, setForm] = useState({ name: "", plan: "", rg: fixedRg || "" });
  const [access, setAccess] = useState(null);
  const offers = useAsync(() => armList(`${subPath()}/providers/Microsoft.Marketplace/offers`, { ...(category ? { category } : {}), ...(search ? { search } : {}) }), [category, search]);
  const cats = useAsync(() => armList(`${subPath()}/providers/Microsoft.Marketplace/categories`), []);
  const rgs = useAsync(() => listResourceGroups(), []);
  const mine = useAsync(() => armList(fixedRg ? `${rgPath(fixedRg)}/providers/Microsoft.SaaS/resources` : `${subPath()}/providers/Microsoft.SaaS/resources`), [fixedRg]);
  const shown = (offers.data || []).filter((o) => !categories || categories.includes(o.category));

  const subscribe = async () => {
    try {
      await arm("PUT", `${rgPath(form.rg)}/providers/Microsoft.SaaS/resources/${form.name}`, { location: "global", properties: { publisherId: "vyomi", offerId: pick.offerId, planId: form.plan || pick.plans[0].planId } });
      notify.success(`Subscribed '${form.name}' to ${pick.displayName}.`, "Subscription created");
      setPick(null); setForm({ ...form, name: "" }); mine.reload();
    } catch (e) { notify.error(e, "Failed to create the SaaS subscription"); }
  };
  const showKey = async (r, regen) => {
    try { setAccess({ name: r.name, ...(await arm("POST", `${r.id}/${regen ? "regenerateAccessKey" : "listAccessInfo"}`, {})) }); } catch (e) { notify.error(e, "Failed to read access info"); }
  };

  return (
    <CapabilityContainer id={capId} title={title}>
      <InfoBar>Vyomi publishes its own catalog of SaaS-simulator spaces. Subscribing creates a real Microsoft.SaaS/resources resource; plans are free and nothing is billed.</InfoBar>
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", margin: "12px 0" }}>
        <Field label="Search the Marketplace"><Input value={search} onChange={(_, d) => setSearch(d.value)} aria-label="Search the Marketplace" /></Field>
        <Field label="Category"><Select value={category} onChange={(_, d) => setCategory(d.value)} aria-label="Category">
          <option value="">All</option>{(cats.data || []).filter((c) => !categories || categories.includes(c.name)).map((c) => <option key={c.name} value={c.name}>{c.name} ({c.count})</option>)}</Select></Field>
      </div>
      <ErrorBar error={offers.error} />
      {offers.loading ? <Loading /> : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 12 }}>
          {shown.map((o) => (
            <div key={o.offerId} className="vy-section" data-offer={o.offerId} style={{ border: "1px solid var(--colorNeutralStroke2)", borderRadius: 6, padding: 12 }}>
              <strong>{o.displayName}</strong>
              <div className="vy-muted" style={{ fontSize: 12 }}>{o.publisherDisplayName} · {o.category} · Free</div>
              <p style={{ fontSize: 13 }}>{o.summary}</p>
              <Button size="small" appearance="primary" aria-label={`Create ${o.displayName}`} onClick={() => { setPick(o); setForm({ ...form, plan: o.plans[0].planId }); }}>Create</Button>
            </div>
          ))}
          {!shown.length && <span className="vy-muted">No offers match.</span>}
        </div>
      )}
      {pick && (
        <section className="vy-section" style={{ maxWidth: 520, marginTop: 16 }} aria-label="Create SaaS subscription">
          <h3>Subscribe to {pick.displayName}</h3>
          {!fixedRg && <Field label="Resource group"><Select value={form.rg} onChange={(_, d) => setForm({ ...form, rg: d.value })} aria-label="Resource group">
            <option value="">Select</option>{(rgs.data || []).map((r) => <option key={r.name}>{r.name}</option>)}</Select></Field>}
          <Field label="Resource name"><Input value={form.name} onChange={(_, d) => setForm({ ...form, name: d.value })} aria-label="Resource name" /></Field>
          <Field label="Plan"><Select value={form.plan} onChange={(_, d) => setForm({ ...form, plan: d.value })} aria-label="Plan">
            {pick.plans.map((p) => <option key={p.planId} value={p.planId}>{p.displayName}</option>)}</Select></Field>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <Button appearance="primary" disabled={!form.name || !form.rg} onClick={subscribe}>Subscribe</Button><Button onClick={() => setPick(null)}>Cancel</Button>
          </div>
        </section>
      )}
      <h3 style={{ marginTop: 20 }}>Your Vyomi SaaS subscriptions</h3>
      <ErrorBar error={mine.error} />
      <table className="vy-grid">
        <thead><tr><th>Name</th><th>Offer</th><th>Plan</th><th>Status</th><th /></tr></thead>
        <tbody>
          {(mine.data || []).length ? mine.data.map((r) => (
            <tr key={r.id}>
              <td>{r.name}</td><td>{r.properties?.offerDisplayName}</td><td>{r.properties?.planId}</td><td>{r.properties?.status}</td>
              <td>
                <Button appearance="subtle" icon={<Key20Regular />} aria-label={`Access info for ${r.name}`} onClick={() => showKey(r, false)} />
                <Button appearance="subtle" icon={<Delete20Regular />} aria-label={`Unsubscribe ${r.name}`} onClick={async () => { try { await arm("DELETE", r.id); mine.reload(); } catch (e) { notify.error(e, "Unsubscribe failed"); } }} />
              </td>
            </tr>
          )) : <tr><td colSpan={5} className="vy-muted">No SaaS subscriptions yet.</td></tr>}
        </tbody>
      </table>
      {access && (
        <section className="vy-section" style={{ maxWidth: 560, marginTop: 12 }}>
          <h4>{access.name} access info</h4>
          <Field label="Space ID"><Input readOnly value={access.spaceId} /></Field>
          <Field label="Access key"><Input readOnly value={access.accessKey} /></Field>
          <Button onClick={() => showKey({ id: mine.data.find((x) => x.name === access.name).id, name: access.name }, true)}>Regenerate key</Button>
        </section>
      )}
    </CapabilityContainer>
  );
}
