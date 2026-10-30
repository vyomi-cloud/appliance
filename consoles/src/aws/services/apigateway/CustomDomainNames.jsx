import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const ENDPOINT_TYPES = [{ value: "REGIONAL", label: "Regional" }, { value: "EDGE", label: "Edge-optimized" }];

export default function CustomDomainNames() {
  const notify = useNotify();
  const t = useAsync(() => api.listDomainNamesV2(), []);
  const [sel, setSel] = useState([]);
  const [create, setCreate] = useState(false);
  const [name, setName] = useState("");
  const [endpointType, setEndpointType] = useState(ENDPOINT_TYPES[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  return (
    <>
      <ResourceTable
        resourceName="Custom domain names"
        items={t.data || []}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="domainName"
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        empty={{ title: "No custom domain names", action: <Button onClick={() => setCreate(true)}>Add domain name</Button> }}
        columns={[
          { id: "name", header: "Domain name", isRowHeader: true, cell: (d) => d.domainName },
          { id: "status", header: "Status", cell: (d) => d.domainNameConfigurations?.[0]?.domainNameStatus || "-" },
          { id: "type", header: "Endpoint type", cell: (d) => d.domainNameConfigurations?.[0]?.endpointType || "-" },
          { id: "policy", header: "Security policy", cell: (d) => d.domainNameConfigurations?.[0]?.securityPolicy || "-" },
        ]}
        actions={<Button variant="primary" onClick={() => setCreate(true)}>Add domain name</Button>}
      />
      <Modal visible={create} onDismiss={() => setCreate(false)} header="Add domain name"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name} onClick={async () => {
            setBusy(true); setError(null);
            try {
              await api.createDomainNameV2({ domainName: name, domainNameConfigurations: [{ endpointType: endpointType.value }] });
              notify.success(`Domain name "${name}" added.`); setCreate(false); setName(""); t.reload();
            } catch (e) { setError(e); } finally { setBusy(false); }
          }}>Add domain name</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="l">
          {error && <ErrorAlert error={error} />}
          <FormField label="Domain name"><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="api.example.com" ariaLabel="Domain name" /></FormField>
          <FormField label="Endpoint type"><Select selectedOption={endpointType} onChange={({ detail }) => setEndpointType(detail.selectedOption)} options={ENDPOINT_TYPES} /></FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
}
