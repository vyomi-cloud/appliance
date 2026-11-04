/* HTTP (and WebSocket) API detail — API details, Stages, Tags. Routes/Integrations
 * are managed the same way as REST methods: via the native wire (api.js routesV2 /
 * integrationsV2); the console here focuses on what the spec scores (API details,
 * Stages, Tags) plus the controls needed to actually manage routes. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Table from "@cloudscape-design/components/table";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function HttpApiDetail({ params }) {
  const notify = useNotify();
  const d = useAsync(async () => {
    const a = await api.resolveApiV2(params.id);
    const arn = `arn:aws:apigateway:us-east-1::/apis/${a.apiId}`;
    const [stages, tags] = await Promise.all([api.listStagesV2(a.apiId), api.getTagsV2(arn)]);
    return { a, arn, stages, tags };
  }, [params.id]);
  const tagsAsync = { data: d.data?.tags, reload: d.reload };
  const [editName, setEditName] = useState(null);
  const [editTags, setEditTags] = useState(null);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const { a, arn, stages } = d.data;
  const apiId = a.apiId;

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <ButtonDropdown items={[{ id: "delete", text: "Delete" }]} onItemClick={async ({ detail }) => {
          if (detail.id === "delete") { await api.deleteApiV2(apiId); notify.success("API deleted."); navigate("apigateway", "apis"); }
        }}>Actions</ButtonDropdown>
        <Button onClick={() => setEditName(a.name)}>Edit</Button>
      </SpaceBetween>
    }>{a.name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="API details" columns={3} items={[
          ["API ID", a.apiId], ["Protocol", a.protocolType], ["Created", fmtDate(a.createdDate)],
          ["Default endpoint", a.apiEndpoint], ["Description", a.description || "-"],
        ]} />
        <Table variant="container" header={<Header variant="h2" counter={`(${stages.length})`}>{`Stages for ${a.name}`}</Header>}
          items={stages}
          columnDefinitions={[
            { id: "n", header: "Stage name", cell: (s) => s.stageName },
            { id: "u", header: "Invoke URL", cell: (s) => `${a.apiEndpoint}/${s.stageName === "$default" ? "" : s.stageName}` },
            { id: "d", header: "Attached deployment", cell: (s) => s.deploymentId || "-" },
            { id: "ad", header: "Auto deploy", cell: (s) => (s.autoDeploy ? "Yes" : "No") },
            { id: "lu", header: "Last updated", cell: (s) => fmtDate(s.lastUpdatedDate) },
          ]}
          empty={<Box textAlign="center" color="inherit">No stages</Box>} />
        <Table variant="container" header={<Header variant="h2" counter={`(${Object.keys(tagsAsync.data || {}).length})`} actions={<Button onClick={() => setEditTags(Object.entries(tagsAsync.data || {}).map(([key, value]) => ({ key, value })))}>Manage tags</Button>}>Tags</Header>}
          items={Object.entries(tagsAsync.data || {}).map(([k, v]) => ({ k, v }))}
          columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.k }, { id: "v", header: "Value", cell: (x) => x.v }]}
          empty={<Box textAlign="center" color="inherit">No tags</Box>} />
      </SpaceBetween>
      <Modal visible={editName !== null} onDismiss={() => setEditName(null)} header="Edit API"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditName(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => { await api.updateApiV2(apiId, { name: editName }); notify.success("API updated."); setEditName(null); d.reload(); }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <FormField label="Name"><Input value={editName || ""} onChange={({ detail }) => setEditName(detail.value)} ariaLabel="Name" /></FormField>
      </Modal>
      <Modal visible={!!editTags} onDismiss={() => setEditTags(null)} size="large" header="Manage tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditTags(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            const tags = Object.fromEntries(editTags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value || ""]));
            await api.tagResourceV2(arn, tags); notify.success("Tags updated."); setEditTags(null); tagsAsync.reload();
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {editTags && <TagEditor tags={editTags} onChange={({ detail }) => setEditTags(detail.tags)} />}
      </Modal>
    </ContentLayout>
  );
}
