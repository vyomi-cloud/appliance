import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Header from "@cloudscape-design/components/header";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import * as api from "./api.js";

export const stateType = (s) => ({ running: "success", stopped: "stopped", terminated: "stopped", pending: "pending", stopping: "pending", "shutting-down": "pending" }[s] || "pending");
export const StateBadge = ({ s }) => <StatusIndicator type={stateType(s)}>{s}</StatusIndicator>;
export const nameOf = (i) => i.name || i.Tags?.Name || "-";

export default function Instances() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [connect, setConnect] = useState(false);
  const t = useAsync(() => api.describeInstances(), []);
  const rows = t.data || [];

  const act = async (fn, verb) => {
    try { await fn(sel.map((i) => i.instanceId)); notify.success(`${verb} ${sel.length === 1 ? sel[0].instanceId : `${sel.length} instances`}.`); t.reload(); }
    catch (e) { notify.error(e); }
  };

  return (
    <SpaceBetween size="l">
      <NotSimulatedContainer title="All instances" feature="Instance alarm states / service health / EC2 health events" note="Account-wide health rollups above the table aren't modeled by Vyomi." />
      <ResourceTable
        resourceName="Instances"
        items={rows}
        trackBy="instanceId"
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Filter Instance by attribute or tag (case-sensitive)"
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (i) => <Link href={href("ec2", "instances", i.instanceId)} onFollow={follow}>{nameOf(i)}</Link> },
          { id: "id", header: "Instance ID", cell: (i) => <Link href={href("ec2", "instances", i.instanceId)} onFollow={follow}>{i.instanceId}</Link> },
          { id: "state", header: "Instance state", cell: (i) => <StateBadge s={i.instanceState?.name} /> },
          { id: "type", header: "Instance type", cell: (i) => i.instanceType },
          { id: "status", header: "Status check", cell: (i) => (i.instanceState?.name === "running" ? "2/2 checks passed" : "-") },
          { id: "az", header: "Availability Zone", cell: (i) => i.placement?.availabilityZone },
          { id: "pubdns", header: "Public IPv4 DNS", cell: (i) => i.dnsName || "-" },
          { id: "pubip", header: "Public IPv4 address", cell: (i) => i.ipAddress || "-" },
          { id: "eip", header: "Elastic IP", cell: () => "-" },
          { id: "ipv6", header: "IPv6 IPs", cell: () => "-" },
          { id: "mon", header: "Monitoring", cell: (i) => (i.monitoring?.state === "enabled" ? "Enabled" : "Disabled") },
          { id: "sg", header: "Security group name", cell: (i) => asFirstGroup(i) },
          { id: "key", header: "Key name", cell: (i) => i.keyName || "-" },
          { id: "launch", header: "Launch time", cell: (i) => i.launchTime },
          { id: "platform", header: "Platform details", cell: (i) => i.platformDetails },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1} onClick={() => setConnect(true)}>Connect</Button>
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "start", text: "Start instance" }, { id: "stop", text: "Stop instance" },
              { id: "reboot", text: "Reboot instance" }, { id: "hibernate", text: "Hibernate instance" },
              { id: "terminate", text: "Terminate instance" },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "start") act(api.startInstances, "Started");
              else if (detail.id === "stop") act(api.stopInstances, "Stopped");
              else if (detail.id === "reboot") act(api.rebootInstances, "Rebooted");
              else if (detail.id === "hibernate") notify.info("Hibernation isn't modeled by Vyomi.");
              else if (detail.id === "terminate") act(api.terminateInstances, "Terminated");
            }}>Instance state</ButtonDropdown>
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "monitor", text: sel[0]?.monitoring?.state === "enabled" ? "Disable detailed monitoring" : "Enable detailed monitoring" },
              { id: "image", text: "Create image", disabled: sel.length !== 1 },
            ]} onItemClick={({ detail }) => {
              if (detail.id === "monitor") (sel[0]?.monitoring?.state === "enabled" ? api.unmonitorInstances : api.monitorInstances)(sel.map((i) => i.instanceId)).then(() => { notify.success("Monitoring updated."); t.reload(); });
              else if (detail.id === "image") navigate("ec2", "instances", sel[0].instanceId, "create-image");
            }}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "launch-instance")} onFollow={follow}>Launch instances</Button>
          </SpaceBetween>
        }
        empty={{ title: "No instances", action: <Button href={href("ec2", "launch-instance")} onFollow={follow}>Launch instances</Button> }}
      />
      <Modal visible={connect} onDismiss={() => setConnect(false)} header="Connect to instance" footer={<Box float="right"><Button onClick={() => setConnect(false)}>Close</Button></Box>}>
        <CapabilityContainer id="ec2.instances.connect" title="Connect" />
      </Modal>
    </SpaceBetween>
  );
}

function asFirstGroup(i) {
  const g = (i.GroupSet || [])[0];
  return g?.groupName || g?.groupId || "-";
}
