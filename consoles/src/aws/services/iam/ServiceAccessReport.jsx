/* SCP "Service access report": the real GenerateOrganizationsAccessReport/GetOrganizationsAccessReport pair, for one of the
 * policy's targets, scoped to the services the SCP allows. Derived from recorded management-account activity (see the
 * capability's limitations). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

function pathFor(model, targetId) {
  const chain = [];
  const ou = (model.ous || []).find((u) => u.Id === targetId);
  const acct = (model.accounts || []).find((a) => a.Id === targetId);
  let cur = ou || acct;
  while (cur && cur.ParentId && cur.ParentId !== model.root.Id) { chain.unshift(cur.ParentId); cur = (model.ous || []).find((u) => u.Id === cur.ParentId); }
  return [model.org.Id, model.root.Id, ...chain, ...(targetId === model.root.Id ? [] : [targetId])].join("/");
}

export default function ServiceAccessReport({ policy, model }) {
  const [pick, setPick] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [report, setReport] = useState(null);
  const options = policy.targets.map((t) => ({ value: t.TargetId, label: `${t.Name} (${t.Type})` }));
  const run = async () => {
    setBusy(true); setError(null); setReport(null);
    try { setReport(await api.organizationsAccessReport(pathFor(model, pick.value), policy.PolicySummary.Id)); }
    catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <CapabilityContainer id="iam.organizations.service-access-report" title="Service access report"
      actions={<SpaceBetween direction="horizontal" size="xs">
        <Select selectedOption={pick} onChange={({ detail }) => setPick(detail.selectedOption)} options={options} placeholder="Choose a target" ariaLabel="Report target"
          empty="Attach this policy to a root, OU or account first" />
        <Button disabled={!pick} loading={busy} onClick={run}>Generate report</Button>
      </SpaceBetween>}>
      <SpaceBetween size="m">
        {error && <ErrorAlert error={error} />}
        {report && (
          <ColumnLayout columns={3} variant="text-grid">
            <div><Box variant="awsui-key-label">Status</Box>{report.JobStatus}</div>
            <div><Box variant="awsui-key-label">Services allowed by this SCP</Box>{report.NumberOfServicesAccessible}</div>
            <div><Box variant="awsui-key-label">Allowed but never accessed</Box>{report.NumberOfServicesNotAccessed}</div>
          </ColumnLayout>
        )}
        <Table variant="embedded" items={report?.AccessDetails || []} trackBy="ServiceNamespace"
          columnDefinitions={[
            { id: "svc", header: "Service", isRowHeader: true, cell: (r) => r.ServiceName },
            { id: "ns", header: "Namespace", cell: (r) => r.ServiceNamespace },
            { id: "last", header: "Last accessed", cell: (r) => fmtDate(r.LastAuthenticatedTime) },
            { id: "ent", header: "Authenticated entities", cell: (r) => r.TotalAuthenticatedEntities },
          ]}
          empty={<Box textAlign="center" color="text-body-secondary">{report ? "No recorded service activity under this target." : "Choose a target and generate the report."}</Box>} />
      </SpaceBetween>
    </CapabilityContainer>
  );
}
