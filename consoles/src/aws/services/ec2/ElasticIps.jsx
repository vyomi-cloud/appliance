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
import { TAG_I18N } from "./InstanceDetail.jsx";
import * as api from "./api.js";

const opt = (v) => ({ value: v, label: v });
const POOLS = ["Amazon's pool of IPv4 addresses", "Public IPv4 address that you bring to your AWS account", "Customer-owned pool of IPv4 addresses", "Allocate using an IPv4 IPAM pool"];

export function ElasticIps() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [assocModal, setAssocModal] = useState(false);
  const [instanceId, setInstanceId] = useState("");
  const t = useAsync(() => api.describeAddresses(), []);
  const instances = useAsync(() => api.describeInstances(), []).data || [];
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Select an elastic IP address</Header>}>
      <ResourceTable
        resourceName="Elastic IP addresses"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="allocationId"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find elastic IP addresses by attribute or tag"
        empty={{ title: "No Elastic IP addresses found in this Region" }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (a) => a.Tags?.Name || "-" },
          { id: "ip", header: "Allocated IPv4 address", cell: (a) => a.publicIp },
          { id: "type", header: "Type", cell: (a) => a.domain },
          { id: "id", header: "Allocation ID", cell: (a) => a.allocationId },
          { id: "rdns", header: "Reverse DNS record", cell: () => "-" },
          { id: "inst", header: "Associated instance ID", cell: (a) => a.instanceId || "-" },
          { id: "priv", header: "Private IP address", cell: (a) => a.privateIpAddress || "-" },
          { id: "assoc", header: "Association ID", cell: (a) => a.associationId || "-" },
          { id: "nio", header: "Network interface owner account ID", cell: () => "-" },
          { id: "nbg", header: "Network border group", cell: (a) => a.networkBorderGroup },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "release", text: "Release Elastic IP addresses", disabled: sel.some((a) => a.instanceId) },
              { id: "assoc", text: "Associate Elastic IP address", disabled: sel.length !== 1 || !!sel[0]?.instanceId },
              { id: "disassoc", text: "Disassociate Elastic IP address", disabled: sel.length !== 1 || !sel[0]?.instanceId },
              { id: "rdns", text: "Update reverse DNS" },
            ]} onItemClick={async ({ detail }) => {
              if (detail.id === "release") { for (const a of sel) await api.releaseAddress(a.allocationId); notify.success("Elastic IP address(es) released."); setSel([]); t.reload(); }
              else if (detail.id === "assoc") setAssocModal(true);
              else if (detail.id === "disassoc") { await api.disassociateAddress(sel[0].associationId); notify.success("Disassociated."); setSel([]); t.reload(); }
              else notify.info("Reverse DNS records aren't modeled by Vyomi.");
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "allocate-elastic-ip")} onFollow={follow}>Allocate Elastic IP address</Button>
          </SpaceBetween>
        }
      />
      <Modal visible={assocModal} onDismiss={() => setAssocModal(false)} header="Associate Elastic IP address"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setAssocModal(false)}>Cancel</Button>
          <Button variant="primary" disabled={!instanceId} onClick={async () => { await api.associateAddress(sel[0].allocationId, instanceId); notify.success("Associated."); setAssocModal(false); setSel([]); t.reload(); }}>Associate</Button></SpaceBetween></Box>}>
        <FormField label="Instance"><Select selectedOption={instanceId ? opt(instanceId) : null} onChange={({ detail }) => setInstanceId(detail.selectedOption.value)}
          options={instances.map((i) => ({ value: i.instanceId, label: `${i.instanceId} (${i.instanceState?.name})` }))} placeholder="Select an instance" ariaLabel="Instance" /></FormField>
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
      notify.success(`Allocated Elastic IP address ${a.publicIp}.`);
      navigate("ec2", "elastic-ips");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Allocate Elastic IP address</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "elastic-ips")} onFollow={follow}>Cancel</Button>
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
