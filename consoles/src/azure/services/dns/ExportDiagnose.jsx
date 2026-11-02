/* DNS zone: Export template (ARM / Bicep / Terraform generated from the zone and its real
 * record sets) and Diagnose and solve problems (health checks computed from the zone's own
 * state over the native ARM wire). No backend beyond the existing zone + record-set calls. */
import { useState } from "react";
import { Button, Checkbox, Tab, TabList, Textarea, ToolbarButton } from "@fluentui/react-components";
import { ArrowDownload20Regular } from "@fluentui/react-icons";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";
import { convertTemplate } from "../../kit/templateConvert.js";
import * as api from "./api.js";

const SKIP = (rs) => { const t = api.recordSetType(rs); return t === "SOA" || (t === "NS" && rs.name === "@"); };

export function ExportTemplate({ z, rg }) {
  const [tab, setTab] = useState("arm");
  const [params, setParams] = useState(true);
  const rs = useAsync(() => api.listRecordSets(rg, z.name), [rg, z.name, z.properties?.numberOfRecordSets]);
  const zp = z.properties || {};
  const zoneProps = { zoneType: zp.zoneType || "Public" };
  for (const k of ["registrationVirtualNetworks", "resolutionVirtualNetworks"]) if (zp[k]) zoneProps[k] = zp[k];
  const zoneRef = params ? "[parameters('zoneName')]" : z.name;
  const template = {
    "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
    contentVersion: "1.0.0.0",
    ...(params ? { parameters: { zoneName: { type: "string", defaultValue: z.name } } } : {}),
    resources: [
      { type: "Microsoft.Network/dnszones", apiVersion: api.API_VERSION, name: zoneRef, location: "global", ...(z.tags && Object.keys(z.tags).length ? { tags: z.tags } : {}), properties: zoneProps },
      ...(rs.data || []).filter((r) => !SKIP(r)).map((r) => {
        const { provisioningState, fqdn, ...props } = r.properties || {};
        return { type: `Microsoft.Network/dnszones/${api.recordSetType(r)}`, apiVersion: api.API_VERSION, name: `${zoneRef}/${r.name}`, dependsOn: [params ? "[resourceId('Microsoft.Network/dnszones', parameters('zoneName'))]" : `[resourceId('Microsoft.Network/dnszones', '${z.name}')]`], properties: props };
      }),
    ],
  };
  const text = convertTemplate(tab, template);
  const download = () => {
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([convertTemplate("arm", template)], { type: "application/json" }));
    el.download = `${z.name}.json`;
    document.body.appendChild(el); el.click(); el.remove();
  };
  return (
    <>
      <div className="vy-panel-title">{z.name} | Export template</div>
      <div className="vy-cmdbar" role="toolbar" aria-label="Export template commands">
        <ToolbarButton icon={<ArrowDownload20Regular />} onClick={download}>Download</ToolbarButton>
      </div>
      <TabList selectedValue={tab} onTabSelect={(_, d) => setTab(d.value)} aria-label="Export template tabs">
        <Tab value="arm">ARM Template</Tab><Tab value="bicep">Bicep</Tab><Tab value="terraform">Terraform</Tab>
      </TabList>
      <CapabilityContainer id="azure.dns.export_template" title="Template">
        <ErrorBar error={rs.error} />
        <Checkbox label="Include parameters" checked={params} onChange={(_, d) => setParams(!!d.checked)} />
        {rs.loading && !rs.data ? <Loading /> : <Textarea readOnly aria-label={`${tab} template`} value={text} style={{ width: "100%", minHeight: 320, fontFamily: "monospace" }} />}
      </CapabilityContainer>
    </>
  );
}

/** Health checks over the zone's own state. */
export function checks(z, sets) {
  const zp = z.properties || {}, priv = zp.zoneType === "Private", out = [];
  const byName = {};
  for (const r of sets) (byName[r.name] ||= []).push(api.recordSetType(r));
  const apexNs = sets.find((r) => r.name === "@" && api.recordSetType(r) === "NS");
  out.push(priv
    ? { id: "delegation", title: "Delegation", status: "ok", detail: "Private zones are resolved only from linked virtual networks; no registrar delegation is needed." }
    : { id: "delegation", title: "Delegation", status: (zp.nameServers || []).length ? "ok" : "fail", detail: (zp.nameServers || []).length ? `Delegate the domain at your registrar to: ${zp.nameServers.join(", ")}.` : "The zone has no assigned name servers." });
  out.push({ id: "apexns", title: "Apex NS record set", status: apexNs ? "ok" : "fail", detail: apexNs ? `Present (${(apexNs.properties?.NSRecords || []).length} name servers).` : "The apex NS record set is missing." });
  out.push({ id: "soa", title: "SOA record set", status: sets.some((r) => api.recordSetType(r) === "SOA") ? "ok" : "fail", detail: "Every zone needs one SOA record set at the apex." });
  const conflicts = Object.entries(byName).filter(([, t]) => t.includes("CNAME") && t.length > 1).map(([n]) => n);
  out.push({ id: "cname", title: "CNAME conflicts", status: conflicts.length ? "fail" : "ok", detail: conflicts.length ? `CNAME shares a name with other record types: ${conflicts.join(", ")}.` : "No record set name mixes a CNAME with other types." });
  const apexCname = sets.some((r) => r.name === "@" && api.recordSetType(r) === "CNAME");
  out.push({ id: "apexcname", title: "CNAME at the zone apex", status: apexCname ? "fail" : "ok", detail: apexCname ? "A CNAME at the apex is not allowed; use an alias A/AAAA record set." : "No CNAME at the apex." });
  const ttl0 = sets.filter((r) => !SKIP(r) && Number(r.properties?.TTL) < 30).map((r) => `${r.name}/${api.recordSetType(r)}`);
  out.push({ id: "ttl", title: "Very low TTLs", status: ttl0.length ? "warn" : "ok", detail: ttl0.length ? `TTL under 30 seconds: ${ttl0.join(", ")}.` : "All TTLs are 30 seconds or higher." });
  const empty = sets.filter((r) => { const t = api.recordSetType(r); if (t === "SOA" || r.properties?.targetResource?.id) return false; const v = r.properties?.[api.ARM_FIELD[t]]; return !v || (Array.isArray(v) && !v.length); }).map((r) => `${r.name}/${api.recordSetType(r)}`);
  out.push({ id: "empty", title: "Empty record sets", status: empty.length ? "warn" : "ok", detail: empty.length ? `No records in: ${empty.join(", ")}.` : "Every record set carries records." });
  const used = zp.numberOfRecordSets ?? sets.length, max = zp.maxNumberOfRecordSets;
  out.push({ id: "quota", title: "Record set quota", status: max && used / max > 0.9 ? "warn" : "ok", detail: `${used} of ${max ?? "--"} record sets used.` });
  if (priv) {
    const links = (zp.registrationVirtualNetworks || []).length + (zp.resolutionVirtualNetworks || []).length;
    out.push({ id: "links", title: "Virtual network links", status: links ? "ok" : "warn", detail: links ? `${links} linked virtual network(s).` : "A private zone with no linked virtual network resolves nowhere." });
  }
  return out;
}

const COLOR = { ok: "#107c10", warn: "#c19c00", fail: "#d13438" };
const WORD = { ok: "Healthy", warn: "Warning", fail: "Problem" };

export function Diagnose({ z, rg }) {
  const rs = useAsync(() => api.listRecordSets(rg, z.name), [rg, z.name, z.properties?.numberOfRecordSets]);
  const [open, setOpen] = useState(null);
  const list = rs.data ? checks(z, rs.data) : [];
  return (
    <>
      <div className="vy-panel-title">{z.name} | Diagnose and solve problems</div>
      <ErrorBar error={rs.error} />
      <div className="vy-cmdbar"><Button appearance="subtle" onClick={rs.reload}>Run checks again</Button></div>
      <CapabilityContainer id="azure.dns.diagnose" title="DNS zone health checks">
        {rs.loading && !rs.data ? <Loading /> : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(260px,1fr))", gap: 12 }}>
            {list.map((c) => (
              <div key={c.id} className="vy-section" data-diag={c.id} data-status={c.status} style={{ border: "1px solid #e1dfdd", borderRadius: 4, padding: 12, cursor: "pointer" }} onClick={() => setOpen(open === c.id ? null : c.id)}>
                <div style={{ fontWeight: 600 }}>{c.title}</div>
                <div style={{ color: COLOR[c.status], fontWeight: 600 }}>{WORD[c.status]}</div>
                {open === c.id && <div style={{ marginTop: 6 }}>{c.detail}</div>}
              </div>
            ))}
          </div>
        )}
      </CapabilityContainer>
    </>
  );
}
