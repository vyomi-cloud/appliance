/* AWS RAM resource sharing — real object model (core/ram_core.py): shares, principal/resource
 * associations, a real state machine, and real owner-side enforcement (a shared subnet/security
 * group cannot be deleted while an association is ASSOCIATED — see vpc_core._delete_subnet /
 * _delete_security_group). Vyomi is a single-account simulator, so the invited principal's own
 * view of the shared resource can't be observed here — that half of RAM's effect has no second
 * account to show it from; see aws.vpc.resource-sharing's limitations. */
import { useState } from "react";
import Table from "@cloudscape-design/components/table";
import Header from "@cloudscape-design/components/header";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

function ShareResourceModal({ resourceArn, onDismiss, onShared }) {
  const notify = useNotify();
  const shares = useAsync(() => api.getResourceShares(), []);
  const [mode, setMode] = useState("new");
  const [shareArn, setShareArn] = useState("");
  const [name, setName] = useState("");
  const [principal, setPrincipal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      if (mode === "new") {
        const s = await api.createResourceShare(name, [resourceArn], principal ? [principal] : []);
        notify.success(`Resource share "${s.resourceShareArn}" created.`);
      } else {
        await api.associateResourceShare(shareArn, [resourceArn], []);
        notify.success("Resource associated with the share.");
      }
      onShared();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible onDismiss={onDismiss} header="Share resource via AWS RAM"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button formAction="none" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={mode === "new" ? !name : !shareArn} onClick={submit}>Share</Button>
      </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="l">
          <FormField label="Resource share">
            <Select selectedOption={{ value: mode, label: mode === "new" ? "Create a new resource share" : "Add to an existing resource share" }}
              options={[{ value: "new", label: "Create a new resource share" }, { value: "existing", label: "Add to an existing resource share" }]}
              onChange={({ detail }) => setMode(detail.selectedOption.value)} />
          </FormField>
          {mode === "new" ? (
            <>
              <FormField label="Resource share name"><Input value={name} placeholder="my-share" onChange={({ detail }) => setName(detail.value)} /></FormField>
              <FormField label="Principal account ID — optional" description="Vyomi has no second account to show the invited principal's view from; this records the principal association for real.">
                <Input value={principal} placeholder="999999999999" onChange={({ detail }) => setPrincipal(detail.value)} />
              </FormField>
            </>
          ) : (
            <FormField label="Existing resource share">
              <Select selectedOption={shareArn ? { value: shareArn, label: shareArn } : null} placeholder="Select a resource share"
                options={(shares.data || []).map((s) => ({ value: s.resourceShareArn, label: s.name }))} onChange={({ detail }) => setShareArn(detail.selectedOption.value)} />
            </FormField>
          )}
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

export function ResourceSharingTab({ resourceId, resourceKind, capabilityId, title }) {
  const notify = useNotify();
  const resourceArn = api.ramResourceArn(resourceKind, resourceId);
  const assocs = useAsync(() => api.getResourceShareAssociations("RESOURCE", { resourceArn }), [resourceArn]);
  const [share, setShare] = useState(false);
  const rows = assocs.data || [];

  return (
    <CapabilityContainer id={capabilityId} title={title} counter={`(${rows.length})`}
      actions={<Button variant="primary" onClick={() => setShare(true)}>Share resource</Button>}>
      <Table items={rows} loading={assocs.loading}
        columnDefinitions={[
          { id: "share", header: "Resource share", cell: (a) => a.resourceShareArn },
          { id: "status", header: "Status", cell: (a) => a.status },
          { id: "created", header: "Associated", cell: (a) => a.creationTime },
        ]}
        empty={<Box textAlign="center" color="inherit">Not shared with any other account.</Box>}
        footer={rows.length > 0 && (
          <Button onClick={async () => {
            for (const a of rows) await api.disassociateResourceShare(a.resourceShareArn, [resourceArn], []);
            notify.success("Resource unshared."); assocs.reload();
          }}>Stop sharing</Button>
        )} />
      {share && <ShareResourceModal resourceArn={resourceArn} onDismiss={() => setShare(false)} onShared={() => { setShare(false); assocs.reload(); }} />}
    </CapabilityContainer>
  );
}
