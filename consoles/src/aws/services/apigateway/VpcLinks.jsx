/* VPC links — split view: list on the left ("Last updated …"), selected link's detail
 * on the right, matching the native console. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Grid from "@cloudscape-design/components/grid";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import TextFilter from "@cloudscape-design/components/text-filter";
import Table from "@cloudscape-design/components/table";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function VpcLinks() {
  const notify = useNotify();
  const t = useAsync(() => api.listVpcLinksV2(), []);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState(null);
  const [create, setCreate] = useState(false);
  const [name, setName] = useState("");
  const [subnet, setSubnet] = useState("subnet-0123456789abcdef0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const links = (t.data || []).filter((l) => l.name.toLowerCase().includes(filter.toLowerCase()));
  const link = links.find((l) => l.vpcLinkId === selected);

  return (
    <ContentLayout header={<Header variant="h1">VPC links</Header>}>
      <Grid gridDefinition={[{ colspan: 4 }, { colspan: 8 }]}>
        <Container header={<Header variant="h2" actions={<Button variant="primary" onClick={() => setCreate(true)}>Create</Button>}>VPC links</Header>}>
          <SpaceBetween size="s">
            <TextFilter filteringText={filter} filteringPlaceholder="Find APIs" onChange={({ detail }) => setFilter(detail.filteringText)} />
            <Box color="text-body-secondary">Last updated {fmtDate(Date.now())}</Box>
            <Table variant="embedded" items={links} trackBy="vpcLinkId" selectionType="single"
              selectedItems={links.filter((l) => l.vpcLinkId === selected)}
              onSelectionChange={({ detail }) => setSelected(detail.selectedItems[0]?.vpcLinkId)}
              columnDefinitions={[
                { id: "name", header: "Name", isRowHeader: true, cell: (l) => l.name },
                { id: "type", header: "API type", cell: () => "HTTP" },
              ]}
              empty={<Box color="text-body-secondary">No VPC links</Box>} />
          </SpaceBetween>
        </Container>
        {link ? (
          <KeyValue title={link.name} columns={3} items={[
            ["Name", link.name], ["API type", "HTTP"], ["Status", link.vpcLinkStatus],
            ["Security group IDs", link.securityGroupIds?.join(", ") || "-"], ["Subnet IDs", link.subnetIds?.join(", ")],
          ]} />
        ) : <Box color="text-body-secondary">Choose a VPC link to view its details.</Box>}
      </Grid>
      <Modal visible={create} onDismiss={() => setCreate(false)} header="Create VPC link"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setCreate(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name} onClick={async () => {
            setBusy(true); setError(null);
            try { await api.createVpcLinkV2({ name, subnetIds: [subnet] }); notify.success(`VPC link "${name}" created.`); setCreate(false); setName(""); t.reload(); }
            catch (e) { setError(e); } finally { setBusy(false); }
          }}>Create</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="l">
          {error && <ErrorAlert error={error} />}
          <FormField label="Name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" /></FormField>
          <FormField label="Subnet ID"><Input value={subnet} onChange={({ detail }) => setSubnet(detail.value)} ariaLabel="Subnet ID" /></FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}
