import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Checkbox from "@cloudscape-design/components/checkbox";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Table from "@cloudscape-design/components/table";
import TagEditor from "@cloudscape-design/components/tag-editor";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { TAG_I18N } from "./InstanceDetail.jsx";
import * as api from "./api.js";

export default function CreateImage({ params }) {
  const notify = useNotify();
  const id = params.id;
  const t = useAsync(() => api.describeInstance(id), [id]);
  const [name, setName] = useState(`image-${id}`);
  const [desc, setDesc] = useState("");
  const [reboot, setReboot] = useState(true);
  const [tagTogether, setTagTogether] = useState("together");
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const imageId = await api.createImage({ InstanceId: id, Name: name, Description: desc, NoReboot: !reboot,
        TagSpecification: tags.length ? [{ ResourceType: "image", Tag: tags.filter((t) => !t.markedForRemoval && t.key).map((t) => ({ Key: t.key, Value: t.value })) }] : undefined });
      notify.success(`Request to create image "${name}" (${imageId}) has been submitted.`);
      navigate("ec2", "amis", imageId);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create image</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "instances", id)} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name} onClick={submit}>Create image</Button>
        </SpaceBetween>
      }>
        <SpaceBetween size="l">
          <Container header={<Header variant="h2">Image settings</Header>}>
            <SpaceBetween size="l">
              <FormField label="Instance ID"><Input value={id} readOnly ariaLabel="Instance ID" /></FormField>
              <FormField label="Image name" constraintText="Maximum 127 characters. Can't be modified after creation.">
                <Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Image name" />
              </FormField>
              <FormField label="Image description - optional" constraintText="Maximum 255 characters">
                <Input value={desc} onChange={({ detail }) => setDesc(detail.value)} ariaLabel="Image description - optional" />
              </FormField>
              <Checkbox checked={reboot} onChange={({ detail }) => setReboot(detail.checked)}>Reboot instance</Checkbox>
              <Table variant="embedded" items={(t.data?.BlockDeviceMapping || [])} header={<Header variant="h3">Instance volumes</Header>}
                columnDefinitions={[
                  { id: "type", header: "Storage type", cell: () => "EBS" }, { id: "dev", header: "Device", cell: (b) => b.deviceName },
                  { id: "snap", header: "Snapshot", cell: () => "New snapshot" }, { id: "size", header: "Size", cell: () => "-" },
                  { id: "vt", header: "Volume type", cell: () => "-" }, { id: "iops", header: "IOPS", cell: () => "-" },
                  { id: "tp", header: "Throughput", cell: () => "-" }, { id: "dot", header: "Delete on termination", cell: (b) => b.ebs?.deleteOnTermination },
                  { id: "enc", header: "Encrypted", cell: () => "-" },
                ]}
                empty={<Box textAlign="center" color="inherit">Loading instance volumes</Box>} />
            </SpaceBetween>
          </Container>
          <Container header={<Header variant="h2">Tags - optional</Header>}>
            <SpaceBetween size="l">
              <RadioGroup value={tagTogether} onChange={({ detail }) => setTagTogether(detail.value)} items={[
                { value: "together", label: "Tag image and snapshots together" }, { value: "separately", label: "Tag image and snapshots separately" },
              ]} />
              <FormField label="Tags"><TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} /></FormField>
            </SpaceBetween>
          </Container>
        </SpaceBetween>
      </Form>
    </ContentLayout>
  );
}
