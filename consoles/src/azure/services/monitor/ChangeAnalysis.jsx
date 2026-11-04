import { useEffect, useState } from "react";
import MonitorShell from "./MonitorShell.jsx";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { listActivityLog } from "./api.js";
import { parseId } from "../../kit/arm.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { fmtDate, NotSimulated } from "../../kit/common.jsx";

const CHANGE_TYPE = (op) => (/delete/i.test(op) ? "Delete" : /create/i.test(op) ? "Create" : "Update");
const resourceType = (id) => { const p = (id || "").split("/").filter(Boolean); const i = p.findIndex((x) => x.toLowerCase() === "providers"); return i >= 0 && p[i + 2] ? `${p[i + 1]}/${p[i + 2]}` : "--"; };

export default function ChangeAnalysis() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const load = () => { setLoading(true); setError(null); listActivityLog().then((ev) => setItems(ev.map((e, i) => ({ ...e, _key: e.id || i })))).catch(setError).finally(() => setLoading(false)); };
  useEffect(load, []);

  const columns = [
    { key: "name", label: "Name", value: (e) => parseId(e.resourceId || "").name || e.resourceId },
    { key: "type", label: "Resource type", value: (e) => resourceType(e.resourceId) },
    { key: "change", label: "Change type", value: (e) => CHANGE_TYPE(e.operationName?.value || "") },
    { key: "by", label: "Changed by", value: (e) => e.caller },
    { key: "time", label: "Time", value: (e) => fmtDate(e.eventTimestamp) },
  ];

  return (
    <MonitorShell active="changeanalysis">
      <CapabilityContainer id="azure.monitor.change_analysis" title="Change Analysis">
        <BrowseGrid resourceName="change" rowKey={(e) => e._key} items={items} columns={columns} loading={loading} error={error}
          onRefresh={load} csvName="change-analysis.csv" />
      </CapabilityContainer>
      <NotSimulated feature="Open query, Group by none" />
    </MonitorShell>
  );
}
