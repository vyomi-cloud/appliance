/* Registry: Activated extensions — a REAL, honest catalog read over the native wire
 * (ListTypes/DescribeType in core/cloudformation_core.py): the exact resource types the
 * engine provisions. Modules and Hooks aren't modeled (aws.cloudformation.hooks;
 * CloudFormation modules aren't built either). Reviewed as a read-only REFERENCE page
 * (consoles/honest-allowlist.json _reference) — no "create a resource" liveness check,
 * since activated types come from the engine itself, not a resource a user creates. */
import { useState } from "react";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Link from "@cloudscape-design/components/link";
import Box from "@cloudscape-design/components/box";
import Spinner from "@cloudscape-design/components/spinner";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { NotSimulatedContainer, KeyValue, ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { href, follow, navigate } from "../../../common/router.js";
import * as api from "./api.js";

function ResourceTypesTable() {
  const { data = [], loading, error, reload } = useAsync(() => api.listTypes(), []);
  const [sel, setSel] = useState([]);
  return (
    <ResourceTable
      resourceName="Resource types"
      items={data}
      trackBy="TypeName"
      loading={loading}
      error={error}
      onRefresh={reload}
      selectionType="single"
      selectedItems={sel}
      onSelectionChange={setSel}
      filterPlaceholder="Filter extension type"
      columns={[
        { id: "t", header: "Resource types", isRowHeader: true, cell: (t) => <Link href={href("cloudformation", "registry", "public-extensions", "resource-type", t.TypeName)} onFollow={follow}>{t.TypeName}</Link> },
        { id: "v", header: "Default version", cell: (t) => t.DefaultVersionId },
        { id: "d", header: "Description", cell: (t) => t.Description },
      ]}
      actions={
        <ButtonDropdown disabled={sel.length !== 1}
          onItemClick={() => navigate("cloudformation", "registry", "public-extensions", "resource-type", sel[0].TypeName)}
          items={[{ id: "view", text: "View details" }]}>
          Actions
        </ButtonDropdown>
      }
    />
  );
}

export default function ActivatedExtensions() {
  const [tab, setTab] = useState("resource-types");
  return (
    <ContentLayout header={<Header variant="h1">Registry: Activated extensions</Header>}>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "resource-types", label: "Resource types", content: <ResourceTypesTable /> },
        { id: "modules", label: "Modules", content: <NotSimulatedContainer title="Modules" feature="CloudFormation modules" /> },
        { id: "hooks", label: "Hooks", content: <NotSimulatedContainer title="Hooks" feature="CloudFormation Hooks" /> },
      ]} />
    </ContentLayout>
  );
}

/** Registry: resource-type detail — real data (ARN, description, JSON schema) from
 * DescribeType. Configuration (logging/execution role) applies to private/third-party
 * extensions, which Vyomi doesn't model. */
export function ExtensionDetail({ params }) {
  const name = params.name || "AWS::S3::Bucket";
  const { data, loading, error } = useAsync(() => api.describeType(name), [name]);
  if (loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (error || !data?.TypeName) return <ErrorAlert error={error || { message: `${name} is not an activated extension.` }} />;
  let schema = data.Schema || "";
  try { schema = JSON.stringify(JSON.parse(schema), null, 2); } catch { /* leave raw */ }
  return (
    <ContentLayout header={<Header variant="h1">{name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Overview" columns={2} items={[
          ["ARN", data.Arn], ["Publisher", "Amazon Web Services"], ["Description", data.Description],
          ["Release date", fmtDate(data.TimeCreated)], ["Visibility", data.Visibility],
        ]} />
        <Tabs tabs={[
          { id: "schema", label: "Schema", content: <Container header={<Header variant="h2">Schema</Header>}><Box variant="pre">{schema}</Box></Container> },
          { id: "configuration", label: "Configuration", content: <NotSimulatedContainer title="Configuration" feature="Extension configuration" note="Logging role / execution role configuration applies to private and third-party extensions, which Vyomi doesn't model." /> },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}
