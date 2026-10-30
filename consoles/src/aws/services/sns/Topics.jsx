import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";

export default function Topics() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const { data = [], loading, error, reload } = useAsync(async () => {
    const arns = await api.listTopics();
    return Promise.all(arns.map(async (arn) => {
      const attrs = await api.getTopicAttributes(arn);
      return { arn, name: api.topicName(arn), type: attrs.FifoTopic === "true" ? "FIFO" : "Standard" };
    }));
  }, []);

  return (
    <ContentLayout header={<Header variant="h1" counter={`(${data.length})`}>Topics</Header>}>
      <ResourceTable
        resourceName="Topics"
        items={data}
        trackBy="arn"
        loading={loading}
        error={error}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, sortingField: "name", cell: (t) => <Link href={href("sns", "topics", t.name)} onFollow={follow}>{t.name}</Link> },
          { id: "type", header: "Type", cell: (t) => t.type },
          { id: "arn", header: "ARN", cell: (t) => t.arn },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => navigate("sns", "topics", sel[0].name, "edit")}>Edit</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
            <Button disabled={sel.length !== 1} onClick={() => navigate("sns", "topics", sel[0].name, "publish")}>Publish message</Button>
            <Button variant="primary" href={href("sns", "create-topic")} onFollow={follow}>Create topic</Button>
          </SpaceBetween>
        }
        empty={{ title: "No topics", subtitle: "You don't have any topics yet.", action: <Button href={href("sns", "create-topic")} onFollow={follow}>Create topic</Button> }}
      />
      <DeleteModal
        visible={del}
        resourceType="topic"
        names={sel.map((t) => t.name)}
        confirmText="delete me"
        onDismiss={() => setDel(false)}
        onConfirm={async () => {
          for (const t of sel) await api.deleteTopic(t.arn);
          notify.success(`${sel.length === 1 ? `"${sel[0].name}"` : `${sel.length} topics`} deleted.`);
          setSel([]); reload();
        }}
      />
    </ContentLayout>
  );
}
