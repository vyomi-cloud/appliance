/* Parameter detail — General configuration + Value (Show/Hide, Edit), History, Tags.
 * Every tab is a real GetParameter/GetParameterHistory/ListTagsForResource call. */
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
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

function ValueSection({ name, param, reload }) {
  const notify = useNotify();
  const [shown, setShown] = useState(false);
  const [edit, setEdit] = useState(null);
  const [busy, setBusy] = useState(false);
  const display = param.Type === "SecureString" && !shown ? "•".repeat(12) : param.Value;
  return (
    <CapabilityContainer id="ssm.parameter.securestring" title="Value" actions={
      <SpaceBetween direction="horizontal" size="xs">
        {param.Type === "SecureString" && <Button onClick={() => setShown((s) => !s)}>{shown ? "Hide" : "Show"}</Button>}
        <Button onClick={() => setEdit(param.Value)}>Edit</Button>
      </SpaceBetween>
    }>
      <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{display}</pre></Box>
      <Modal visible={edit !== null} onDismiss={() => setEdit(null)} size="large" header="Edit parameter value"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEdit(null)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true);
            try {
              await api.putParameter({ Name: name, Value: edit, Type: param.Type, Tier: param.Tier, Overwrite: true,
                ...(param.Type === "SecureString" ? { KeyId: param.KeyId } : {}) });
              notify.success("Parameter value updated."); setEdit(null); reload();
            } catch (e) { notify.error(e); } finally { setBusy(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <FormField label="Value"><Textarea rows={8} value={edit || ""} onChange={({ detail }) => setEdit(detail.value)} spellcheck={false} /></FormField>
      </Modal>
    </CapabilityContainer>
  );
}

function HistoryTab({ name }) {
  const h = useAsync(() => api.getParameterHistory(name), [name]);
  return (
    <Table variant="container" items={h.data || []} loading={h.loading} trackBy="Version"
      header={<Header variant="h2" counter={`(${(h.data || []).length})`}>Version history</Header>}
      columnDefinitions={[
        { id: "v", header: "Version", cell: (x) => x.Version },
        { id: "l", header: "Label(s)", cell: (x) => (x.Labels || []).join(", ") || "-" },
        { id: "m", header: "Last modified", cell: (x) => fmtDate(x.LastModifiedDate) },
        { id: "d", header: "Description", cell: (x) => x.Description || "-" },
        { id: "val", header: "Value", cell: (x) => x.Type === "SecureString" ? "•".repeat(10) : x.Value },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No versions</b></Box>} />
  );
}

function LabelModal({ name, version, visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [labels, setLabels] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header={`Label version ${version}`}
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!labels.trim()} onClick={async () => {
          setBusy(true);
          try {
            await api.labelParameterVersion(name, version, labels.split(",").map((s) => s.trim()).filter(Boolean));
            notify.success("Version labeled."); setLabels(""); onDone(); onDismiss();
          } catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Label version</Button>
      </SpaceBetween></Box>}>
      <FormField label="Labels" constraintText="Comma-separated. A label can mark only one version at a time.">
        <Textarea value={labels} onChange={({ detail }) => setLabels(detail.value)} ariaLabel="Labels" />
      </FormField>
    </Modal>
  );
}

function TagsTab({ name }) {
  const notify = useNotify();
  const t = useAsync(() => api.listTagsForResource("Parameter", name), [name]);
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
              if (toRemove.length) await api.removeTagsFromResource("Parameter", name, toRemove);
              const toAdd = edit.filter((x) => !x.markedForRemoval && x.key).map((x) => ({ Key: x.key, Value: x.value || "" }));
              if (toAdd.length) await api.addTagsToResource("Parameter", name, toAdd);
              notify.success("Tags updated."); setEdit(null); t.reload();
            } catch (e) { notify.error(e); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        {edit && <TagEditor tags={edit} onChange={({ detail }) => setEdit(detail.tags)} />}
      </Modal>
    </Container>
  );
}

export default function ParameterDetail({ query }) {
  const name = query.name;
  const d = useAsync(() => api.getParameter(name), [name]);
  const [labelModal, setLabelModal] = useState(false);
  const [delModal, setDelModal] = useState(false);
  if (d.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (d.error) return <ErrorAlert error={d.error} />;
  const p = d.data;
  return (
    <ContentLayout header={<Header variant="h1" actions={
      <ButtonDropdown items={[{ id: "label", text: "Label this version" }, { id: "delete", text: "Delete parameter" }]}
        onItemClick={({ detail }) => (detail.id === "label" ? setLabelModal(true) : setDelModal(true))}>Actions</ButtonDropdown>
    }>{name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="General configuration" columns={4} items={[
          ["ARN", p.ARN], ["Type", <StatusIndicator key="t" type={p.Type === "SecureString" ? "info" : "success"}>{p.Type}</StatusIndicator>],
          ["Tier", p.Tier], ["Data type", p.DataType],
          ["Version", p.Version], ["Last modified", fmtDate(p.LastModifiedDate)],
        ]} />
        <ValueSection name={name} param={p} reload={d.reload} />
        <Tabs tabs={[
          { id: "history", label: "History", content: <HistoryTab name={name} /> },
          { id: "tags", label: "Tags", content: <TagsTab name={name} /> },
        ]} />
      </SpaceBetween>
      <LabelModal name={name} version={p.Version} visible={labelModal} onDismiss={() => setLabelModal(false)} onDone={d.reload} />
      <DeleteModal visible={delModal} onDismiss={() => setDelModal(false)} resourceType="parameter" names={[name]}
        onConfirm={async () => { await api.deleteParameter(name); navigate("ssm", "parameters"); }} />
    </ContentLayout>
  );
}
