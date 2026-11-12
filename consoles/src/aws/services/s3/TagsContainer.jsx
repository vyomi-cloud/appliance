/* Tags container with Manage tags (bucket and object). `state` = useAsync result of { tags } | { error }. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useNotify } from "../../../common/notify.jsx";
import { TAG_I18N } from "../../kit/tagI18n.js";
import { ErrorAlert } from "../../kit/common.jsx";

export default function TagsContainer({ state, save, limit = 10 }) {
  const notify = useNotify();
  const [edit, setEdit] = useState(null);
  const [busy, setBusy] = useState(false);
  const tags = state.data?.tags || [];
  if (state.loading) return <Container header={<Header variant="h2">Tags</Header>}><StatusIndicator type="loading">Loading</StatusIndicator></Container>;
  if (state.data?.error || state.error) return <Container header={<Header variant="h2">Tags</Header>}><ErrorAlert error={state.data?.error || state.error} /></Container>;
  return (
    <Container header={<Header variant="h2" counter={`(${tags.length})`} actions={<Button onClick={() => setEdit(tags.map((t) => ({ ...t })))}>Edit</Button>}>Tags</Header>}>
      <Table variant="embedded" items={tags}
        columnDefinitions={[{ id: "k", header: "Key", cell: (t) => t.key }, { id: "v", header: "Value", cell: (t) => t.value || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b><Box variant="p" color="inherit">There are no tags associated with this resource.</Box></Box>} />
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} size="large" header="Edit tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true);
            try {
              await save(edit.filter((x) => !x.markedForRemoval && x.key).map(({ key, value }) => ({ key, value: value || "" })));
              notify.success("Successfully edited tags."); setEdit(null); state.reload();
            } catch (e) { notify.error(e); } finally { setBusy(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <TagEditor tags={edit} tagLimit={limit} i18nStrings={TAG_I18N} onChange={({ detail }) => setEdit(detail.tags)} />}
      </Modal>
    </Container>
  );
}
