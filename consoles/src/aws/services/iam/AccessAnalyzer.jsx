/* IAM Access Analyzer — real analyzer CRUD (Vyomi-only wire calls, see core/iam_core.py).
 * Findings live on ResourceAnalysis.jsx / UnusedAccess.jsx; settings on AnalyzerSettings.jsx. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

function CreateAnalyzerModal({ visible, onDismiss, onDone }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [type, setType] = useState("ACCOUNT");
  const [age, setAge] = useState("90");
  const [busy, setBusy] = useState(false);
  const close = () => { setName(""); setType("ACCOUNT"); setAge("90"); onDismiss(); };
  return (
    <Modal visible={visible} onDismiss={close} header="Create analyzer"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={close}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={async () => {
          setBusy(true);
          try {
            await api.createAnalyzer({ AnalyzerName: name, Type: type, ...(type === "ACCOUNT_UNUSED_ACCESS" ? { UnusedAccessAge: age } : {}) });
            notify.success(`Analyzer "${name}" created.`); onDone(); close();
          } catch (e) { notify.error(e); } finally { setBusy(false); }
        }}>Create analyzer</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="m">
        <FormField label="Analyzer name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Analyzer name" /></FormField>
        <FormField label="Analyzer type">
          <RadioGroup value={type} onChange={({ detail }) => setType(detail.value)}
            items={[
              { value: "ACCOUNT", label: "External access analyzer — account" },
              { value: "ACCOUNT_UNUSED_ACCESS", label: "Unused access analyzer — account" },
            ]} />
        </FormField>
        {type === "ACCOUNT_UNUSED_ACCESS" &&
          <FormField label="Unused access age (days)"><Input type="number" value={age} onChange={({ detail }) => setAge(detail.value)} ariaLabel="Unused access age" /></FormField>}
      </SpaceBetween>
    </Modal>
  );
}

export default function AccessAnalyzer() {
  const notify = useNotify();
  const a = useAsync(() => api.listAnalyzers(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [del, setDel] = useState(false);
  return (
    <SpaceBetween size="l">
      <CapabilityContainer id="iam.access-analyzer" title="Access Analyzer" counter={`(${(a.data || []).length})`}
        actions={<SpaceBetween direction="horizontal" size="xs">
          <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
          <Button variant="primary" onClick={() => setCreate(true)}>Create analyzer</Button>
        </SpaceBetween>}>
        <Table variant="embedded" items={a.data || []} loading={a.loading} trackBy="Name"
          selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          columnDefinitions={[
            { id: "name", header: "Name", cell: (x) => x.Name },
            { id: "type", header: "Type", cell: (x) => x.Type },
            { id: "status", header: "Status", cell: (x) => x.Status },
            { id: "created", header: "Created at", cell: (x) => fmtDate(x.CreatedAt) },
          ]}
          empty={<Box textAlign="center" color="inherit">
            <b>No analyzers</b>
            <Box variant="p" color="text-body-secondary">Resource analysis and unused access findings need an analyzer — create one to get started.</Box>
          </Box>} />
      </CapabilityContainer>
      <CreateAnalyzerModal visible={create} onDismiss={() => setCreate(false)} onDone={a.reload} />
      <DeleteModal visible={del} onDismiss={() => setDel(false)} resourceType="analyzer" names={sel.map((x) => x.Name)}
        onConfirm={async () => { for (const x of sel) await api.deleteAnalyzer(x.Name); notify.success("Analyzer(s) deleted."); setSel([]); a.reload(); }} />
    </SpaceBetween>
  );
}
