/* Last Accessed + "Generate policy based on CloudTrail events" — shared by UserDetail,
 * RoleDetail, PolicyDetail and GroupDetail. Both are real, backed by Vyomi's own
 * native-wire activity log (core/iam_core.py: record_activity / GetServiceLastAccessedDetails
 * / the Vyomi-only GeneratePolicyFromActivity) rather than CloudTrail or background
 * telemetry — see the iam.last-accessed / iam.cloudtrail-policy-generator capability
 * notices for exactly what that does and doesn't cover. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import CopyToClipboard from "@cloudscape-design/components/copy-to-clipboard";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export function LastAccessedTab({ arn }) {
  const r = useAsync(() => api.getServiceLastAccessedDetails(arn), [arn]);
  return (
    <CapabilityContainer id="iam.last-accessed" title="Last accessed" counter={r.data ? `(${r.data.length})` : undefined}
      actions={<Button iconName="refresh" onClick={r.reload} ariaLabel="Refresh" />}>
      <Table variant="embedded" items={r.data || []} loading={r.loading} trackBy="ServiceNamespace"
        columnDefinitions={[
          { id: "service", header: "Service", cell: (x) => x.ServiceName },
          { id: "last", header: "Last accessed", cell: (x) => fmtDate(x.LastAuthenticated) },
          { id: "entities", header: "Authenticated entities", cell: (x) => x.TotalAuthenticatedEntities },
        ]}
        empty={<Box textAlign="center" color="inherit">
          <b>No service access data</b>
          <Box variant="p" color="text-body-secondary">Only native-wire requests signed with this principal's own access key are recorded here — see the badge above for what that covers.</Box>
        </Box>} />
    </CapabilityContainer>
  );
}

export function CloudTrailPolicyGenerator({ arn }) {
  const notify = useNotify();
  const [busy, setBusy] = useState(false);
  const [doc, setDoc] = useState(null);
  const generate = async () => {
    setBusy(true);
    try { setDoc(await api.generatePolicyFromActivity(arn)); }
    catch (e) { notify.error(e); }
    finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="iam.cloudtrail-policy-generator" title="Generate policy based on CloudTrail events"
      actions={<Button loading={busy} onClick={generate}>Generate policy</Button>}>
      {doc
        ? <SpaceBetween size="s">
            <Box variant="p" color="text-body-secondary">Generated from Vyomi's native-wire activity log for this principal (see the badge above).</Box>
            <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(JSON.parse(doc), null, 2)}</pre>
            <CopyToClipboard copyButtonText="Copy" copySuccessText="Copied" copyErrorText="Couldn't copy" textToCopy={doc} />
          </SpaceBetween>
        : <Box color="text-body-secondary">Choose "Generate policy" to build a policy document from this principal's recorded activity.</Box>}
    </CapabilityContainer>
  );
}
