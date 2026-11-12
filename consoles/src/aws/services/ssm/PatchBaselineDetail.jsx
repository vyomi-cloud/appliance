/* Patch baseline detail — real GetPatchBaseline. */
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

export default function PatchBaselineDetail({ params }) {
  const id = params.id;
  const d = useAsync(() => api.getPatchBaseline(id), [id]);
  const [delModal, setDelModal] = useState(false);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const b = d.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={<Button onClick={() => setDelModal(true)}>Delete</Button>}>{b.Name}</Header>}>
      <KeyValue title={<SpaceBetween direction="horizontal" size="xs" alignItems="center"><span>Baseline details</span><CapabilityBadge id="ssm.patchbaseline.crud" /></SpaceBetween>} columns={3} items={[
        ["Baseline ID", b.BaselineId], ["Operating system", b.OperatingSystem], ["Description", b.Description || "-"],
        ["Approved patches", (b.ApprovedPatches || []).join(", ") || "-"], ["Rejected patches", (b.RejectedPatches || []).join(", ") || "-"],
      ]} />
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="patch baseline" names={[b.Name]}
        onConfirm={async () => { await api.deletePatchBaseline(id); navigate("ssm", "patch-baselines"); }} />
    </ContentLayout>
  );
}
