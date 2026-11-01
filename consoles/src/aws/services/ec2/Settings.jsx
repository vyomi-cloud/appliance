import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Modal from "@cloudscape-design/components/modal";
import Toggle from "@cloudscape-design/components/toggle";
import FormField from "@cloudscape-design/components/form-field";
import Select from "@cloudscape-design/components/select";
import Input from "@cloudscape-design/components/input";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Table from "@cloudscape-design/components/table";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow } from "../../../common/router.js";
import { KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function Settings() {
  return (
    <ContentLayout header={<Header variant="h1">Settings</Header>}>
      <Tabs tabs={[
        { id: "dps", label: "Data protection and security", content: <DataProtection /> },
        { id: "amis", label: "Allowed AMIs", content: <AllowedAmis /> },
        { id: "managed", label: "Managed resources - new", content: <CapabilityContainer id="ec2.settings.other" title="Managed resources" /> },
        { id: "zones", label: "Zones", content: <Zones /> },
        { id: "credit", label: "Default credit specification", content: <CreditSpecification /> },
        { id: "serial", label: "EC2 Serial Console", content: <SerialConsole /> },
        { id: "asg", label: "Auto Scaling groups", content: <CapabilityContainer id="ec2.settings.other" title="Auto Scaling group defaults" /> },
        { id: "prefs", label: "EC2 console preferences", content: <ConsolePreferences /> },
      ]} />
    </ContentLayout>
  );
}

function AllowedAmis() {
  const notify = useNotify();
  const t = useAsync(() => api.getAllowedImagesSettings(), []);
  const [editing, setEditing] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [providers, setProviders] = useState([]);
  const open = () => { setEnabled(t.data?.state === "enabled"); setProviders((t.data?.criteria || []).flat()); setEditing(true); };
  const PROVIDERS = [{ value: "amazon", label: "Amazon" }, { value: "self", label: "My account" }, { value: "aws-marketplace", label: "AWS Marketplace" }];
  const toggleProvider = (v) => setProviders((xs) => (xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v]));
  const save = async () => {
    await (enabled ? api.enableAllowedImagesSettings() : api.disableAllowedImagesSettings());
    if (enabled) await api.replaceImageCriteria([providers]);
    notify.success(`Allowed AMIs settings saved.${saveNotice("ec2.settings.allowed-amis")}`);
    setEditing(false); t.reload();
  };
  return (
    <CapabilityContainer id="ec2.settings.allowed-amis" title="Allowed AMIs" actions={<Button onClick={open}>Manage</Button>}>
      <KeyValue columns={2} items={[
        ["Allowed AMIs", t.data?.state === "enabled" ? "Enabled" : "Disabled"],
        ["Allowed image providers", (t.data?.criteria || []).flat().join(", ") || "None"],
      ]} />
      <Modal visible={editing} onDismiss={() => setEditing(false)} header="Manage Allowed AMIs"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setEditing(false)}>Cancel</Button><Button variant="primary" onClick={save}>Save changes</Button></SpaceBetween></Box>}>
        <SpaceBetween size="l">
          <Toggle checked={enabled} onChange={({ detail }) => setEnabled(detail.checked)}>Enable Allowed AMIs</Toggle>
          {enabled && (
            <FormField label="Allowed image providers" description="Instances can only be launched from AMIs owned by these providers.">
              {PROVIDERS.map((p) => <Toggle key={p.value} checked={providers.includes(p.value)} onChange={() => toggleProvider(p.value)}>{p.label}</Toggle>)}
            </FormField>
          )}
        </SpaceBetween>
      </Modal>
    </CapabilityContainer>
  );
}

function SerialConsole() {
  const notify = useNotify();
  const t = useAsync(() => api.getSerialConsoleAccessStatus(), []);
  return (
    <CapabilityContainer id="ec2.settings.serial-console" title="EC2 Serial Console">
      <SpaceBetween size="l">
        <KeyValue columns={1} items={[["Serial console access", t.data ? "Enabled" : "Disabled"]]} />
        <Toggle checked={!!t.data} onChange={async ({ detail }) => {
          await (detail.checked ? api.enableSerialConsoleAccess() : api.disableSerialConsoleAccess());
          notify.success(`Serial console access ${detail.checked ? "enabled" : "disabled"}.${saveNotice("ec2.settings.serial-console")}`);
          t.reload();
        }}>Allow access to the EC2 serial console</Toggle>
      </SpaceBetween>
    </CapabilityContainer>
  );
}

const CREDIT_FAMILIES = ["t2", "t3", "t3a", "t4g"];

function CreditSpecification() {
  const notify = useNotify();
  const t = useAsync(() => Promise.all(CREDIT_FAMILIES.map((f) => api.getDefaultCreditSpecification(f).then((v) => [f, v]))).then(Object.fromEntries), []);
  return (
    <CapabilityContainer id="ec2.settings.credit-specification" title="Default credit specification">
      <Table
        variant="embedded"
        items={CREDIT_FAMILIES}
        columnDefinitions={[
          { id: "family", header: "Instance family", cell: (f) => f },
          { id: "spec", header: "Default credit specification", cell: (f) => (
            <RadioGroup value={t.data?.[f] || "standard"} onChange={async ({ detail }) => {
              await api.modifyDefaultCreditSpecification(f, detail.value);
              notify.success(`Default credit specification for ${f} saved.${saveNotice("ec2.settings.credit-specification")}`);
              t.reload();
            }} items={[{ value: "standard", label: "Standard" }, { value: "unlimited", label: "Unlimited" }]} />
          ) },
        ]}
      />
    </CapabilityContainer>
  );
}

function Zones() {
  const t = useAsync(() => api.describeAvailabilityZones(), []);
  return (
    <CapabilityContainer id="ec2.settings.zones" title="Zones">
      <Table
        variant="embedded"
        items={t.data || []}
        loading={t.loading}
        columnDefinitions={[
          { id: "name", header: "Zone name", cell: (z) => z.ZoneName }, { id: "id", header: "Zone ID", cell: (z) => z.ZoneId },
          { id: "state", header: "State", cell: (z) => z.State }, { id: "region", header: "Region", cell: (z) => z.RegionName },
        ]}
      />
    </CapabilityContainer>
  );
}

const PREFS_KEY = "vyomi.ec2.console-preferences";

function ConsolePreferences() {
  const notify = useNotify();
  const [prefs, setPrefs] = useState(() => { try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || { navCollapsed: false, defaultView: "list" }; } catch { return { navCollapsed: false, defaultView: "list" }; } });
  const save = (patch) => {
    const next = { ...prefs, ...patch };
    setPrefs(next);
    localStorage.setItem(PREFS_KEY, JSON.stringify(next));
    notify.success("Console preferences saved.");
  };
  return (
    <Box>
      <SpaceBetween size="l">
        <Toggle checked={prefs.navCollapsed} onChange={({ detail }) => save({ navCollapsed: detail.checked })}>Collapse navigation by default</Toggle>
        <FormField label="Default resource view">
          <Select selectedOption={{ value: prefs.defaultView, label: prefs.defaultView === "grid" ? "Grid view" : "List view" }}
            onChange={({ detail }) => save({ defaultView: detail.selectedOption.value })}
            options={[{ value: "list", label: "List view" }, { value: "grid", label: "Grid view" }]} ariaLabel="Default resource view" />
        </FormField>
      </SpaceBetween>
    </Box>
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
