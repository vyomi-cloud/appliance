/* Network manager | Deployments: commit connectivity / security admin configurations and evaluate the deployed rules
 * (core/azure_nm_engine_core.py).  Connectivity commits write real peerings into the member virtual networks. */
import { useState } from "react";
import { Button, Checkbox, Field, Input, Select, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { restJson } from "../../../common/wire.js";
import { ErrorBar, Loading } from "../../kit/common.jsx";

const V = "2023-09-01";
export default function Deployments({ base }) {
  const notify = useNotify();
  const eng = `${base}/providers/Microsoft.Vyomi/networkManagerEngine`;
  const conn = useAsync(async () => (await restJson("GET", `${base}/connectivityConfigurations`, { query: { "api-version": V } })).value || [], [base]);
  const sec = useAsync(async () => (await restJson("GET", `${base}/securityAdminConfigurations`, { query: { "api-version": V } })).value || [], [base]);
  const status = useAsync(() => restJson("GET", `${eng}/status`, { query: { "api-version": V } }), [base]);
  const vnets = useAsync(async () => (await restJson("GET", `/subscriptions/${base.split("/")[2]}/providers/Microsoft.Network/virtualNetworks`, { query: { "api-version": V } })).value || [], [base]);
  const [pick, setPick] = useState({});
  const [kind, setKind] = useState("Connectivity");
  const [ev, setEv] = useState({ vnetId: "", direction: "Inbound", protocol: "Tcp", sourceAddress: "8.8.8.8", destinationAddress: "10.0.0.4", destinationPort: "22" });
  const [res, setRes] = useState(null);
  const list = kind === "Connectivity" ? conn.data : sec.data;
  const ids = Object.keys(pick).filter((k) => pick[k]);
  const deploy = async () => {
    try {
      const r = await restJson("POST", `${eng}/deploy`, { query: { "api-version": V }, body: { commitType: kind, configurationIds: ids } });
      notify.success(kind === "Connectivity" ? `Deployed: ${r.peeringsCreated} peerings written to the member virtual networks.` : `Deployed ${r.rulesDeployed} admin rule(s).`, "Deployment");
      status.reload();
    } catch (e) { notify.error(e, "Deployment failed"); }
  };
  const evaluate = async () => {
    try { setRes(await restJson("POST", `${eng}/evaluate`, { query: { "api-version": V }, body: { ...ev, destinationPort: Number(ev.destinationPort) } })); } catch (e) { notify.error(e, "Evaluation failed"); }
  };
  const set = (k) => (_, d) => setEv({ ...ev, [k]: d.value });
  return (
    <>
      <p>A deployment makes the configuration take effect. Connectivity commits write real peerings into the member virtual networks (a commit replaces the peerings this manager created before). Security admin commits activate the rules for the evaluation below.</p>
      <Field label="Configuration type"><Select value={kind} onChange={(_, d) => { setKind(d.value); setPick({}); }}><option>Connectivity</option><option>SecurityAdmin</option></Select></Field>
      {(list || []).length === 0 ? <p>No {kind} configurations yet.</p> : (list || []).map((c) => <div key={c.id}><Checkbox checked={!!pick[c.id]} onChange={(_, d) => setPick({ ...pick, [c.id]: d.checked })} label={c.name} /></div>)}
      <div style={{ margin: "8px 0" }}><Button appearance="primary" disabled={!ids.length} onClick={deploy}>Deploy</Button></div>
      <h3>Deployment history</h3>
      {status.error ? <ErrorBar error={status.error} title="Could not read deployments" /> : status.loading && !status.data ? <Loading /> : (
        <Table size="small" aria-label="Deployments"><TableHeader><TableRow>{["Time", "Type", "Configurations", "Result"].map((h) => <TableHeaderCell key={h}>{h}</TableHeaderCell>)}</TableRow></TableHeader>
          <TableBody>{((status.data?.commits) || []).length === 0 ? <TableRow><TableCell colSpan={4}>Nothing deployed.</TableCell></TableRow> : [...status.data.commits].reverse().map((c, i) => <TableRow key={i}><TableCell>{c.commitTime}</TableCell><TableCell>{c.commitType}</TableCell><TableCell>{c.configurationIds.map((x) => x.split("/").pop()).join(", ")}</TableCell><TableCell>{c.deploymentStatus}{c.peeringsCreated !== undefined ? `, ${c.peeringsCreated} peerings` : ""}{c.rulesDeployed !== undefined ? `, ${c.rulesDeployed} rules` : ""}</TableCell></TableRow>)}</TableBody></Table>
      )}
      <h3>Effective security admin rules</h3>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}>
        <Field label="Virtual network"><Select value={ev.vnetId} onChange={set("vnetId")}><option value="">Select…</option>{(vnets.data || []).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</Select></Field>
        <Field label="Direction"><Select value={ev.direction} onChange={set("direction")}><option>Inbound</option><option>Outbound</option></Select></Field>
        <Field label="Protocol"><Select value={ev.protocol} onChange={set("protocol")}><option>Tcp</option><option>Udp</option><option>Icmp</option></Select></Field>
        <Field label="Source IP"><Input value={ev.sourceAddress} onChange={set("sourceAddress")} /></Field>
        <Field label="Destination IP"><Input value={ev.destinationAddress} onChange={set("destinationAddress")} /></Field>
        <Field label="Destination port"><Input value={ev.destinationPort} onChange={set("destinationPort")} /></Field>
        <Button disabled={!ev.vnetId} onClick={evaluate}>Evaluate</Button>
      </div>
      {res && <p><b>{res.verdict}</b>{res.matchedRule ? ` by rule ${res.matchedRule.rule} (priority ${res.matchedRule.priority}, ${res.matchedRule.access}) in ${res.matchedRule.collection}` : ""}. Next: {res.nextHop}. {res.note || ""}</p>}
    </>
  );
}
