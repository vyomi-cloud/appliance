import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Toggle from "@cloudscape-design/components/toggle";
import Button from "@cloudscape-design/components/button";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Link from "@cloudscape-design/components/link";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow } from "../../../common/router.js";
import * as api from "./api.js";

function BlockPublicAccess() {
  const notify = useNotify();
  const bpa = useAsync(() => api.getVpcBlockPublicAccessOptions(), []);
  const excl = useAsync(() => api.describeVpcBlockPublicAccessExclusions(), []);
  const [mode, setMode] = useState(null);
  const [busy, setBusy] = useState(false);
  const current = mode ?? bpa.data?.InternetGatewayBlockMode ?? "off";
  const save = async () => {
    setBusy(true);
    try { await api.modifyVpcBlockPublicAccessOptions(current); notify.success(`Block Public Access set to "${current}".${saveNotice("aws.vpc.console-settings")}`); bpa.reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <SpaceBetween size="l">
      <FormField label="Internet gateway block mode"
        description="Real behaviour change: when not 'off', internet-gateway routes stop working (both Reachability Analyzer and offline packet enforcement honor this) for every VPC/subnet except those explicitly excluded below.">
        <RadioGroup value={current} onChange={({ detail }) => setMode(detail.value)} items={[
          { value: "off", label: "Off" },
          { value: "block-ingress", label: "Block ingress — bidirectional traffic to resources with internet gateways is allowed, but inbound traffic initiated from the internet is blocked" },
          { value: "block-bidirectional", label: "Block bidirectional — all internet traffic to and from VPCs/subnets with internet gateways is blocked" },
        ]} />
      </FormField>
      <Button variant="primary" loading={busy} onClick={save}>Save changes</Button>
      <Table items={excl.data || []} header={<Header variant="h3" counter={`(${(excl.data || []).length})`}>Exclusions</Header>}
        columnDefinitions={[
          { id: "r", header: "Resource", cell: (x) => x.ResourceArn },
          { id: "m", header: "Exclusion mode", cell: (x) => x.Mode },
          { id: "s", header: "State", cell: (x) => x.State },
        ]}
        empty={<Box textAlign="center" color="inherit">No exclusions — every VPC/subnet is subject to the mode above.</Box>} />
    </SpaceBetween>
  );
}

function LocalZones() {
  const [optedIn, setOptedIn] = useState(false);
  return (
    <FormField label="Local Zones" description="Opt in to show Local Zone availability zones in the AZ picker when creating subnets.">
      <Toggle checked={optedIn} onChange={({ detail }) => setOptedIn(detail.checked)}>Enable Local Zones in the Availability Zone list</Toggle>
    </FormField>
  );
}

export default function Settings() {
  return (
    <ContentLayout header={<Header variant="h1">Settings</Header>}>
      <SpaceBetween size="l">
        <CapabilityContainer id="aws.vpc.console-settings" title="VPC Block Public Access" description="Account-wide guardrail against accidental internet exposure.">
          <BlockPublicAccess />
        </CapabilityContainer>
        <Container header={<Header variant="h2">Zones</Header>}><LocalZones /></Container>
        <Container header={<Header variant="h2">Encryption</Header>}>
          <Box variant="p">Default EBS volume encryption is managed on the EC2 console's <Link href={href("ec2", "settings")} onFollow={follow}>Account attributes / EBS encryption</Link> page (one account-wide setting, shared by every EC2/VPC resource).</Box>
        </Container>
        <Container header={<Header variant="h2">Console experiments</Header>}>
          <Box variant="p" color="text-body-secondary">Early-access UI toggles — cosmetic only, same as real AWS: they change what the console shows you, not how Vyomi behaves.</Box>
          <Toggle checked={false} onChange={() => {}}>Enable the new VPC resource map experience</Toggle>
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
