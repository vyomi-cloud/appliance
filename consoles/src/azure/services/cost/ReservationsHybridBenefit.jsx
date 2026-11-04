import { useEffect, useState } from "react";
import { Button, Input, Select, Switch, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import {
  deleteReservation, listReservations, listVmSizes, listVmsForHybridBenefit, putReservation,
  RESERVATION_TERM_LABEL, RESERVATION_TERMS, setHybridBenefit,
} from "./api.js";
import { ErrorBar, fmtDate, Loading } from "../../kit/common.jsx";

const RENEWAL_LABEL = (p) => (p.renew ? `On — ${fmtDate(p.expiryDateTime)}` : "Off");
const AHB_LICENSE_TYPES = new Set(["windows_server", "windows_server_perpetual"]);

export default function ReservationsHybridBenefit() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [sku, setSku] = useState("");
  const [sizes, setSizes] = useState([]);
  const [quantity, setQuantity] = useState("1");
  const [term, setTerm] = useState("P1Y");

  const load = () => { setLoading(true); setError(null); listReservations().then(setItems).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);
  useEffect(() => { listVmSizes().then((v) => { setSizes(v); setSku((s) => s || v[0]?.name || ""); }).catch(() => setSizes([])); }, []);

  const [vms, setVms] = useState(null);
  const loadVms = () => { setVms(null); listVmsForHybridBenefit().then(setVms).catch(() => setVms([])); };
  useEffect(loadVms, []);

  const columns = [
    { key: "name", label: "Name" },
    { key: "status", label: "Status", value: (p) => p.properties.provisioningState },
    { key: "sku", label: "Instance size", value: (p) => p.properties.skuName },
    { key: "quantity", label: "Quantity", value: (p) => p.properties.quantity },
    { key: "term", label: "Term", value: (p) => RESERVATION_TERM_LABEL[p.properties.term] || p.properties.term },
    { key: "util", label: "Utilization", value: (p) => `${p.properties.utilization}%` },
    { key: "renewal", label: "Renewal", value: (p) => RENEWAL_LABEL(p.properties) },
  ];

  return (
    <CostShell active="reservations">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.reservations_hybrid_benefit" title="Reservations" actions={
          <Button appearance="primary" onClick={() => setCreating((v) => !v)}>{creating ? "Cancel" : "Purchase"}</Button>
        }>
          {creating && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "0 0 12px", flexWrap: "wrap" }}>
              <Input placeholder="Reservation name" value={name} onChange={(_, d) => setName(d.value)} aria-label="Reservation name" />
              <Select value={sku} onChange={(_, d) => setSku(d.value)} aria-label="Instance size">
                {sizes.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
              </Select>
              <Input type="number" min="1" placeholder="Quantity" value={quantity} onChange={(_, d) => setQuantity(d.value)} aria-label="Quantity" style={{ width: 100 }} />
              <Select value={term} onChange={(_, d) => setTerm(d.value)} aria-label="Term">
                {RESERVATION_TERMS.map((t) => <option key={t} value={t}>{RESERVATION_TERM_LABEL[t]}</option>)}
              </Select>
              <Button appearance="primary" disabled={!name || !sku || !quantity} onClick={async () => {
                await putReservation(name, { properties: { term, skuName: sku, quantity: Number(quantity) } });
                setName(""); setCreating(false); load();
              }}>Create</Button>
            </div>
          )}
          <ErrorBar error={error} title="Failed to load reservations" />
          <BrowseGrid resourceName="reservation" items={items} columns={columns} loading={loading} error={error}
            onRefresh={load} onDelete={async (rows) => { await Promise.all(rows.map((r) => deleteReservation(r.name))); load(); }}
            emptyAction={<Button appearance="primary" onClick={() => setCreating(true)}>Purchase Now</Button>} csvName="reservations.csv" />
        </CapabilityContainer>

        <section className="vy-form-section">
          <h3>Azure Hybrid Benefit</h3>
          <p className="vy-muted" style={{ fontSize: 13 }}>Use an existing Windows Server license to lower the cost of a virtual machine.</p>
          {vms === null ? <Loading /> : !vms.length ? <p>No virtual machines in your inventory yet.</p> : (
            <Table size="small" aria-label="Azure Hybrid Benefit">
              <TableHeader><TableRow><TableHeaderCell>Virtual machine</TableHeaderCell><TableHeaderCell>Resource group</TableHeaderCell><TableHeaderCell>Hybrid Benefit</TableHeaderCell></TableRow></TableHeader>
              <TableBody>
                {vms.map((vm) => {
                  const enabled = AHB_LICENSE_TYPES.has(String(vm.properties?.licenseType || "").toLowerCase());
                  return (
                    <TableRow key={vm.id}>
                      <TableCell>{vm.name}</TableCell>
                      <TableCell>{vm.resourceGroup}</TableCell>
                      <TableCell>
                        <Switch checked={enabled} label={enabled ? "On" : "Off"}
                          onChange={async (_, d) => { await setHybridBenefit(vm.resourceGroup, vm.name, d.checked); loadVms(); }} />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </section>
      </div>
    </CostShell>
  );
}
