import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Box from "@cloudscape-design/components/box";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Subscriptions() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const { data = [], loading, error: loadError, reload } = useAsync(async () => (await api.listSubscriptions())
    .map((s) => ({ ...s, id: s.pending ? "PendingConfirmation" : api.subId(s.arn), key: `${s.topicArn}|${s.protocol}|${s.endpoint}`, topic: api.topicName(s.topicArn) })), []);

  return (
    <ContentLayout header={<Header variant="h1" counter={`(${data.length})`}>Subscriptions</Header>}>
      <ResourceTable
        resourceName="Subscriptions"
        items={data}
        trackBy="key"
        loading={loading}
        error={loadError}
        onRefresh={reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Search"
        columns={[
          { id: "id", header: "ID", isRowHeader: true, cell: (x) => x.pending ? x.id : <Link href={href("sns", "subscriptions", x.id)} onFollow={follow}>{x.id}</Link> },
          { id: "endpoint", header: "Endpoint", cell: (x) => x.endpoint },
          { id: "status", header: "Status", cell: (x) => <StatusIndicator type={x.pending ? "pending" : "success"}>{x.pending ? "Pending confirmation" : "Confirmed"}</StatusIndicator> },
          { id: "protocol", header: "Protocol", cell: (x) => x.protocol },
          { id: "topic", header: "Topic", cell: (x) => <Link href={href("sns", "topics", x.topic)} onFollow={follow}>{x.topic}</Link> },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1 || sel[0].pending} href={sel.length === 1 && !sel[0].pending ? href("sns", "subscriptions", sel[0].id) : undefined} onFollow={follow}>Edit</Button>
            <Button disabled={!sel.length || sel.some((x) => x.pending)} onClick={() => setDel(true)}>Delete</Button>
            <Button disabled={sel.length !== 1} onClick={async () => { try { await api.subscribe(sel[0].topicArn, sel[0].protocol, sel[0].endpoint); notify.success("Requested a new confirmation message."); } catch (e) { notify.error(e); } }}>Request confirmation</Button>
            <Button disabled={sel.length !== 1} onClick={() => setConfirmOpen(true)}>Confirm subscription</Button>
            <Button variant="primary" href={href("sns", "create-subscription")} onFollow={follow}>Create subscription</Button>
          </SpaceBetween>
        }
        empty={{ title: "No subscriptions found", action: <Button href={href("sns", "create-subscription")} onFollow={follow}>Create subscription</Button> }}
      />
      <DeleteModal visible={del} resourceType="subscription" names={sel.map((x) => x.id)} confirmText="delete me" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const x of sel) await api.unsubscribe(x.arn); notify.success("Subscription deleted."); setSel([]); reload(); }} />
      <Modal visible={confirmOpen} onDismiss={() => setConfirmOpen(false)} header="Confirm subscription"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true); setError(null);
            try { await api.confirmSubscription(sel[0].topicArn, token); notify.success("Subscription confirmed."); setConfirmOpen(false); setToken(""); reload(); }
            catch (e) { setError(e); } finally { setBusy(false); }
          }}>Confirm subscription</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Confirmation token" description="The Token from the subscription confirmation message sent to the endpoint.">
            <Input value={token} onChange={({ detail }) => setToken(detail.value)} ariaLabel="Confirmation token" />
          </FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}
