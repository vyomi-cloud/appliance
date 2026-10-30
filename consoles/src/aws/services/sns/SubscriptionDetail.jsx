import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import Tabs from "@cloudscape-design/components/tabs";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Textarea from "@cloudscape-design/components/textarea";
import Checkbox from "@cloudscape-design/components/checkbox";
import Toggle from "@cloudscape-design/components/toggle";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Spinner from "@cloudscape-design/components/spinner";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function SubscriptionDetail({ params, query }) {
  const id = params.id;
  const notify = useNotify();
  const [tab, setTab] = useState(query.tab || "filter-policy");
  const [del, setDel] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [raw, setRaw] = useState(false);
  const [busy, setBusy] = useState(false);
  const s = useAsync(async () => {
    const all = await api.listSubscriptions();
    const sub = all.find((x) => api.subId(x.arn) === id);
    if (!sub) { const e = new Error("Subscription does not exist"); e.code = "NotFound"; e.status = 404; throw e; }
    const attrs = await api.getSubscriptionAttributes(sub.arn);
    return { sub, attrs };
  }, [id]);
  if (s.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (s.error) return <ErrorAlert error={s.error} />;
  const { sub, attrs } = s.data;
  const pending = attrs.PendingConfirmation === "true";

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button iconName="refresh" ariaLabel="Refresh" onClick={s.reload} />
        <Button onClick={() => { setRaw(attrs.RawMessageDelivery === "true"); setEditOpen(true); }}>Edit</Button>
        <Button onClick={() => setDel(true)}>Delete</Button>
      </SpaceBetween>
    }>{`Subscription: ${id}`}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={3} items={[
          ["ARN", sub.arn], ["Endpoint", sub.endpoint], ["Topic", api.topicName(sub.topicArn)],
          ["Subscription Principal", `arn:aws:iam::${attrs.Owner}:root`],
          ["Status", pending ? "Pending confirmation" : "Confirmed"], ["Protocol", sub.protocol],
        ]} />
        <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
          { id: "filter-policy", label: "Subscription filter policy", content: (
            <CapabilityContainer id="sns.subscription.filter-policy" title="Subscription filter policy">
              <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{attrs.FilterPolicy || "No filter policy configured."}</pre></Box>
            </CapabilityContainer>
          ) },
          { id: "redrive-policy", label: "Redrive policy (dead-letter queue)", content: (
            <CapabilityContainer id="sns.subscription.redrive-policy" title="Redrive policy (dead-letter queue)">
              <Box variant="code"><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{attrs.RedrivePolicy || "No redrive policy configured."}</pre></Box>
            </CapabilityContainer>
          ) },
        ]} />
      </SpaceBetween>
      <DeleteModal visible={del} resourceType="subscription" names={[id]} confirmText="delete me" onDismiss={() => setDel(false)}
        onConfirm={async () => { await api.unsubscribe(sub.arn); notify.success("Subscription deleted."); navigate("sns", "subscriptions"); }} />
      <Modal visible={editOpen} onDismiss={() => setEditOpen(false)} header="Edit subscription"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true);
            try { await api.setSubscriptionAttribute(sub.arn, "RawMessageDelivery", raw ? "true" : "false"); notify.success(`Subscription updated.${saveNotice("sns.subscription.raw-delivery")}`); setEditOpen(false); s.reload(); }
            finally { setBusy(false); }
          }}>Save changes</Button>
        </SpaceBetween></Box>}>
        <Checkbox checked={raw} onChange={({ detail }) => setRaw(detail.checked)}>Enable raw message delivery</Checkbox>
      </Modal>
    </ContentLayout>
  );
}
