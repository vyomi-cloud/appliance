import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Link from "@cloudscape-design/components/link";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";
import Spinner from "@cloudscape-design/components/spinner";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import * as api from "./api.js";

export function InstanceTypes() {
  const t = useAsync(() => api.describeInstanceTypes(), []);
  return (
    <ContentLayout header={<Header variant="h1">Select an instance type</Header>}>
      <ResourceTable
        resourceName="Instance types"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="InstanceType"
        selectionType="multi"
        filterPlaceholder="Filter instance types by attribute"
        columns={[
          { id: "type", header: "Instance type", isRowHeader: true, cell: (x) => <Link href={href("ec2", "instance-types", x.InstanceType)} onFollow={follow}>{x.InstanceType}</Link> },
          { id: "free", header: "Free tier eligible", cell: (x) => (x.FreeTierEligible ? "Yes" : "No") },
          { id: "vcpu", header: "vCPUs", cell: (x) => x.VCpuCount },
          { id: "arch", header: "Architecture", cell: (x) => x.Architectures.join(", ") },
          { id: "mem", header: "Memory (GiB)", cell: (x) => (x.MemoryMiB / 1024).toFixed(0) },
          { id: "storage", header: "Storage (GB)", cell: () => "EBS only" },
          { id: "storagetype", header: "Storage type", cell: () => "EBS only" },
          { id: "net", header: "Network performance", cell: (x) => x.NetworkPerformance },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={() => navigate("ec2", "instance-type-finder")}>Instance type finder</Button>
            <ButtonDropdown items={[{ id: "compare", text: "Compare instance types" }]}>Actions</ButtonDropdown>
          </SpaceBetween>
        }
      />
    </ContentLayout>
  );
}

export function InstanceTypeDetail({ params }) {
  const t = useAsync(() => api.describeInstanceTypes().then((xs) => xs.find((x) => x.InstanceType === params.type)), [params.type]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Instance type not found" }} />;
  const x = t.data;
  return (
    <ContentLayout header={<Header variant="h1">{x.InstanceType}</Header>}>
      <Tabs tabs={[
        { id: "details", label: "Details", content: (
          <KeyValue title="Instance type details" columns={2} items={[
            ["Instance type", x.InstanceType], ["Instance family", x.InstanceType.split(".")[0]], ["Hypervisor", x.Hypervisor],
            ["Free tier eligible", x.FreeTierEligible ? "Yes" : "No"], ["Current generation", "Yes"], ["Bare metal", x.BareMetal ? "Yes" : "No"],
            ["On-Demand Linux pricing", "Not simulated"], ["Supported root device types", "ebs"],
          ]} />
        ) },
        { id: "compute", label: "Compute", content: <KeyValue title="Compute" columns={2} items={[["vCPUs", x.VCpuCount], ["Memory (GiB)", (x.MemoryMiB / 1024).toFixed(0)]]} /> },
        { id: "networking", label: "Networking", content: <KeyValue title="Networking" columns={1} items={[["Network performance", x.NetworkPerformance]]} /> },
        { id: "storage", label: "Storage", content: <KeyValue title="Storage" columns={1} items={[["Storage type", "EBS only"]]} /> },
        { id: "accelerators", label: "Accelerators", content: <KeyValue title="Accelerators" columns={1} items={[["GPUs", "None"]]} /> },
        { id: "pricing", label: "Pricing", content: <KeyValue title="Pricing" columns={1} items={[["On-Demand hourly rate", "Not simulated"]]} /> },
      ]} />
    </ContentLayout>
  );
}
