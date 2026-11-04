import { useEffect, useState } from "react";
import { Button, Checkbox, Radio, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import { listSubscriptions } from "./api.js";
import { Loading } from "../../kit/common.jsx";

export default function ChangeScope() {
  const [subs, setSubs] = useState(null);
  const [picked, setPicked] = useState(null);
  const [onlySelected, setOnlySelected] = useState(false);
  useEffect(() => {
    listSubscriptions().then((ss) => { setSubs(ss); setPicked(ss[0]?.subscriptionId); }).catch(() => setSubs([]));
  }, []);

  if (subs === null) return <CostShell active="changescope"><Loading /></CostShell>;
  const rows = onlySelected ? subs.filter((s) => s.subscriptionId === picked) : subs;

  return (
    <CostShell active="changescope">
      <div className="vy-page">
        <section className="vy-form-section">
          <h3>Select scope</h3>
          <Table size="small" aria-label="Scope">
            <TableHeader>
              <TableRow><TableHeaderCell /><TableHeaderCell>Name</TableHeaderCell><TableHeaderCell>Type</TableHeaderCell></TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((s) => (
                <TableRow key={s.subscriptionId}>
                  <TableCell><Radio checked={picked === s.subscriptionId} onChange={() => setPicked(s.subscriptionId)} aria-label={`Select ${s.displayName}`} /></TableCell>
                  <TableCell>{s.displayName}</TableCell>
                  <TableCell>Subscription</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div style={{ margin: "12px 0" }}>
            <Checkbox label="Only show subscriptions selected in the global filter." checked={onlySelected} onChange={(_, d) => setOnlySelected(d.checked)} />
          </div>
          <Button appearance="primary" onClick={() => { location.hash = "#/cost/overview"; }}>Select</Button>{" "}
          <Button onClick={() => { location.hash = "#/cost/overview"; }}>Cancel</Button>
        </section>
      </div>
    </CostShell>
  );
}
