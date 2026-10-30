import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Modal from "@cloudscape-design/components/modal";
import Toggle from "@cloudscape-design/components/toggle";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow } from "../../../common/router.js";
import { KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function Settings() {
  return (
    <ContentLayout header={<Header variant="h1">Settings</Header>}>
      <Tabs tabs={[
        { id: "dps", label: "Data protection and security", content: <DataProtection /> },
        { id: "amis", label: "Allowed AMIs", content: <CapabilityContainer id="ec2.settings.other" title="Allowed AMIs" /> },
        { id: "managed", label: "Managed resources - new", content: <CapabilityContainer id="ec2.settings.other" title="Managed resources" /> },
        { id: "zones", label: "Zones", content: <CapabilityContainer id="ec2.settings.other" title="Zones" /> },
        { id: "credit", label: "Default credit specification", content: <CapabilityContainer id="ec2.settings.other" title="Default credit specification" /> },
        { id: "serial", label: "EC2 Serial Console", content: <CapabilityContainer id="ec2.settings.other" title="EC2 Serial Console" /> },
        { id: "asg", label: "Auto Scaling groups", content: <CapabilityContainer id="ec2.settings.other" title="Auto Scaling groups" /> },
        { id: "prefs", label: "EC2 console preferences", content: <CapabilityContainer id="ec2.settings.other" title="EC2 console preferences" /> },
      ]} />
    </ContentLayout>
  );
}

function DataProtection() {
  const notify = useNotify();
  const t = useAsync(() => Promise.all([api.getEbsEncryptionByDefault(), api.getEbsDefaultKmsKeyId()]).then(([enc, kms]) => ({ enc, kms })), []);
  const [modal, setModal] = useState(false);
  const [enc, setEnc] = useState(false);
  const [kms, setKms] = useState("alias/aws/ebs");
  const open = () => { setEnc(!!t.data?.enc); setKms(t.data?.kms || "alias/aws/ebs"); setModal(true); };
  const save = async () => {
    await (enc ? api.enableEbsEncryptionByDefault() : api.disableEbsEncryptionByDefault());
    if (enc) await api.modifyEbsDefaultKmsKeyId(kms); else await api.resetEbsDefaultKmsKeyId();
    notify.success("EBS encryption settings saved.");
    setModal(false); t.reload();
  };
  return (
    <SpaceBetween size="l">
      <KeyValue title="Automatically backup your data" actions={<Button href={href("ec2", "lifecycle-manager")} onFollow={follow}>Manage in Lifecycle Manager</Button>} columns={2}
        items={[["EBS snapshot policy", "No default policy"], ["EBS-backed AMI policy", "No default policy"]]} />
      <KeyValue title="EBS encryption" actions={<Button onClick={open}>Manage</Button>} columns={2}
        items={[["Always encrypt new EBS volumes", t.data?.enc ? "Enabled" : "Disabled"], ["Default encryption key", t.data?.kms || "alias/aws/ebs"]]} />
      <Modal visible={modal} onDismiss={() => setModal(false)} header="Manage EBS encryption"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setModal(false)}>Cancel</Button><Button variant="primary" onClick={save}>Save changes</Button></SpaceBetween></Box>}>
        <SpaceBetween size="l">
          <Toggle checked={enc} onChange={({ detail }) => setEnc(detail.checked)}>Always encrypt new EBS volumes</Toggle>
          {enc && <FormField label="Default encryption key"><Select selectedOption={{ value: kms, label: kms }} onChange={({ detail }) => setKms(detail.selectedOption.value)} options={[{ value: "alias/aws/ebs", label: "alias/aws/ebs" }]} ariaLabel="Default encryption key" /></FormField>}
        </SpaceBetween>
      </Modal>
    </SpaceBetween>
  );
}
