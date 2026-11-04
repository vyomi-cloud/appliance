/* Document detail — Content, Document versions, Tags. Real GetDocument/ListDocumentVersions. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Table from "@cloudscape-design/components/table";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Textarea from "@cloudscape-design/components/textarea";
import Spinner from "@cloudscape-design/components/spinner";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { ErrorAlert, fmtDate, KeyValue } from "../../kit/common.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

function ContentTab({ name, doc, reload }) {
  const notify = useNotify();
  const c = useAsync(() => api.getDocument(name), [name]);
  const [edit, setEdit] = useState(null);
  const [busy, setBusy] = useState(false);
  const readOnly = doc.Owner === "Amazon";
  return (
    <Container header={<Header variant="h2" actions={!readOnly && <Button onClick={() => setEdit(c.data?.Content || "")}>Update document</Button>}>Content</Header>}>
      {c.loading ? <Spinner /> : <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{c.data?.Content}</pre></Box>}
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} size="large" header="Update document"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true);
            try { await api.updateDocument(name, edit); notify.success("Document updated to a new version."); setEdit(null); c.reload(); reload(); }
            catch (e) { notify.error(e); } finally { setBusy(false); }
          }}>Update document</Button>
        </SpaceBetween></Box>}>
        <FormField label="Content"><Textarea rows={16} value={edit || ""} onChange={({ detail }) => setEdit(detail.value)} spellcheck={false} /></FormField>
      </Modal>
    </Container>
  );
}

function VersionsTab({ name, doc, reload }) {
  const notify = useNotify();
  const v = useAsync(() => api.listDocumentVersions(name), [name]);
  return (
    <Table variant="container" items={v.data || []} loading={v.loading} trackBy="DocumentVersion"
      header={<Header variant="h2" counter={`(${(v.data || []).length})`}>Document versions</Header>}
      columnDefinitions={[
        { id: "v", header: "Version", cell: (x) => x.DocumentVersion },
        { id: "n", header: "Version name", cell: (x) => x.VersionName || "-" },
        { id: "c", header: "Created date", cell: (x) => fmtDate(x.CreatedDate) },
        { id: "d", header: "Default version", cell: (x) => x.IsDefaultVersion
          ? <StatusIndicator type="success">Default</StatusIndicator>
          : <Button variant="inline-link" onClick={async () => { await api.updateDocumentDefaultVersion(name, x.DocumentVersion); notify.success(`Version ${x.DocumentVersion} is now the default.`); v.reload(); reload(); }}>Set as default</Button> },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No versions</b></Box>} />
  );
}

function TagsTab({ name }) {
  const notify = useNotify();
  const t = useAsync(() => api.listTagsForResource("Document", name), [name]);
  const [edit, setEdit] = useState(null);
  return (
    <Container>
      <Table variant="embedded" items={t.data || []} loading={t.loading}
        header={<Header variant="h2" counter={`(${(t.data || []).length})`} actions={<Button onClick={() => setEdit((t.data || []).map((x) => ({ key: x.Key, value: x.Value })))}>Edit</Button>}>Tags</Header>}
        columnDefinitions={[{ id: "k", header: "Key", cell: (x) => x.Key }, { id: "v", header: "Value", cell: (x) => x.Value || "-" }]}
        empty={<Box textAlign="center" color="inherit"><b>No tags</b></Box>} />
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} size="large" header="Edit tags"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" onClick={async () => {
            try {
              const current = new Set((t.data || []).map((x) => x.Key));
              const next = new Set(edit.filter((x) => !x.markedForRemoval && x.key).map((x) => x.key));
              const toRemove = [...current].filter((k) => !next.has(k));
              if (toRemove.length) await api.removeTagsFromResource("Document", name, toRemove);
              const toAdd = edit.filter((x) => !x.markedForRemoval && x.key).map((x) => ({ Key: x.key, Value: x.value || "" }));
              if (toAdd.length) await api.addTagsToResource("Document", name, toAdd);
              notify.success("Tags updated."); setEdit(null); t.reload();
            } catch (e) { notify.error(e); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <TagEditor tags={edit} onChange={({ detail }) => setEdit(detail.tags)} />}
      </Modal>
    </Container>
  );
}

export default function DocumentDetail({ query }) {
  const name = query.name;
  const d = useAsync(() => api.describeDocument(name), [name]);
  const [delModal, setDelModal] = useState(false);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const doc = d.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <ButtonDropdown items={[{ id: "delete", text: "Delete document", disabled: doc.Owner === "Amazon" }]}
        onItemClick={() => setDelModal(true)}>Actions</ButtonDropdown>
    }>{name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Document details" columns={4} items={[
          ["Owner", doc.Owner], ["Document type", doc.DocumentType], ["Document format", doc.DocumentFormat],
          ["Default version", doc.DefaultVersion], ["Latest version", doc.LatestVersion], ["Schema version", doc.SchemaVersion],
          ["Created date", fmtDate(doc.CreatedDate)], ["Description", doc.Description || "-"],
        ]} />
        <Tabs tabs={[
          { id: "content", label: "Content", content: <ContentTab name={name} doc={doc} reload={d.reload} /> },
          { id: "versions", label: "Document versions", content: <VersionsTab name={name} doc={doc} reload={d.reload} /> },
          { id: "tags", label: "Tags", content: <TagsTab name={name} /> },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="document" names={[name]}
        onConfirm={async () => { await api.deleteDocument(name); navigate("ssm", "documents"); }} />
    </ContentLayout>
  );
}
