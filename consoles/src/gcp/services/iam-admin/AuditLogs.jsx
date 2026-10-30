/* Data Access audit logs configuration — stored on the project's IAM policy
 * (policy.auditConfigs), round-tripped through the same native :getIamPolicy /
 * :setIamPolicy verbs the Allow tab uses. config_only: Vyomi does not gate or emit
 * audit log entries based on it. */
import { useState } from "react";
import { Alert, Button, Checkbox, Stack } from "@mui/material";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { ErrorAlert, NotSimulated, PageHeader } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const SERVICES = [
  "storage.googleapis.com", "iam.googleapis.com", "cloudresourcemanager.googleapis.com", "pubsub.googleapis.com",
  "secretmanager.googleapis.com", "cloudkms.googleapis.com", "sqladmin.googleapis.com", "compute.googleapis.com",
  "run.googleapis.com", "cloudfunctions.googleapis.com", "artifactregistry.googleapis.com", "monitoring.googleapis.com",
];
const LOG_TYPES = [["ADMIN_READ", "Admin read"], ["DATA_READ", "Data read"], ["DATA_WRITE", "Data write"]];

export default function AuditLogs() {
  const notify = useNotify();
  const pol = useAsync(() => api.getIamPolicy(), []);
  const [sel, setSel] = useState([]);
  const [showInfo, setShowInfo] = useState(true);
  const [showDefault, setShowDefault] = useState(false);

  const configs = pol.data?.auditConfigs || [];
  const byService = Object.fromEntries(configs.map((c) => [c.service, c]));
  const rows = SERVICES.map((service) => ({ service, config: byService[service] || { service, auditLogConfigs: [] } }));

  const toggle = async (service, logType, on) => {
    const cfg = byService[service] || { service, auditLogConfigs: [] };
    const next = { ...cfg, auditLogConfigs: cfg.auditLogConfigs.filter((l) => l.logType !== logType) };
    if (on) next.auditLogConfigs = [...next.auditLogConfigs, { logType, exemptedMembers: [] }];
    const nextConfigs = [...configs.filter((c) => c.service !== service), ...(next.auditLogConfigs.length ? [next] : [])];
    try {
      await api.setIamPolicy({ ...pol.data, auditConfigs: nextConfigs });
      notify.success(`${on ? "Enabled" : "Disabled"} ${logType.replace("_", " ").toLowerCase()} logging for ${service}`);
      pol.reload();
    } catch (e) { notify.error(e); }
  };

  const hasLog = (cfg, type) => (cfg.auditLogConfigs || []).some((l) => l.logType === type);

  return (
    <>
      <PageHeader title="Audit logs" actions={
        <Stack direction="row" spacing={1}>
          <Button onClick={() => setShowDefault((v) => !v)}>Set default configuration</Button>
          <Button onClick={() => setShowInfo((v) => !v)}>{showInfo ? "Hide info panel" : "Show info panel"}</Button>
          <Button href="https://cloud.google.com/logging/docs/audit" target="_blank" rel="noreferrer">Learn</Button>
        </Stack>} />
      {showInfo && <Alert severity="info" sx={{ mb: 2 }}>Admin Activity and System Event audit logs are always written and can't be configured. Data Access audit logs are disabled by default except for Vyomi's own console actions.</Alert>}
      {showDefault && <NotSimulated feature="Default audit log configuration applied to future services" />}
      <ErrorAlert error={pol.error} title="Failed to load audit log configuration" />
      <CapabilityContainer id="gcp.iam-admin.audit-logs-config" title="Data access audit logs configuration">
        <ResourceTable resourceName="services" items={rows} rowKey={(r) => r.service} loading={pol.loading} onRetry={pol.reload}
          selectable selected={sel} onSelectedChange={setSel} filterPlaceholder="Filter"
          columns={[
            { id: "service", header: "Service", sortField: "service", cell: (r) => r.service },
            ...LOG_TYPES.map(([type, label]) => ({
              id: type, header: label,
              cell: (r) => <Checkbox size="small" checked={hasLog(r.config, type)} inputProps={{ "aria-label": `${label} for ${r.service}` }}
                onChange={(e) => toggle(r.service, type, e.target.checked)} />,
            })),
            { id: "exempted", header: "Exempted principals", cell: (r) => (r.config.auditLogConfigs || []).flatMap((l) => l.exemptedMembers || []).join(", ") || "None" },
            { id: "inherited", header: "Inherited exempted principals", cell: () => "None" },
          ]} />
      </CapabilityContainer>
    </>
  );
}
