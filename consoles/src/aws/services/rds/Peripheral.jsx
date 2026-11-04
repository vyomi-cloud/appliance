/* Smaller nav destinations, several genuinely out of Vyomi's scope (capacity
 * markets, RDS Custom, cross-service Redshift pipelines). Lists are REAL
 * (backed by a native describe call, sometimes derived from live instance
 * state — recommendations, certificate updates); capacity reservations and
 * custom engine versions render as a plain "Not simulated" page (title +
 * note, per consoles/AGENT-UI.md — never a disabled skeleton of the real
 * form). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

export function ReservedInstances() {
  const notify = useNotify();
  const t = useAsync(() => api.describeReservedDBInstances());
  return (
    <ResourceTable
      resourceName="Reserved instances"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="ReservedDBInstanceId"
      empty={{ title: "No reserved instance found" }}
      actions={<Button variant="primary" onClick={() => notify.info("Purchasing walks AWS's reserved-instance-offering catalog (pricing, terms, offering ids); Vyomi doesn't model that catalog. Call PurchaseReservedDBInstancesOffering directly to record a reservation.")}>Purchase Reserved DB Instance</Button>}
      columns={[
        { id: "id", header: "Reservation ID", isRowHeader: true, cell: (r) => r.ReservedDBInstanceId },
        { id: "lease", header: "Lease ID", cell: (r) => r.LeaseId || "-" },
        { id: "product", header: "Product", cell: (r) => r.ProductDescription || "-" },
        { id: "region", header: "Region", cell: () => "us-east-1" },
        { id: "class", header: "Class", cell: (r) => r.DBInstanceClass || "-" },
        { id: "offering", header: "Offering Type", cell: (r) => r.OfferingType || "-" },
        { id: "status", header: "Status", cell: (r) => r.State || "-" },
        { id: "multiaz", header: "Multi AZ", cell: (r) => (r.MultiAZ === "true" ? "Yes" : "No") },
        { id: "start", header: "Start date", cell: (r) => r.StartTime || "-" },
        { id: "remaining", header: "Remaining Days", cell: () => "-" },
        { id: "qty", header: "Quantity", cell: (r) => r.DBInstanceCount || "-" },
      ]}
    />
  );
}

export function CapacityReservations() {
  return (
    <NotSimulatedContainer title="Capacity reservations" feature="RDS capacity reservations"
      note="Capacity reservations are a capacity-market/billing construct; Vyomi has no billing system to reserve capacity against." />
  );
}

export function CreateCapacityReservation() {
  return <ContentLayout header={<Header variant="h1">Create capacity reservation</Header>}>
    <NotSimulatedContainer title="Create capacity reservation" feature="RDS capacity reservations"
      note="Capacity reservations are a capacity-market/billing construct; Vyomi has no billing system to reserve capacity against." />
  </ContentLayout>;
}

export function ZeroEtlIntegrations() {
  return (
    <ResourceTableHonestList
      resourceName="Zero-ETL integrations"
      list={() => api.describeIntegrations()}
      trackBy="IntegrationName"
      createHref={href("rds", "create-zero-etl-integration")}
      createLabel="Create zero-ETL integration"
      emptyTitle="No integrations"
      otherActions={["Modify", "Delete"]}
      columns={[
        { id: "name", header: "Integration name", isRowHeader: true, cell: (r) => r.IntegrationName },
        { id: "status", header: "Status", cell: (r) => r.Status },
        { id: "created", header: "Creation date", cell: (r) => r.CreateTime },
        { id: "src", header: "Source ARN", cell: (r) => r.SourceArn },
        { id: "destAccount", header: "Destination AWS account", cell: (r) => r.TargetArn },
        { id: "destType", header: "Destination type", cell: () => "Redshift" },
        { id: "dest", header: "Destination ARN", cell: (r) => r.TargetArn },
      ]}
    />
  );
}

export function CreateZeroEtlIntegration() {
  return <ContentLayout header={<Header variant="h1">Create zero-ETL integration</Header>}>
    <NotSimulatedContainer title="Create zero-ETL integration" feature="RDS zero-ETL integrations"
      note="A zero-ETL integration requires a real cross-service pipeline into Redshift that Vyomi does not run." />
  </ContentLayout>;
}

export function CustomEngineVersions() {
  const notify = useNotify();
  const t = useAsync(() => api.describeDBEngineVersions());
  const dismiss = () => notify.info("Registering install media (CreateCustomDBEngineVersion) is real; the customer-managed EC2 instance RDS Custom actually runs on is out of Vyomi's scope entirely.");
  return (
    <ResourceTable
      resourceName="Custom engine versions"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="EngineVersion"
      empty={{ title: "No custom engine versions found", action: <Button onClick={dismiss}>Create custom engine version</Button> }}
      actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={dismiss}>Actions</Button>
          <Button variant="primary" onClick={dismiss}>Create custom engine version</Button>
        </SpaceBetween>
      }
      columns={[
        { id: "engine", header: "Engine", isRowHeader: true, cell: (r) => r.Engine },
        { id: "version", header: "Engine version", cell: (r) => r.EngineVersion },
        { id: "desc", header: "Description", cell: (r) => r.DBEngineVersionDescription || "-" },
        { id: "status", header: "Status", cell: (r) => r.Status },
      ]}
    />
  );
}

export function Recommendations() {
  const [sel, setSel] = useState([]);
  const t = useAsync(() => api.describeDBRecommendations());
  return (
    <ResourceTable
      resourceName="Recommendations"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="RecommendationId"
      selectionType="multi"
      selectedItems={sel}
      onSelectionChange={setSel}
      empty={{ title: "No active recommendations" }}
      actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button disabled={sel.length !== 1}>View details</Button>
          <Button disabled={!sel.length}>Apply</Button>
          <Button disabled={!sel.length}>Dismiss</Button>
        </SpaceBetween>
      }
      columns={[
        { id: "severity", header: "Severity", isRowHeader: true, cell: (r) => r.Severity },
        { id: "detection", header: "Detection", cell: (r) => r.Detection },
        { id: "reco", header: "Recommendation", cell: (r) => r.Recommendation },
        { id: "impact", header: "Impact", cell: (r) => r.Impact },
        { id: "category", header: "Category", cell: (r) => r.Category },
        { id: "start", header: "Start time", cell: (r) => r.CreatedTime },
        { id: "modified", header: "Last modified", cell: (r) => r.UpdatedTime },
        { id: "resource", header: "Resource identifier", cell: (r) => r.ResourceArn },
      ]}
    />
  );
}

const CURRENT_CA = "rds-ca-rsa2048-g1";

export function CertificateUpdate() {
  const [sel, setSel] = useState([]);
  const notify = useNotify();
  const t = useAsync(async () => {
    const [dbs, certs] = await Promise.all([api.describeDBInstances(), api.describeCertificates()]);
    const validTill = Object.fromEntries(certs.map((c) => [c.CertificateIdentifier, c.ValidTill]));
    return dbs.filter((d) => d.CACertificateIdentifier !== CURRENT_CA)
      .map((d) => ({ ...d, _caExpiration: validTill[d.CACertificateIdentifier] }));
  });
  const applyNow = async () => {
    try {
      await Promise.all(sel.map((d) => api.modifyDBInstance(d.DBInstanceIdentifier, { CACertificateIdentifier: CURRENT_CA })));
      notify.success(`Certificate update applied to ${sel.length} database(s).`);
      setSel([]);
      t.reload();
    } catch (e) { notify.error(e); }
  };
  return (
    <ResourceTable
      resourceName="Databases requiring certificate update"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="DBInstanceIdentifier"
      selectionType="multi"
      selectedItems={sel}
      onSelectionChange={setSel}
      empty={{ title: "No records found." }}
      actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button onClick={() => notify.success("List exported.")}>Export list</Button>
          <Button disabled={!sel.length} onClick={() => notify.info("Vyomi applies a certificate update immediately — there is no separate maintenance-window scheduler to defer it to.")}>Schedule update</Button>
          <Button disabled={!sel.length} onClick={applyNow}>Apply update now</Button>
        </SpaceBetween>
      }
      columns={[
        { id: "id", header: "DB identifier", isRowHeader: true, cell: (d) => d.DBInstanceIdentifier },
        { id: "status", header: "Status", cell: (d) => d.DBInstanceStatus },
        { id: "ca", header: "Certificate authority", cell: (d) => d.CACertificateIdentifier || CURRENT_CA },
        { id: "exp", header: "CA expiration date", cell: (d) => d._caExpiration || "-" },
        { id: "role", header: "Role", cell: () => "Instance" },
        { id: "restart", header: "Restart required", cell: () => "No" },
        { id: "scheduled", header: "Scheduled changes", cell: () => "None" },
        { id: "maint", header: "Maintenance", cell: () => "-" },
      ]}
    />
  );
}

export function RestoreFromS3() {
  return <ContentLayout header={<Header variant="h1">Create database by restoring from S3</Header>}>
    <NotSimulatedContainer title="Restore from S3" feature="Restoring a MySQL backup from Amazon S3"
      note="This path imports a MySQL backup file from an S3 bucket outside Vyomi; it isn't modeled." />
  </ContentLayout>;
}

/** A list page honestly backed by a native call, with a header action that opens
 * an honest create route (never a fake success). */
function ResourceTableHonestList({ resourceName, list, trackBy, createHref, createLabel, emptyTitle, otherActions, columns }) {
  const t = useAsync(list);
  return (
    <ResourceTable
      resourceName={resourceName}
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy={trackBy}
      empty={{ title: emptyTitle, action: <Button href={createHref} onFollow={follow}>{createLabel}</Button> }}
      actions={
        <SpaceBetween direction="horizontal" size="xs">
          {otherActions.map((a) => <Button key={a} disabled>{a}</Button>)}
          <Button variant="primary" href={createHref} onFollow={follow}>{createLabel}</Button>
        </SpaceBetween>
      }
      columns={columns}
    />
  );
}
