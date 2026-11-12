/* Front Door and CDN profiles (Microsoft.Cdn/profiles): browse + create, and a profile blade with endpoints, origin groups + origins, routes,
 * rule sets + rules and custom domains over native ARM (core/azure_netcfg_core.py). Control plane only: no edge request is ever served. */
import { useEffect, useState } from "react";
import { Button, Dialog, DialogActions, DialogBody, DialogContent, DialogSurface, DialogTitle, Field, Input, Link, Select } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { DEFAULT_RG, getSubscription, listResourceGroups } from "../../kit/arm.js";
import ArmChildren from "../../kit/ArmChildren.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceBlade, { TitleRow } from "../../kit/ResourceBlade.jsx";
import { ErrorBar, Essentials, Glyph, InfoBar, Loading } from "../../kit/common.jsx";
import { remember } from "../../kit/recent.js";
import { useSubscription } from "../../kit/subscription.js";

const V = "2024-02-01";
const sub = () => `/subscriptions/${getSubscription()}`;
const rgOf = (id = "") => (id.split("/resourceGroups/")[1] || "").split("/")[0];
const pPath = (rg, name) => `${sub()}/resourceGroups/${encodeURIComponent(rg)}/providers/Microsoft.Cdn/profiles/${encodeURIComponent(name)}`;
const SKUS = ["Standard_AzureFrontDoor", "Premium_AzureFrontDoor", "Standard_Microsoft", "Standard_Verizon", "Premium_Verizon", "Standard_Akamai"];
const isAfd = (p) => String(p?.sku?.name || "").endsWith("AzureFrontDoor");

export function Profiles() {
  const notify = useNotify();
  const s = useSubscription();
  const { data, loading, error, reload } = useAsync(async () => (await restJson("GET", `${sub()}/providers/Microsoft.Cdn/profiles`, { query: { "api-version": V } })).value || [], [s.id]);
  const rgs = useAsync(() => listResourceGroups(), [s.id]);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ rg: DEFAULT_RG, name: "", sku: SKUS[0] });
  const [err, setErr] = useState(null);
  const create = async () => {
    setErr(null);
    try {
      await restJson("PUT", pPath(f.rg, f.name), { query: { "api-version": V }, body: { location: "global", sku: { name: f.sku } } });
      notify.success(`Profile '${f.name}' created.`, "Create profile"); setOpen(false); reload();
    } catch (e) { setErr(e); }
  };
  return (
    <>
      <TitleRow title="Front Door and CDN profiles" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="vnets" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid tools resourceName="profile" items={data || []} loading={loading} error={error} onRefresh={reload} onCreate={() => { setErr(null); setF({ rg: (rgs.data?.[0]?.name) || DEFAULT_RG, name: "", sku: SKUS[0] }); setOpen(true); }}
          onDelete={async (rows) => { for (const r of rows) await restJson("DELETE", pPath(rgOf(r.id), r.name), { query: { "api-version": V } }); notify.success(`Deleted ${rows.length} profile(s).`, "Delete succeeded"); reload(); }}
          subscriptionLabel={s.displayName || s.id} csvName="cdn-profiles.csv"
          pills={[{ key: "rg", label: "Resource group", value: (r) => rgOf(r.id) }, { key: "sku", label: "Pricing tier", value: (r) => r.sku?.name }]}
          columns={[{ key: "name", label: "Name", render: (r) => <Link href={`#/frontdoor/${encodeURIComponent(rgOf(r.id))}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "type", label: "Type", value: (r) => (isAfd(r) ? "Front Door" : "CDN profile") }, { key: "sku", label: "Pricing tier", value: (r) => r.sku?.name },
            { key: "resourceGroup", label: "Resource group", value: (r) => rgOf(r.id) }, { key: "location", label: "Location", value: () => "Global" }]}
          emptyAction={<Link as="button" onClick={() => setOpen(true)}>Create a profile</Link>} />
      </div>
      <Dialog open={open} onOpenChange={(_, d) => !d.open && setOpen(false)}>
        <DialogSurface aria-label="Create profile"><DialogBody><DialogTitle>Create a Front Door or CDN profile</DialogTitle>
          <DialogContent><div style={{ display: "flex", flexDirection: "column", gap: 12 }}><ErrorBar error={err} title="Create failed" />
            <Field label="Resource group"><Select aria-label="Resource group" value={f.rg} onChange={(_, d) => setF({ ...f, rg: d.value })}>{(rgs.data || []).map((g) => <option key={g.name}>{g.name}</option>)}</Select></Field>
            <Field label="Profile name" required><Input aria-label="Profile name" value={f.name} onChange={(_, d) => setF({ ...f, name: d.value })} /></Field>
            <Field label="Pricing tier"><Select aria-label="Pricing tier" value={f.sku} onChange={(_, d) => setF({ ...f, sku: d.value })}>{SKUS.map((x) => <option key={x}>{x}</option>)}</Select></Field>
          </div></DialogContent>
          <DialogActions><Button appearance="primary" onClick={create}>Create</Button><Button onClick={() => setOpen(false)}>Cancel</Button></DialogActions></DialogBody></DialogSurface>
      </Dialog>
    </>
  );
}

export const MENU = [
  { id: "overview", label: "Overview" },
  { group: "Settings", items: [{ id: "endpoints", label: "Endpoints and routes" }, { id: "origins", label: "Origin groups" }, { id: "rulesets", label: "Rule sets" }, { id: "domains", label: "Domains" }] },
];

export function ProfileBlade({ params }) {
  const { rg, name } = params;
  const panel = params.panel || "overview";
  const prof = useAsync(() => restJson("GET", pPath(rg, name), { query: { "api-version": V } }), [rg, name]);
  const self = `#/frontdoor/${encodeURIComponent(rg)}/${encodeURIComponent(name)}`;
  useEffect(() => { if (prof.data) remember({ name, type: "Front Door and CDN profile", href: self }); }, [!!prof.data, self]);
  const [ep, setEp] = useState(null);
  const [og, setOg] = useState(null);
  const [rs, setRs] = useState(null);
  const base = pPath(rg, name);
  let body;
  if (prof.loading && !prof.data) body = <Loading />;
  else if (prof.error) body = <><ErrorBar error={prof.error} title="Failed to load the profile" /><Link href="#/frontdoor">Back to profiles</Link></>;
  else {
    const p = prof.data, afd = isAfd(p);
    const notAfd = <InfoBar title="Classic CDN profile" intent="warning">{`${p.sku?.name} profiles use classic CDN endpoints; Front Door endpoints, routes, origin groups and rule sets need a Standard_AzureFrontDoor or Premium_AzureFrontDoor profile.`}</InfoBar>;
    body = {
      overview: () => (<>
        <div className="vy-panel-title">{name}</div>
        <Essentials left={[["Resource group", rgOf(p.id)], ["Location", "Global"], ["Pricing tier", p.sku?.name]]} right={[["Front Door ID", p.properties?.frontDoorId || "-"], ["Provisioning state", p.properties?.provisioningState], ["Resource state", p.properties?.resourceState]]} />
        <CapabilityContainer id="azure.vnets.front_door_cdn" title="About this profile"><p className="vy-muted" style={{ fontSize: 13 }}>Endpoint host names, routes and rule sets are real control-plane resources with Azure's validation. No request is ever served from an endpoint: there is no caching, WAF, TLS termination or origin health probing.</p></CapabilityContainer>
      </>),
      endpoints: () => (afd ? (<>
        <div className="vy-panel-title">{name} | Endpoints and routes</div>
        <ArmChildren title="Endpoints" noun="endpoint" path={`${base}/afdEndpoints`} version={V} onSelect={setEp} selectedName={ep}
          fields={[{ key: "name", label: "Endpoint name", required: true }, { key: "enabledState", label: "Status", options: ["Enabled", "Disabled"] }]}
          build={(v) => ({ name: v.name, body: { location: "global", properties: { enabledState: v.enabledState } } })}
          columns={[{ label: "Host name", value: (r) => r.properties?.hostName }, { label: "Status", value: (r) => r.properties?.enabledState }]} />
        {ep ? <ArmChildren title={`Routes of ${ep}`} noun="route" path={`${base}/afdEndpoints/${ep}/routes`} version={V}
          fields={[{ key: "name", label: "Route name", required: true }, { key: "og", label: "Origin group name", required: true }, { key: "patterns", label: "Patterns to match", def: "/*", type: "csv" }, { key: "https", label: "HTTPS redirect", options: ["Enabled", "Disabled"] }]}
          build={(v) => ({ name: v.name, body: { properties: { originGroup: { id: `${base}/originGroups/${v.og}` }, patternsToMatch: v.patterns, httpsRedirect: v.https, supportedProtocols: ["Http", "Https"], forwardingProtocol: "MatchRequest" } } })}
          columns={[{ label: "Origin group", value: (r) => String(r.properties?.originGroup?.id || "").split("/").pop() }, { label: "Patterns", value: (r) => (r.properties?.patternsToMatch || []).join(", ") }, { label: "HTTPS redirect", value: (r) => r.properties?.httpsRedirect }]} /> : <p className="vy-muted">Select an endpoint to manage its routes.</p>}
      </>) : notAfd),
      origins: () => (afd ? (<>
        <div className="vy-panel-title">{name} | Origin groups</div>
        <ArmChildren title="Origin groups" noun="origin group" path={`${base}/originGroups`} version={V} onSelect={setOg} selectedName={og}
          fields={[{ key: "name", label: "Origin group name", required: true }, { key: "path", label: "Health probe path", def: "/" }, { key: "proto", label: "Probe protocol", options: ["Https", "Http"] }, { key: "interval", label: "Probe interval (seconds)", type: "number", def: "100" }]}
          build={(v) => ({ name: v.name, body: { properties: { healthProbeSettings: { probePath: v.path, probeProtocol: v.proto, probeRequestType: "HEAD", probeIntervalInSeconds: v.interval }, loadBalancingSettings: { sampleSize: 4, successfulSamplesRequired: 3 } } } })}
          columns={[{ label: "Probe", value: (r) => `${r.properties?.healthProbeSettings?.probeProtocol || ""} ${r.properties?.healthProbeSettings?.probePath || ""}` }, { label: "Interval (s)", value: (r) => r.properties?.healthProbeSettings?.probeIntervalInSeconds }]} />
        {og ? <ArmChildren title={`Origins of ${og}`} noun="origin" path={`${base}/originGroups/${og}/origins`} version={V}
          fields={[{ key: "name", label: "Origin name", required: true }, { key: "host", label: "Host name", required: true }, { key: "priority", label: "Priority (1-5)", type: "number", def: "1" }, { key: "weight", label: "Weight (1-1000)", type: "number", def: "1000" }]}
          build={(v) => ({ name: v.name, body: { properties: { hostName: v.host, originHostHeader: v.host, priority: v.priority, weight: v.weight, httpPort: 80, httpsPort: 443, enabledState: "Enabled" } } })}
          columns={[{ label: "Host name", value: (r) => r.properties?.hostName }, { label: "Priority", value: (r) => r.properties?.priority }, { label: "Weight", value: (r) => r.properties?.weight }]} /> : <p className="vy-muted">Select an origin group to manage its origins.</p>}
      </>) : notAfd),
      rulesets: () => (afd ? (<>
        <div className="vy-panel-title">{name} | Rule sets</div>
        <ArmChildren title="Rule sets" noun="rule set" path={`${base}/ruleSets`} version={V} onSelect={setRs} selectedName={rs}
          fields={[{ key: "name", label: "Rule set name (letters and digits)", required: true }]} build={(v) => ({ name: v.name, body: { properties: {} } })} columns={[{ label: "Provisioning state", value: (r) => r.properties?.provisioningState }]} />
        {rs ? <ArmChildren title={`Rules of ${rs}`} noun="rule" path={`${base}/ruleSets/${rs}/rules`} version={V}
          fields={[{ key: "name", label: "Rule name", required: true }, { key: "order", label: "Order", type: "number", def: "1" }, { key: "cond", label: "Condition", options: ["RequestScheme", "RequestMethod", "UrlPath"] }, { key: "action", label: "Action", options: ["UrlRedirect", "ModifyResponseHeader", "CacheExpiration"] }]}
          build={(v) => ({ name: v.name, body: { properties: { order: v.order, conditions: [{ name: v.cond, parameters: { typeName: "Del" + v.cond + "ConditionParameters", operator: "Equal", matchValues: ["HTTP"] } }], actions: [{ name: v.action, parameters: { typeName: "Del" + v.action + "ActionParameters" } }] } } })}
          columns={[{ label: "Order", value: (r) => r.properties?.order }, { label: "Conditions", value: (r) => (r.properties?.conditions || []).map((c) => c.name).join(", ") }, { label: "Actions", value: (r) => (r.properties?.actions || []).map((c) => c.name).join(", ") }]} /> : <p className="vy-muted">Select a rule set to manage its rules.</p>}
      </>) : notAfd),
      domains: () => (afd ? (<>
        <div className="vy-panel-title">{name} | Domains</div>
        <ArmChildren title="Custom domains" noun="custom domain" path={`${base}/customDomains`} version={V}
          note="Domain validation stays Pending: Vyomi runs no DNS validation or certificate issuance."
          fields={[{ key: "name", label: "Domain resource name", required: true }, { key: "host", label: "Host name", required: true }, { key: "cert", label: "Certificate type", options: ["ManagedCertificate", "CustomerCertificate"] }]}
          build={(v) => ({ name: v.name, body: { properties: { hostName: v.host, tlsSettings: { certificateType: v.cert, minimumTlsVersion: "TLS12" } } } })}
          columns={[{ label: "Host name", value: (r) => r.properties?.hostName }, { label: "Validation", value: (r) => r.properties?.domainValidationState }, { label: "Certificate", value: (r) => r.properties?.tlsSettings?.certificateType }]} />
      </>) : notAfd),
    }[panel]?.();
  }
  return (
    <ResourceBlade title={name} subtitle="Front Door and CDN profile" glyph={<Glyph id="vnets" />} closeHref="#/frontdoor" menu={MENU} active={panel} hrefFor={(id) => (id === "overview" ? self : `${self}/${id}`)}>{body}</ResourceBlade>
  );
}
