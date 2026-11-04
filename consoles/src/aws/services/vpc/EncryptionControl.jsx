/* VPC encryption control: per-VPC monitor / enforce mode with an audit of the VPC's network interfaces and load balancers
 * (core/vpc_encryption_core.py). */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import Toggle from "@cloudscape-design/components/toggle";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function EncryptionControl() {
  const notify = useNotify();
  const ctl = useAsync(() => api.describeVpcEncryptionControls(), []);
  const vpcs = useAsync(() => api.describeVpcs(), []);
  const [sel, setSel] = useState([]);
  const [vpc, setVpc] = useState(null);
  const [error, setError] = useState(null);
  const one = sel[0];
  const audit = useAsync(() => (one ? api.vpcEncryptionAudit(one.VpcId) : Promise.resolve([])), [one?.VpcId, ctl.data]);
  const used = new Set((ctl.data || []).map((c) => c.VpcId));
  const options = (vpcs.data || []).filter((v) => !used.has(v.VpcId)).map((v) => ({ value: v.VpcId, label: v.VpcId + (v.Tags?.Name ? ` (${v.Tags.Name})` : "") }));
  const run = async (fn, ok) => { setError(null); try { await fn(); if (ok) notify.success(ok); ctl.reload(); } catch (e) { setError(e); } };
  const bad = (audit.data || []).filter((r) => !r.Encrypted && !r.Excluded);
  return (
    <ContentLayout header={<Header variant="h1" description="Audit and enforce encryption in transit inside a VPC.">VPC encryption control</Header>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <CapabilityContainer id="vpc.encryption-control" title="Encryption controls">
          <SpaceBetween size="m">
            <Table variant="embedded" items={ctl.data || []} loading={ctl.loading} trackBy="Id" selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
              header={<SpaceBetween direction="horizontal" size="xs">
                <Button disabled={!one || one.Mode === "monitor"} onClick={() => run(() => api.modifyVpcEncryptionControl(one.Id, { Mode: "monitor" }), "Switched to monitor mode.")}>Switch to monitor</Button>
                <Button disabled={!one || one.Mode === "enforce"} onClick={() => run(() => api.modifyVpcEncryptionControl(one.Id, { Mode: "enforce" }), "Enforce mode enabled.")}>Switch to enforce</Button>
                <Button disabled={!one} onClick={() => run(async () => { await api.deleteVpcEncryptionControl(one.Id); setSel([]); }, "Encryption control deleted.")}>Delete</Button>
              </SpaceBetween>}
              columnDefinitions={[{ id: "id", header: "Encryption control ID", cell: (c) => c.Id }, { id: "v", header: "VPC", cell: (c) => c.VpcId },
                { id: "m", header: "Mode", cell: (c) => c.Mode }, { id: "s", header: "State", cell: (c) => <StatusIndicator type={c.State === "available" ? "success" : "pending"}>{c.State}</StatusIndicator> },
                { id: "x", header: "Exclusions", cell: (c) => Object.entries(c.Exclusions).filter(([, v]) => v).map(([k]) => k).join(", ") || "-" }]}
              empty={<Box textAlign="center" color="inherit"><b>No encryption controls</b></Box>} />
            <SpaceBetween direction="horizontal" size="xs" alignItems="end">
              <FormField label="VPC"><Select selectedOption={vpc} options={options} onChange={({ detail }) => setVpc(detail.selectedOption)} placeholder="Choose a VPC" ariaLabel="VPC" /></FormField>
              <Button variant="primary" disabled={!vpc} onClick={() => run(async () => { await api.createVpcEncryptionControl(vpc.value); setVpc(null); }, "Encryption control created in monitor mode.")}>Create encryption control</Button>
            </SpaceBetween>
          </SpaceBetween>
        </CapabilityContainer>
        {one && (
          <CapabilityContainer id="vpc.encryption-control" title={`Resource audit - ${one.VpcId}`}
            description={bad.length ? `${bad.length} unencrypted resource(s) block enforce mode.` : "No resources block enforce mode."}>
            <Table variant="embedded" items={audit.data || []} loading={audit.loading}
              columnDefinitions={[{ id: "i", header: "Resource", cell: (r) => r.Id }, { id: "t", header: "Type", cell: (r) => r.Type },
                { id: "e", header: "Encryption", cell: (r) => <StatusIndicator type={r.Encrypted ? "success" : r.Excluded ? "stopped" : "warning"}>{r.Encrypted ? "Encrypted" : r.Excluded ? "Excluded" : "Unencrypted"}</StatusIndicator> },
                { id: "r", header: "Reason", cell: (r) => r.Reason }]}
              empty={<Box textAlign="center" color="inherit">No resources carrying traffic</Box>} />
          </CapabilityContainer>
        )}
      </SpaceBetween>
    </ContentLayout>
  );
}
