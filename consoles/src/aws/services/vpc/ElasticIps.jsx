/* Same component as the EC2 console's Elastic IPs (ui-spec notes this explicitly). */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import RadioGroup from "@cloudscape-design/components/radio-group";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import { TAG_I18N } from "./tagI18n.js";
import * as api from "./api.js";

const opt = (v) => ({ value: v, label: v });
const POOLS = ["Amazon's pool of IPv4 addresses", "Public IPv4 address that you bring to your AWS account", "Customer-owned pool of IPv4 addresses", "Allocate using an IPv4 IPAM pool"];

export function ElasticIps() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [assocModal, setAssocModal] = useState(false);
  const [instanceId, setInstanceId] = useState("");
  const t = useAsync(() => api.describeAddresses(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Elastic IP addresses</Header>}>
      <ResourceTable
        resourceName="Elastic IP addresses"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="AllocationId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find elastic IP addresses by attribute or tag"
        empty={<Box textAlign="center">No Elastic IP addresses found in this Region</Box>}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (a) => a.Tags?.Name || "-" },
          { id: "ip", header: "Allocated IPv4 address", cell: (a) => a.PublicIp },
          { id: "type", header: "Type", cell: (a) => a.Domain },
          { id: "id", header: "Allocation ID", cell: (a) => a.AllocationId },
          { id: "rdns", header: "Reverse DNS record", cell: () => "-" },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "release", text: "Release Elastic IP addresses", disabled: sel.some((a) => a.InstanceId) },
              { id: "assoc", text: "Associate Elastic IP address", disabled: sel.length !== 1 || !!sel[0]?.InstanceId },
              { id: "disassoc", text: "Disassociate Elastic IP address", disabled: sel.length !== 1 || !sel[0]?.InstanceId },
            ]} onItemClick={async ({ detail }) => {
              if (detail.id === "release") { for (const a of sel) await api.releaseAddress(a.AllocationId); notify.success("Elastic IP address(es) released."); setSel([]); t.reload(); }
              else if (detail.id === "assoc") setAssocModal(true);
              else if (detail.id === "disassoc") { await api.disassociateAddress(sel[0].AssociationId); notify.success("Disassociated."); setSel([]); t.reload(); }
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("vpc", "allocate-elastic-ip")} onFollow={follow}>Allocate Elastic IP address</Button>
          </SpaceBetween>
        }
      />
      <Modal visible={assocModal} onDismiss={() => setAssocModal(false)} header="Associate Elastic IP address"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setAssocModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!instanceId} onClick={async () => { await api.associateAddress(sel[0].AllocationId, instanceId); notify.success("Associated."); setAssocModal(false); setSel([]); t.reload(); }}>Associate</Button></SpaceBetween></Box>}>
        <FormField label="Instance ID"><input value={instanceId} onChange={(e) => setInstanceId(e.target.value)} placeholder="i-0123456789abcdef0" style={{ width: "100%" }} /></FormField>
      </Modal>
    </ContentLayout>
  );
}

export function AllocateElasticIp() {
  const notify = useNotify();
  const [pool, setPool] = useState(POOLS[0]);
  const [nbg, setNbg] = useState("us-east-1");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const a = await api.allocateAddress(Object.fromEntries(tags.filter((t) => !t.markedForRemoval && t.key).map((t) => [t.key, t.value])));
      notify.success(`Allocated Elastic IP address ${a.PublicIp}.`);
      navigate("vpc", "elastic-ips");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Allocate Elastic IP address</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("vpc", "elastic-ips")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={pool !== POOLS[0]} onClick={submit}>Allocate</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Elastic IP address settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Public IPv4 address pool">
                <RadioGroup value={pool} onChange={({ detail }) => setPool(detail.value)} items={POOLS.map((v) => ({ value: v, label: v }))} />
              </FormField>
              {pool !== POOLS[0] && <NotSimulated feature={pool} note="Vyomi only backs allocation from Amazon's own pool of IPv4 addresses." />}
              <FormField label="Network border group"><Select selectedOption={opt(nbg)} onChange={({ detail }) => setNbg(detail.selectedOption.value)} options={["us-east-1", "us-east-1-bos-1"].map(opt)} ariaLabel="Network border group" /></FormField>
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Tags - optional</Header>}>
            <FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
