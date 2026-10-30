import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate, NotSimulated } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";

export default function Buckets() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(async () => {
    const bs = await api.listBuckets();
    const regions = await Promise.all(bs.map((b) => api.bucketRegion(b.name)));
    return bs.map((b, i) => ({ ...b, region: regions[i] }));
  });

  return (
    <>
      <Tabs
        tabs={[
          {
            id: "general", label: "General purpose buckets",
            content: (
              <ResourceTable
                variant="container"
                resourceName="General purpose buckets"
                info={<Link variant="info">Info</Link>}
                description="Buckets are containers for data stored in S3."
                items={data}
                loading={loading}
                error={error}
                onRefresh={reload}
                selectionType="single"
                selectedItems={sel}
                onSelectionChange={setSel}
                filterPlaceholder="Find buckets by name"
                columns={[
                  { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (b) => <Link href={href("s3", "buckets", b.name)} onFollow={follow}>{b.name}</Link> },
                  { id: "region", header: "AWS Region", sortingField: "region", cell: (b) => b.region || "-" },
                  { id: "created", header: "Creation date", sortingField: "created", cell: (b) => fmtDate(b.created) },
                ]}
                actions={
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button disabled={sel.length !== 1} onClick={async () => { try { await navigator.clipboard.writeText(`arn:aws:s3:::${sel[0].name}`); notify.success("ARN copied"); } catch { notify.info(`arn:aws:s3:::${sel[0].name}`, "ARN"); } }}>Copy ARN</Button>
                    <Button disabled={sel.length !== 1} onClick={() => setDel(true)}>Delete</Button>
                    <Button variant="primary" href={href("s3", "create")} onFollow={follow}>Create bucket</Button>
                  </SpaceBetween>
                }
                empty={{ title: "No buckets", subtitle: "You don't have any buckets.", action: <Button href={href("s3", "create")} onFollow={follow}>Create bucket</Button> }}
              />
            ),
          },
          { id: "directory", label: "Directory buckets", content: <NotSimulated feature="Directory buckets (S3 Express One Zone)" /> },
        ]}
      />
      <DeleteModal
        visible={del}
        resourceType="bucket"
        names={sel.map((b) => b.name)}
        warning="Buckets must be empty before they can be deleted."
        onDismiss={() => setDel(false)}
        onConfirm={async () => {
          await api.deleteBucket(sel[0].name);
          notify.success(`Successfully deleted bucket "${sel[0].name}".`);
          setSel([]);
          reload();
        }}
      />
    </>
  );
}
