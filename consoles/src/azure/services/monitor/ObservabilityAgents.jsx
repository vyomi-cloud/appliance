/* Observability agents (preview): the real mechanic behind VM insights data collection is a
 * Microsoft.Insights/dataCollectionRuleAssociations extension resource linking a machine to a
 * Data Collection Rule (core/azure_monitor_core.py upsert_dcr_association) — modelled here, not
 * a cosmetic "agent installed" checkbox. No agent process actually runs or ships data. */
import { useEffect, useState } from "react";
import { Button, Select } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { listResourcesOfType, RESOURCE_TYPES, listDataCollectionRules, listDcrAssociations, putDcrAssociation, deleteDcrAssociation } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";

const VM_TYPE = RESOURCE_TYPES.find((r) => r.type === "virtualMachines");

export default function ObservabilityAgents() {
  const [vms, setVms] = useState(null);
  const [dcrs, setDcrs] = useState([]);
  const [assoc, setAssoc] = useState({});     // vm id -> association record (or null)
  const [picked, setPicked] = useState({});   // vm id -> selected dcr id for the picker
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);

  const load = () => {
    setError(null);
    Promise.all([listResourcesOfType(VM_TYPE), listDataCollectionRules()]).then(async ([vmList, dcrList]) => {
      setVms(vmList);
      setDcrs(dcrList);
      const pairs = await Promise.all(vmList.map(async (vm) => [vm.id, (await listDcrAssociations(vm.id).catch(() => []))[0] || null]));
      setAssoc(Object.fromEntries(pairs));
    }).catch(setError);
  };
  useEffect(load, []);

  const associate = async (vm) => {
    const dcrId = picked[vm.id] || dcrs[0]?.id;
    if (!dcrId) return;
    setActionError(null);
    try { await putDcrAssociation(vm.id, "default", dcrId); load(); } catch (e) { setActionError(e); }
  };
  const disassociate = async (vm) => {
    setActionError(null);
    try { await deleteDcrAssociation(vm.id, assoc[vm.id].name); load(); } catch (e) { setActionError(e); }
  };

  const columns = [
    { key: "name", label: "Resource" },
    { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
    {
      key: "collection", label: "Data collection", render: (vm) => {
        const a = assoc[vm.id];
        if (a) {
          const dcr = dcrs.find((d) => d.id.toLowerCase() === a.properties.dataCollectionRuleId.toLowerCase());
          return <span>Collecting — {dcr?.name || a.properties.dataCollectionRuleId} <Button size="small" appearance="subtle" onClick={() => disassociate(vm)}>Remove</Button></span>;
        }
        return (
          <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
            Not configured
            {dcrs.length > 0 && (
              <>
                <Select size="small" value={picked[vm.id] || dcrs[0].id} onChange={(_, d) => setPicked((p) => ({ ...p, [vm.id]: d.value }))} aria-label={`Data collection rule for ${vm.name}`}>
                  {dcrs.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </Select>
                <Button size="small" appearance="primary" onClick={() => associate(vm)}>Enable</Button>
              </>
            )}
          </span>
        );
      },
    },
  ];

  return (
    <MonitorShell active="observabilityagents" pageTitle="Observability agents (preview)">
      <CapabilityContainer id="azure.monitor.observability_agents" title="Observability agents (preview)" actions={
        dcrs.length === 0 ? <a href="#/monitor/createdatacollectionrule">Create a data collection rule</a> : null
      }>
        <ErrorBar error={actionError} />
        {vms === null ? <Loading /> : (
          <BrowseGrid resourceName="virtual machine" items={vms} columns={columns} loading={false} error={error} onRefresh={load} csvName="observability-agents.csv" />
        )}
      </CapabilityContainer>
    </MonitorShell>
  );
}
