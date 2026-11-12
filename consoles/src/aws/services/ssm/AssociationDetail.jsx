/* Association detail — real DescribeAssociation. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";

export default function AssociationDetail({ params }) {
  const id = params.id;
  const d = useAsync(() => api.describeAssociation(id), [id]);
  const [delModal, setDelModal] = useState(false);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const a = d.data;
  const targets = (a.Targets || []).map((t) => `${t.Key}: ${(t.Values || []).join(", ")}`).join("; ");
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={() => setDelModal(true)}>Delete association</Button>}>{id}</Header>}>
      <KeyValue title={<SpaceBetween direction="horizontal" size="xs" alignItems="center"><span>Association details</span><CapabilityBadge id="ssm.statemanager.association" /></SpaceBetween>} columns={3} items={[
        ["Document name", a.Name], ["Association name", a.AssociationName || "-"], ["Status", a.Overview?.Status || "-"],
        ["Targets", targets || "-"], ["Schedule", a.ScheduleExpression || "On target change"], ["Document version", a.DocumentVersion],
      ]} />
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="association" names={[id]}
        onConfirm={async () => { await api.deleteAssociation(id); navigate("ssm", "associations"); }} />
    </ContentLayout>
  );
}
