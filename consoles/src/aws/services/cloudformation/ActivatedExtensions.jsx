/* Registry: Activated extensions — a REAL, honest catalog: the exact resource types
 * core/cloudformation_core.py RESOURCE_TYPES provisions. Modules and Hooks aren't
 * modeled (aws.cloudformation.hooks; CloudFormation modules aren't built either). */
import { useState } from "react";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { SUPPORTED_RESOURCE_TYPES } from "./api.js";

const DESCRIPTIONS = {
  "AWS::S3::Bucket": "An Amazon S3 bucket, provisioned through Vyomi's S3 engine.",
  "AWS::DynamoDB::Table": "A DynamoDB table, provisioned through Vyomi's DynamoDB engine.",
  "AWS::SNS::Topic": "An SNS topic, provisioned through Vyomi's SNS engine.",
  "AWS::SQS::Queue": "An SQS queue, provisioned through Vyomi's SQS engine.",
  "AWS::IAM::Role": "An IAM role, provisioned through Vyomi's IAM engine.",
  "AWS::CloudFormation::WaitCondition": "A CloudFormation-internal signaling resource (no underlying infrastructure in real AWS either).",
  "AWS::CloudFormation::WaitConditionHandle": "A CloudFormation-internal signaling handle (no underlying infrastructure in real AWS either).",
};

function ResourceTypesTable() {
  return (
    <Table
      variant="container"
      items={SUPPORTED_RESOURCE_TYPES}
      trackBy={(t) => t}
      header={<Header variant="h2" counter={`(${SUPPORTED_RESOURCE_TYPES.length})`}>Resource types</Header>}
      columnDefinitions={[
        { id: "t", header: "Resource types", isRowHeader: true, cell: (t) => t },
        { id: "v", header: "Default version", cell: () => "1" },
        { id: "d", header: "Description", cell: (t) => DESCRIPTIONS[t] },
      ]}
    />
  );
}

export default function ActivatedExtensions() {
  const [tab, setTab] = useState("resource-types");
  return (
    <ContentLayout header={<Header variant="h1" actions={<ButtonDropdown disabled items={[{ id: "deactivate", text: "Deactivate" }]}>Actions</ButtonDropdown>}>Registry: Activated extensions</Header>}>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "resource-types", label: "Resource types", content: <ResourceTypesTable /> },
        { id: "modules", label: "Modules", content: <NotSimulatedContainer title="Modules" feature="CloudFormation modules" /> },
        { id: "hooks", label: "Hooks", content: <NotSimulatedContainer title="Hooks" feature="CloudFormation Hooks" /> },
      ]} />
    </ContentLayout>
  );
}
