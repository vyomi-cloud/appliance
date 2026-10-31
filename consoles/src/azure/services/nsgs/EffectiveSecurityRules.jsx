/* Effective security rules — reached from this NSG's "Help" menu. For a picked network
 * interface, merges the custom + default inbound/outbound rules from BOTH the interface's
 * own network security group and its subnet's network security group (real ARM reads —
 * core/capabilities/azure/nsgs.json azure.nsgs.effective_rules), the same two-NSG picture
 * `az network nic show-effective-nsg` / the real portal's page shows. It lists the rule set;
 * it does not evaluate a packet (that's IP flow verify — azure.nsgs.network_watcher). */
import { useEffect, useState } from "react";
import { Select, Spinner, Tab, TabList } from "@fluentui/react-components";
import { useAsync } from "../../../common/useAsync.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar } from "../../kit/common.jsx";
import * as api from "./api.js";

const PORT = (r) => r.properties?.destinationPortRange || (r.properties?.destinationPortRanges || []).join(",") || r.port || "*";

function effectiveRows(direction, nicNsgName, nicRules, subnetNsgName, subnetRules) {
  const tag = (rules, appliesTo) => rules.filter((r) => r.properties?.direction === direction).map((r) => ({ ...r, appliesTo }));
  const defaults = (name) => (name ? api.DEFAULT_RULES.filter((r) => r.direction === direction).map((r) => ({ ...r, appliesTo: name })) : []);
  const rows = [
    ...tag(nicRules, nicNsgName && `Network interface: ${nicNsgName}`),
    ...defaults(nicNsgName && `Network interface: ${nicNsgName}`),
    ...tag(subnetRules, subnetNsgName && `Subnet: ${subnetNsgName}`),
    ...defaults(subnetNsgName && `Subnet: ${subnetNsgName}`),
  ];
  return rows.sort((x, y) => (x.properties?.priority ?? x.priority) - (y.properties?.priority ?? y.priority));
}

function RulesTable({ rows }) {
  if (!rows.length) return <p className="vy-muted">No security rules to display.</p>;
  return (
    <table className="vy-grid">
      <thead><tr><th>Priority</th><th>Name</th><th>Port</th><th>Protocol</th><th>Source</th><th>Destination</th><th>Action</th><th>Applies to</th></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.name}-${i}`}>
            <td>{r.properties?.priority ?? r.priority}</td>
            <td>{r.name}</td>
            <td>{PORT(r)}</td>
            <td>{r.properties?.protocol ?? r.protocol}</td>
            <td>{r.properties?.sourceAddressPrefix ?? r.source}</td>
            <td>{r.properties?.destinationAddressPrefix ?? r.destination}</td>
            <td>{r.properties?.access ?? r.access}</td>
            <td>{r.appliesTo}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function EffectiveSecurityRules({ a }) {
  const nics = useAsync(() => api.listInterfacesInScope(a.id), [a.id]);
  const [nicId, setNicId] = useState("");
  const [dir, setDir] = useState("Inbound");
  const list = nics.data || [];
  useEffect(() => { if (!nicId && list.length) setNicId(list[0].id); }, [list.length, nicId]);
  const nic = list.find((n) => n.id === nicId);
  const eff = useAsync(() => (nic ? api.loadEffectiveSecurityRules(nic) : Promise.resolve(null)), [nic?.id]);

  return (
    <CapabilityContainer id="azure.nsgs.effective_rules" title={`${a.name} | Effective security rules`}>
      {nics.loading ? <Spinner size="tiny" /> : !list.length ? (
        <p>No network interface is associated with this network security group (directly or through its subnet) yet.</p>
      ) : (
        <>
          <div style={{ marginBottom: 12, maxWidth: 420 }}>
            <Select value={nicId} onChange={(_, d) => setNicId(d.value)} aria-label="Network interface">
              {list.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </Select>
          </div>
          <ErrorBar error={eff.error} />
          {eff.loading || !eff.data ? <Spinner size="tiny" /> : (
            <>
              <TabList selectedValue={dir} onTabSelect={(_, d) => setDir(d.value)} aria-label="Effective security rules direction">
                <Tab value="Inbound">Inbound rules</Tab>
                <Tab value="Outbound">Outbound rules</Tab>
              </TabList>
              <div style={{ marginTop: 12 }}>
                <RulesTable rows={effectiveRows(dir, eff.data.nicNsgName, eff.data.nicRules, eff.data.subnetNsgName, eff.data.subnetRules)} />
              </div>
            </>
          )}
        </>
      )}
    </CapabilityContainer>
  );
}
