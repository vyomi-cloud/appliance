/* Quotas & System Limits — a dashboard over resources this console itself creates
 * (service accounts, their keys, custom roles, workload identity pools, organization
 * policy constraints): real counts from the native wire against GCP's documented
 * default per-project quota values. limited: request-rate quotas (e.g. "IAM API
 * requests per minute") need traffic metering Vyomi doesn't run, so they aren't shown. */
import { ErrorAlert, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import * as api from "./api.js";

const DEFAULT_LIMITS = {
  "Service accounts": 100,
  "Service account keys (busiest account)": 10,
  "IAM custom roles": 300,
  "Workload identity pools": 100,
  "Organization policy constraints": 500,
};

async function loadQuotas() {
  const [sas, roles, pools, policies] = await Promise.all([
    api.listServiceAccounts(), api.listCustomRoles(), api.listWorkloadIdentityPools(), api.listOrgPolicies(),
  ]);
  const keyCounts = await Promise.all(sas.map((sa) => api.listKeys(sa.email)));
  const busiestKeyCount = keyCounts.reduce((max, ks) => Math.max(max, ks.length), 0);
  const usage = {
    "Service accounts": sas.length,
    "Service account keys (busiest account)": busiestKeyCount,
    "IAM custom roles": roles.length,
    "Workload identity pools": pools.length,
    "Organization policy constraints": policies.length,
  };
  return Object.entries(DEFAULT_LIMITS).map(([name, limit]) => ({ name, limit, usage: usage[name] }));
}

export default function QuotasSystemLimits() {
  const list = useAsync(loadQuotas, []);
  return (
    <>
      <PageHeader title="Quotas & System Limits" />
      <ErrorAlert error={list.error} title="Failed to load quota usage" />
      <CapabilityContainer id="gcp.iam-admin.quotas-system-limits" title="IAM & Admin quotas">
        <ResourceTable resourceName="quotas" items={list.data || []} rowKey={(q) => q.name} loading={list.loading} onRetry={list.reload}
          filterPlaceholder="Filter"
          columns={[
            { id: "name", header: "Quota", cell: (q) => q.name },
            { id: "scope", header: "Scope", cell: () => "Per project" },
            { id: "limit", header: "Limit", cell: (q) => q.limit },
            { id: "usage", header: "Current usage", cell: (q) => q.usage },
          ]} />
      </CapabilityContainer>
    </>
  );
}
