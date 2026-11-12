/* Deployment + infrastructure: Network, Custom domains and Locations are real properties.*
 * fields on the service, written through the same PATCH the create wizard uses. Locations is
 * ENFORCED server-side (Consumption/Developer can't add a region — core/azure_arm_core.py's
 * _apim_locations_block). Gateways is a read-only view of the resulting managed-gateway
 * regions — see azure.apim.deployment. */
import { useState, useEffect } from "react";
import { Button, Field, Input, Select } from "@fluentui/react-components";
import { Add20Regular, Delete20Regular } from "@fluentui/react-icons";
import { useNotify } from "../../../common/notify.jsx";
import { locationLabel } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const CAP = "azure.apim.deployment";
const VNET_TYPES = ["None", "External", "Internal"];

export function Network({ a, reload }) {
  const notify = useNotify();
  const [type, setType] = useState(a.properties?.virtualNetworkType || "None");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.updateService(a.resourceGroup, a.name, { properties: { virtualNetworkType: type } });
      notify.success("Network settings were saved.", "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving network settings failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id={CAP} title={`${a.name} | Network`}>
      <Field label="Virtual network type" style={{ maxWidth: 280 }}
        hint="External: gateway has a public IP, deployed inside a VNet. Internal: gateway only reachable inside the VNet.">
        <Select value={type} onChange={(_, d) => setType(d.value)} aria-label="Virtual network type">
          {VNET_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </Select>
      </Field>
      <div style={{ marginTop: 12 }}><Button appearance="primary" disabled={busy} onClick={save}>Save</Button></div>
    </CapabilityContainer>
  );
}

const HOSTNAME_TYPES = ["Proxy", "Portal", "Management", "Scm", "DeveloperPortal"];

export function CustomDomains({ a, reload }) {
  const notify = useNotify();
  const init = () => (a.properties?.hostnameConfigurations || []).map((h) => ({ ...h }));
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const upd = (i, k, v) => setRows((xs) => xs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const save = async () => {
    const seen = new Set();
    for (const r of rows) {
      if (!r.hostName?.trim()) { notify.error(new Error("Hostname is required."), "Validation failed"); return; }
      if (seen.has(r.hostName.toLowerCase())) { notify.error(new Error(`Duplicate hostname '${r.hostName}'.`), "Validation failed"); return; }
      seen.add(r.hostName.toLowerCase());
    }
    setBusy(true);
    try {
      await api.updateService(a.resourceGroup, a.name, { properties: { hostnameConfigurations: rows } });
      notify.success("Custom domains were saved.", "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving custom domains failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id={CAP} title={`${a.name} | Custom domains`}>
      <table className="vy-grid" style={{ width: "100%" }}>
        <thead><tr><th>Type</th><th>Hostname</th><th>Default SSL binding</th><th /></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><Select size="small" value={r.type || "Proxy"} onChange={(_, d) => upd(i, "type", d.value)} aria-label={`Type ${i + 1}`}>
                {HOSTNAME_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </Select></td>
              <td><Input size="small" value={r.hostName || ""} onChange={(_, d) => upd(i, "hostName", d.value)} aria-label={`Hostname ${i + 1}`} /></td>
              <td><input type="checkbox" checked={!!r.defaultSslBinding} onChange={(e) => upd(i, "defaultSslBinding", e.target.checked)} aria-label={`Default SSL binding ${i + 1}`} /></td>
              <td><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Remove ${i + 1}`} onClick={() => setRows((xs) => xs.filter((_, j) => j !== i))} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <Button icon={<Add20Regular />} onClick={() => setRows((xs) => [...xs, { type: "Proxy", hostName: "" }])}>Add</Button>
        <Button appearance="primary" disabled={busy} onClick={save}>Save</Button>
      </div>
    </CapabilityContainer>
  );
}

const TIER_NAMES = ["Basic", "Standard", "Premium", "BasicV2", "StandardV2", "PremiumV2"];
const LOCATIONS = ["eastus", "westus", "westeurope", "northeurope", "southeastasia", "centralus"];

export function Locations({ a, reload }) {
  const notify = useNotify();
  const tier = a.sku?.name;
  const multiRegionAllowed = !["Consumption", "Developer"].includes(tier);
  const init = () => (a.properties?.additionalLocations || []).map((l) => ({ ...l, sku: { ...(l.sku || {}) } }));
  const [rows, setRows] = useState(init);
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(init()), [a]);
  const upd = (i, k, v) => setRows((xs) => xs.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const save = async () => {
    setBusy(true);
    try {
      await api.updateService(a.resourceGroup, a.name, { properties: { additionalLocations: rows } });
      notify.success("Locations were saved.", "Saved");
      reload();
    } catch (e) { notify.error(e, "Saving locations failed"); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id={CAP} title={`${a.name} | Locations`}>
      <p style={{ fontSize: 13 }}>Primary location: <b>{locationLabel(a.location)}</b> ({a.sku?.capacity ?? 0} unit{a.sku?.capacity === 1 ? "" : "s"}).</p>
      {!multiRegionAllowed && (
        <p style={{ fontSize: 13 }} className="vy-muted">The {tier} tier does not support additional locations — switch to Basic, Standard or Premium under Pricing tier first.</p>
      )}
      {multiRegionAllowed && (
        <>
          <table className="vy-grid" style={{ width: "100%" }}>
            <thead><tr><th>Region</th><th>Tier</th><th>Units</th><th /></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td><Select size="small" value={r.location || LOCATIONS[0]} onChange={(_, d) => upd(i, "location", d.value)} aria-label={`Region ${i + 1}`}>
                    {LOCATIONS.filter((l) => l !== a.location).map((l) => <option key={l} value={l}>{locationLabel(l)}</option>)}
                  </Select></td>
                  <td><Select size="small" value={r.sku?.name || tier || "Standard"} onChange={(_, d) => upd(i, "sku", { ...r.sku, name: d.value })} aria-label={`Tier ${i + 1}`}>
                    {TIER_NAMES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </Select></td>
                  <td><Input size="small" type="number" min={1} max={12} value={String(r.sku?.capacity ?? 1)} onChange={(_, d) => upd(i, "sku", { ...r.sku, capacity: Number(d.value) || 1 })} aria-label={`Units ${i + 1}`} /></td>
                  <td><Button appearance="subtle" size="small" icon={<Delete20Regular />} aria-label={`Remove region ${i + 1}`} onClick={() => setRows((xs) => xs.filter((_, j) => j !== i))} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <Button icon={<Add20Regular />} onClick={() => setRows((xs) => [...xs, { location: LOCATIONS.find((l) => l !== a.location), sku: { name: tier, capacity: 1 } }])}>Add a location</Button>
            <Button appearance="primary" disabled={busy} onClick={save}>Save</Button>
          </div>
        </>
      )}
    </CapabilityContainer>
  );
}

export function Gateways({ a }) {
  const rows = [{ location: a.location, capacity: a.sku?.capacity ?? 0 }, ...(a.properties?.additionalLocations || [])];
  return (
    <CapabilityContainer id={CAP} title={`${a.name} | Gateways`}>
      <p style={{ fontSize: 13 }}>The managed gateway regions currently deployed for this service.</p>
      <table className="vy-grid" style={{ width: "100%" }}>
        <thead><tr><th>Region</th><th>Units</th><th>Status</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}><td>{locationLabel(r.location)}</td><td>{r.capacity ?? r.sku?.capacity ?? 0}</td><td>Online</td></tr>
          ))}
        </tbody>
      </table>
    </CapabilityContainer>
  );
}
