import Header from "@cloudscape-design/components/header";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useState } from "react";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

const activityArn = (name) => `arn:aws:states:us-east-1:000000000000:activity:${name}`;

export default function ActivityDetail({ params }) {
  const name = params.name;
  const notify = useNotify();
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeActivity(activityArn(name)), [name]);
  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (t.error) return <ErrorAlert error={t.error} />;
  const d = t.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={t.reload} iconName="refresh" ariaLabel="Refresh" />
        <Button onClick={() => setDel(true)}>Delete</Button>
      </SpaceBetween>
    }>{name}</Header>}>
      <KeyValue title="Details" columns={3} items={[
        ["Name", d.name],
        ["ARN", d.activityArn],
        ["Created", fmtDate(d.creationDate)],
      ]} />
      <DeleteModal visible={del} resourceType="activity" names={[name]} confirmText="delete"
        onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.deleteActivity(d.activityArn); notify.success(`Activity "${name}" deleted.`); navigate("states", "activities"); }} />
    </ContentLayout>
  );
}
