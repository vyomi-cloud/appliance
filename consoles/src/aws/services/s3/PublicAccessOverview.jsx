/* Public access overview: every bucket with the Block Public Access settings in force (bucket OR account), whether it exposes a public
 * policy / public ACL, and which setting blocks it. Read from GET /api/iam/aws/governance/s3-public-access, evaluated by the same
 * rules the engine applies to anonymous requests (RestrictPublicBuckets, IgnorePublicAcls). */
import Box from "@cloudscape-design/components/box";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { gov } from "../../../common/governanceApi.js";
import { ErrorAlert } from "../../kit/common.jsx";

const KEYS = ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"];

export default function PublicAccessOverview() {
  const d = useAsync(() => gov("aws", "s3-public-access"), []);
  if (d.error) return <ErrorAlert error={d.error} />;
  const acct = d.data?.account || {};
  return (
    <SpaceBetween size="l">
      <Header variant="h1" description="Which buckets can be reached without credentials, and which Block Public Access setting stops it.">Public access overview</Header>
      <Table loading={d.loading} items={d.data?.buckets || []} trackBy="bucket" variant="container"
        header={<Header variant="h2" counter={`(${(d.data?.buckets || []).length})`} description={<>Account settings: {KEYS.map((k) => `${k} ${acct[k] ? "on" : "off"}`).join(", ")}. <Link href="#/s3/settings">Edit account settings</Link></>}>Buckets</Header>}
        columnDefinitions={[
          { id: "b", header: "Bucket", isRowHeader: true, cell: (r) => <Link href={`#/s3/buckets/${r.bucket}`}>{r.bucket}</Link> },
          { id: "pp", header: "Public bucket policy", cell: (r) => (r.publicPolicy ? "Yes" : "No") },
          { id: "pa", header: "Public ACL", cell: (r) => (r.publicAcl ? "Yes" : "No") },
          { id: "bl", header: "Blocked by", cell: (r) => r.blockedBy.join(", ") || "-" },
          { id: "st", header: "Access", cell: (r) => <StatusIndicator type={r.publiclyAccessible ? "error" : "success"}>{r.publiclyAccessible ? "Public" : "Not public"}</StatusIndicator> },
          { id: "ef", header: "Effective Block Public Access", cell: (r) => KEYS.filter((k) => r.effective[k]).map((k) => k.replace("Public", "")).join(", ") || "none" },
        ]}
        empty={<Box textAlign="center"><b>No buckets</b></Box>} />
    </SpaceBetween>
  );
}
