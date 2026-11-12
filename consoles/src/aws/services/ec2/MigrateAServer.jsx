/* Migrate a server - AWS Application Migration Service source servers, replication + launch settings and the
 * test / cutover lifecycle. Cutover launches a REAL EC2 instance (core/mgn_core.py); replication itself is records only. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import * as mgn from "./mgnApi.js";
import * as ec2 from "./api.js";

const TONE = { NOT_READY: "pending", READY_FOR_TEST: "info", TEST_IN_PROGRESS: "in-progress", READY_FOR_CUTOVER: "info", CUTTING_OVER: "in-progress", CUTOVER: "success", DISCONNECTED: "stopped" };
const opt = (v) => ({ value: v, label: v });

export default function MigrateAServer() {
  const notify = useNotify();
  const servers = useAsync(() => mgn.describeSourceServers({}), []);
  const tpls = useAsync(() => mgn.describeTemplates(), []);
  const subnets = useAsync(() => ec2.describeSubnets(), []);
  const [sel, setSel] = useState([]);
  const [dlg, setDlg] = useState(null);
  const [f, setF] = useState({});
  const set = (k) => ({ detail }) => setF((x) => ({ ...x, [k]: detail.value }));
  const one = sel[0] ? (servers.data || []).find((x) => x.sourceServerID === sel[0].sourceServerID) || sel[0] : undefined;   // fresh row after each action
  const reload = () => { servers.reload(); tpls.reload(); };
  const run = async (fn, ok) => { try { await fn(); if (ok) notify.success(ok); setDlg(null); reload(); } catch (e) { notify.error(e); } };
  const subnetOpts = (subnets.data || []).map((s) => ({ value: s.subnetId, label: `${s.subnetId} (${s.cidrBlock || ""})` }));
  const st = one?.lifeCycle?.state;
  const openLaunch = async () => { try { const l = await mgn.getLaunch(one.sourceServerID); setF({ subnet: l.targetSubnetId, type: l.targetInstanceType, disp: l.launchDisposition, sizing: l.targetInstanceTypeRightSizingMethod }); setDlg("launch"); } catch (e) { notify.error(e); } };
  const openRepl = async () => { try { const r = await mgn.getReplication(one.sourceServerID); setF({ subnet: r.stagingAreaSubnetId, bw: String(r.bandwidthThrottling), rtype: r.replicationServerInstanceType }); setDlg("repl"); } catch (e) { notify.error(e); } };
  return (
    <ContentLayout header={<Header variant="h1" description="Source servers, replication and launch settings, test and cutover.">Migrate a server</Header>}>
      <SpaceBetween size="l">
        <Alert type="info" header="Replication is simulated as records">
          No agent runs on a source machine and no disk data is copied: a source server is registered here (the stand-in for installing the replication agent) and its
          replication state advances with time. Test and cutover really launch an EC2 instance, from a synthetic image sized like the source disks.
        </Alert>
        <CapabilityContainer id="ec2.migration.application-migration-service" title="Source servers">
          <ResourceTable resourceName="Source servers" variant="embedded" items={servers.data || []} loading={servers.loading} error={servers.error} onRefresh={reload}
            trackBy="sourceServerID" selectionType="single" selectedItems={sel} onSelectionChange={setSel} empty={{ title: "No source servers" }}
            actions={<SpaceBetween direction="horizontal" size="xs">
              <Button disabled={!one} onClick={openRepl}>Replication settings</Button>
              <Button disabled={!one} onClick={openLaunch}>Launch settings</Button>
              <Button disabled={!one || !["READY_FOR_TEST", "READY_FOR_CUTOVER"].includes(st)} onClick={() => run(() => mgn.startTest([one.sourceServerID]), "Test instance launched.")}>Launch test instance</Button>
              <Button disabled={st !== "TEST_IN_PROGRESS"} onClick={() => run(() => mgn.changeLifeCycle(one.sourceServerID, "READY_FOR_CUTOVER"), "Marked ready for cutover.")}>Mark as ready for cutover</Button>
              <Button disabled={!one || !["READY_FOR_TEST", "READY_FOR_CUTOVER", "TEST_IN_PROGRESS"].includes(st)} onClick={() => run(() => mgn.startCutover([one.sourceServerID]), "Cutover instance launched.")}>Launch cutover instance</Button>
              <Button disabled={st !== "CUTTING_OVER"} onClick={() => run(() => mgn.finalizeCutover(one.sourceServerID), "Cutover finalized.")}>Finalize cutover</Button>
              <Button disabled={!one?.launchedInstance || st === "CUTOVER"} onClick={() => run(() => mgn.terminateTargets([one.sourceServerID]), "Target instance terminated.")}>Terminate target instance</Button>
              <Button disabled={!one || !["CUTOVER", "DISCONNECTED"].includes(st)} onClick={() => run(() => mgn.markArchived(one.sourceServerID), "Source server archived.")}>Archive</Button>
              <Button variant="primary" onClick={() => { setF({ tpl: tpls.data?.[0]?.replicationConfigurationTemplateID }); setDlg("register"); }}>Add source server</Button>
            </SpaceBetween>}
            columns={[
              { id: "n", header: "Source server", isRowHeader: true, cell: (s) => s.sourceProperties.identificationHints.hostname },
              { id: "id", header: "ID", cell: (s) => s.sourceServerID },
              { id: "lc", header: "Migration lifecycle", cell: (s) => <StatusIndicator type={TONE[s.lifeCycle.state] || "pending"}>{s.lifeCycle.state}</StatusIndicator> },
              { id: "dr", header: "Data replication", cell: (s) => s.dataReplicationInfo.dataReplicationState },
              { id: "os", header: "OS", cell: (s) => s.sourceProperties.os.fullString },
              { id: "ty", header: "Recommended type", cell: (s) => s.sourceProperties.recommendedInstanceType },
              { id: "in", header: "Target instance", cell: (s) => (s.launchedInstance ? <Button variant="inline-link" onClick={() => navigate("ec2", "instances", s.launchedInstance.ec2InstanceID)}>{s.launchedInstance.ec2InstanceID}</Button> : "-") },
            ]} />
        </CapabilityContainer>
        <CapabilityContainer noBadge id="ec2.migration.application-migration-service" title="Replication settings templates">
          <ResourceTable resourceName="Replication templates" variant="embedded" items={tpls.data || []} loading={tpls.loading} error={tpls.error} onRefresh={tpls.reload}
            trackBy="replicationConfigurationTemplateID" empty={{ title: "No replication settings template", description: "Create one before adding a source server." }}
            actions={<Button onClick={() => { setF({}); setDlg("tpl"); }}>Create template</Button>}
            columns={[
              { id: "i", header: "Template ID", isRowHeader: true, cell: (t) => t.replicationConfigurationTemplateID },
              { id: "s", header: "Staging subnet", cell: (t) => t.stagingAreaSubnetId },
              { id: "t", header: "Replication server type", cell: (t) => t.replicationServerInstanceType },
              { id: "b", header: "Bandwidth throttling (Mbps)", cell: (t) => (t.bandwidthThrottling || "Unlimited") },
            ]} />
        </CapabilityContainer>
      </SpaceBetween>
      <Modal visible={dlg === "tpl"} onDismiss={() => setDlg(null)} header="Create replication settings template"
        footer={<Box float="right"><Button variant="primary" disabled={!f.subnet} onClick={() => run(() => mgn.createTemplate({ stagingAreaSubnetId: f.subnet, replicationServerInstanceType: f.rtype || "t3.small", bandwidthThrottling: Number(f.bw || 0) }), "Template created.")}>Create template</Button></Box>}>
        <SpaceBetween size="m">
          <FormField label="Staging area subnet"><Select ariaLabel="Staging area subnet" selectedOption={subnetOpts.find((o) => o.value === f.subnet) || null} options={subnetOpts} onChange={({ detail }) => setF((x) => ({ ...x, subnet: detail.selectedOption.value }))} placeholder="Choose a subnet" /></FormField>
          <FormField label="Replication server instance type"><Input ariaLabel="Replication server instance type" value={f.rtype || "t3.small"} onChange={set("rtype")} /></FormField>
          <FormField label="Bandwidth throttling (Mbps, 0 = unlimited)"><Input ariaLabel="Bandwidth throttling" type="number" value={f.bw || "0"} onChange={set("bw")} /></FormField>
        </SpaceBetween>
      </Modal>
      <Modal visible={dlg === "register"} onDismiss={() => setDlg(null)} header="Add source server"
        footer={<Box float="right"><Button variant="primary" disabled={!f.host || !f.tpl} onClick={() => run(() => mgn.registerSourceServer({ hostname: f.host, os: f.os || "Linux", cpus: Number(f.cpus || 2), ramBytes: Number(f.ram || 4) * 1024 ** 3, disks: [{ deviceName: "/dev/sda", bytes: Number(f.disk || 8) * 1024 ** 3 }], replicationConfigurationTemplateID: f.tpl }), "Source server added.")}>Add</Button></Box>}>
        <SpaceBetween size="m">
          <FormField label="Hostname"><Input ariaLabel="Hostname" value={f.host || ""} onChange={set("host")} /></FormField>
          <FormField label="Operating system"><Input ariaLabel="Operating system" value={f.os || "Linux"} onChange={set("os")} /></FormField>
          <FormField label="vCPUs"><Input ariaLabel="vCPUs" type="number" value={f.cpus || "2"} onChange={set("cpus")} /></FormField>
          <FormField label="Memory (GiB)"><Input ariaLabel="Memory GiB" type="number" value={f.ram || "4"} onChange={set("ram")} /></FormField>
          <FormField label="Boot disk (GiB)"><Input ariaLabel="Boot disk GiB" type="number" value={f.disk || "8"} onChange={set("disk")} /></FormField>
        </SpaceBetween>
      </Modal>
      <Modal visible={dlg === "launch"} onDismiss={() => setDlg(null)} header="Launch settings"
        footer={<Box float="right"><Button variant="primary" onClick={() => run(() => mgn.updateLaunch(one.sourceServerID, { targetSubnetId: f.subnet || "", targetInstanceType: f.type || "", launchDisposition: f.disp, targetInstanceTypeRightSizingMethod: f.sizing }), "Launch settings saved.")}>Save</Button></Box>}>
        <SpaceBetween size="m">
          <FormField label="Target subnet"><Select ariaLabel="Target subnet" selectedOption={subnetOpts.find((o) => o.value === f.subnet) || null} options={subnetOpts} onChange={({ detail }) => setF((x) => ({ ...x, subnet: detail.selectedOption.value }))} placeholder="Default network" /></FormField>
          <FormField label="Instance type right sizing"><Select ariaLabel="Right sizing" selectedOption={opt(f.sizing || "BASIC")} options={["NONE", "BASIC", "IN_AWS"].map(opt)} onChange={({ detail }) => setF((x) => ({ ...x, sizing: detail.selectedOption.value }))} /></FormField>
          <FormField label="Instance type (used when right sizing is None)"><Input ariaLabel="Instance type" value={f.type || ""} onChange={set("type")} /></FormField>
          <FormField label="Launched instance state"><Select ariaLabel="Launch disposition" selectedOption={opt(f.disp || "STOPPED")} options={["STOPPED", "STARTED"].map(opt)} onChange={({ detail }) => setF((x) => ({ ...x, disp: detail.selectedOption.value }))} /></FormField>
        </SpaceBetween>
      </Modal>
      <Modal visible={dlg === "repl"} onDismiss={() => setDlg(null)} header="Replication settings"
        footer={<Box float="right"><Button variant="primary" onClick={() => run(() => mgn.updateReplication(one.sourceServerID, { stagingAreaSubnetId: f.subnet, bandwidthThrottling: Number(f.bw || 0), replicationServerInstanceType: f.rtype }), "Replication settings saved.")}>Save</Button></Box>}>
        <SpaceBetween size="m">
          <FormField label="Staging area subnet"><Select ariaLabel="Staging subnet" selectedOption={subnetOpts.find((o) => o.value === f.subnet) || null} options={subnetOpts} onChange={({ detail }) => setF((x) => ({ ...x, subnet: detail.selectedOption.value }))} /></FormField>
          <FormField label="Replication server instance type"><Input ariaLabel="Replication type" value={f.rtype || ""} onChange={set("rtype")} /></FormField>
          <FormField label="Bandwidth throttling (Mbps)"><Input ariaLabel="Bandwidth" type="number" value={f.bw || "0"} onChange={set("bw")} /></FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}
