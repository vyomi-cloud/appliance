import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow } from "@fluentui/react-components";
import CostShell from "./CostShell.jsx";
import { listSubscriptions } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ErrorBar, Loading } from "../../kit/common.jsx";

export default function AzureSubscriptions() {
  const [subs, setSubs] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { listSubscriptions().then(setSubs).catch(setError); }, []);

  return (
    <CostShell active="subscriptions">
      <div className="vy-page">
        <CapabilityContainer id="azure.cost.azure_subscriptions" title="Azure subscriptions">
          <ErrorBar error={error} title="Failed to load subscriptions" />
          {subs === null ? <Loading /> : (
            <Table size="small" aria-label="Azure subscriptions">
              <TableHeader><TableRow><TableHeaderCell>Subscription name</TableHeaderCell><TableHeaderCell>Subscription ID</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell></TableRow></TableHeader>
              <TableBody>
                {subs.map((s) => <TableRow key={s.subscriptionId}><TableCell>{s.displayName}</TableCell><TableCell>{s.subscriptionId}</TableCell><TableCell>{s.state}</TableCell></TableRow>)}
              </TableBody>
            </Table>
          )}
        </CapabilityContainer>
      </div>
    </CostShell>
  );
}
