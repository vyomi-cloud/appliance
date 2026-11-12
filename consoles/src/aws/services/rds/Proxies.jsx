import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const FAMILIES = ["MYSQL", "POSTGRESQL", "SQLSERVER"];

function CreateModal({ visible, onDismiss, onDone, notify }) {
  const [name, setName] = useState("");
  const [family, setFamily] = useState(FAMILIES[1]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <Modal visible={visible} onDismiss={onDismiss} header="Create proxy"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name} onClick={async () => {
          setBusy(true); setError(null);
          try { await api.createDBProxy(name, family); notify.success(`Creating proxy "${name}".`); onDone(); onDismiss(); setName(""); }
          catch (e) { setError(e); } finally { setBusy(false); }
        }}>Create proxy</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Proxy identifier"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Proxy identifier" /></FormField>
        <FormField label="Engine family">
          <Select selectedOption={{ value: family, label: family }} onChange={({ detail }) => setFamily(detail.selectedOption.value)}
            options={FAMILIES.map((v) => ({ value: v, label: v }))} ariaLabel="Engine family" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function Proxies() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const t = useAsync(() => api.describeDBProxies());
  return (
    <>
      <ResourceTable
        resourceName="Proxies"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="DBProxyName"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No proxies", action: <Button onClick={() => setCreate(true)}>Create proxy</Button> }}
        columns={[
          { id: "name", header: "Proxy identifier", isRowHeader: true, cell: (p) => p.DBProxyName },
          { id: "status", header: "Status", cell: (p) => <StatusIndicator type={p.Status === "available" ? "success" : "in-progress"}>{p.Status}</StatusIndicator> },
          { id: "family", header: "Engine family", cell: (p) => p.EngineFamily },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={sel.length !== 1} items={[{ id: "delete", text: "Delete" }]} onItemClick={async () => {
              try { await api.deleteDBProxy(sel[0].DBProxyName); notify.success("Proxy deleted."); setSel([]); t.reload(); }
              catch (e) { notify.error(e); }
            }}>Actions</ButtonDropdown>
            <Button variant="primary" onClick={() => setCreate(true)}>Create proxy</Button>
          </SpaceBetween>
        }
      />
      <CreateModal visible={create} onDismiss={() => setCreate(false)} onDone={t.reload} notify={notify} />
    </>
  );
}
