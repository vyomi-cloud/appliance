/* Security Insights — a small set of real IAM-lint rules evaluated live against this
 * project's actual policy bindings, service-account keys and issued credentials on
 * every call (not GCP's full IAM Recommender rule catalog). */
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function SecurityInsights() {
  const list = useAsync(() => api.listSecurityInsights(), []);

  return (
    <>
      <PageHeader title="Security Insights" />
      <CapabilityContainer id="gcp.iam-admin.security-insights" title="Insights">
        <ErrorAlert error={list.error} title="Failed to load insights" />
        <ResourceTable resourceName="insights" items={list.data || []} rowKey={(i) => i.name} loading={list.loading} onRetry={list.reload}
          filterPlaceholder="Filter" empty="No findings — nothing to flag right now"
          columns={[
            { id: "category", header: "Category", sortField: "category", cell: (i) => i.category },
            { id: "severity", header: "Severity", sortField: "severity", cell: (i) => i.severity },
            { id: "description", header: "Description", cell: (i) => i.description },
          ]} />
      </CapabilityContainer>
    </>
  );
}
