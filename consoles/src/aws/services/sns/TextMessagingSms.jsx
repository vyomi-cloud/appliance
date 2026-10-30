/* Mobile text messaging (SMS) — SMS attributes and the sandbox phone-number workflow are
 * real and stateful; Vyomi has no real carrier/SMPP gateway, so no SMS is ever actually
 * delivered and delivery statistics are not modeled (core/capabilities/aws/sns.json). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Textarea from "@cloudscape-design/components/textarea";
import Select from "@cloudscape-design/components/select";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Box from "@cloudscape-design/components/box";
import Table from "@cloudscape-design/components/table";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { ErrorAlert, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function TextMessagingSms() {
  const notify = useNotify();
  const [publishOpen, setPublishOpen] = useState(false);
  const [phone, setPhone] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={() => setPublishOpen(true)}>Publish text message</Button>
      </SpaceBetween>
    }>Mobile text messaging (SMS)</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Account information" columns={1} items={[["Status", <StatusIndicator type="info">In SMS Sandbox</StatusIndicator>]]} />
        <NotSimulatedContainer title="Delivery statistics (UTC)" feature="SMS delivery statistics" note="Vyomi has no real carrier to deliver SMS through, so delivery-rate statistics aren't modeled." />
        <Preferences />
        <SandboxNumbers />
        <NotSimulatedContainer title="Delivery statistics by country" feature="SMS delivery statistics by country" />
        <OptedOutNumbers />
      </SpaceBetween>
      <Modal visible={publishOpen} onDismiss={() => setPublishOpen(false)} header="Publish text message"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setPublishOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true); setError(null);
            try { await api.publish({ phoneNumber: phone, message }); notify.success(`Published text message to ${phone}.`); setPublishOpen(false); setMessage(""); }
            catch (e) { setError(e); } finally { setBusy(false); }
          }}>Publish message</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Phone number" description="Must be a verified SMS Sandbox destination number."><Input value={phone} placeholder="+15555550100" onChange={({ detail }) => setPhone(detail.value)} ariaLabel="Phone number" /></FormField>
          <FormField label="Message"><Textarea value={message} onChange={({ detail }) => setMessage(detail.value)} ariaLabel="Message" /></FormField>
        </SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}

function Preferences() {
  const notify = useNotify();
  const attrs = useAsync(() => api.getSmsAttributes(), []);
  const [editing, setEditing] = useState(false);
  const [type, setType] = useState("Promotional");
  const [limit, setLimit] = useState("1");
  const [busy, setBusy] = useState(false);
  if (attrs.loading) return null;
  const a = attrs.data || {};
  return (
    <CapabilityContainer id="sns.sms.preferences" title="Text messaging preferences" actions={
      editing ? null : <Button onClick={() => { setType(a.DefaultSMSType || "Promotional"); setLimit(a.MonthlySpendLimit || "1"); setEditing(true); }}>Edit</Button>
    }>
      {editing ? (
        <SpaceBetween size="m">
          <FormField label="Default message type">
            <Select selectedOption={{ label: type, value: type }} onChange={({ detail }) => setType(detail.selectedOption.value)}
              options={["Promotional", "Transactional"].map((v) => ({ label: v, value: v }))} />
          </FormField>
          <FormField label="Account spend limit (USD)"><Input type="number" value={limit} onChange={({ detail }) => setLimit(detail.value)} ariaLabel="Account spend limit" /></FormField>
          <SpaceBetween direction="horizontal" size="xs">
            <Button variant="primary" loading={busy} onClick={async () => {
              setBusy(true);
              try { await api.setSmsAttributes({ DefaultSMSType: type, MonthlySpendLimit: limit }); notify.success(`Preferences updated.${saveNotice("sns.sms.preferences")}`); setEditing(false); attrs.reload(); }
              finally { setBusy(false); }
            }}>Save changes</Button>
            <Button variant="link" onClick={() => setEditing(false)}>Cancel</Button>
          </SpaceBetween>
        </SpaceBetween>
      ) : (
        <KeyValue columns={3} items={[
          ["Default message type", a.DefaultSMSType || "Promotional"], ["Account spend limit", `$${a.MonthlySpendLimit || "1"}`],
          ["Success sample rate", `${a.DeliveryStatusSuccessSamplingRate || "0"}%`],
          ["IAM role for logging delivery status in CloudWatch Logs", a.DeliveryStatusIAMRole || "-"],
          ["Amazon S3 bucket name for usage reports", a.UsageReportS3Bucket || "-"], ["Default sender ID", a.DefaultSenderID || "-"],
        ]} />
      )}
    </CapabilityContainer>
  );
}

function SandboxNumbers() {
  const notify = useNotify();
  const s = useAsync(() => api.listSmsSandboxPhoneNumbers(), []);
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  return (
    <>
      <ResourceTable
        resourceName="Sandbox destination phone numbers"
        items={s.data || []}
        trackBy="phone"
        loading={s.loading}
        error={s.error}
        onRefresh={s.reload}
        selectionType="single"
        selectedItems={sel}
        onSelectionChange={setSel}
        columns={[
          { id: "phone", header: "Verified phone number", isRowHeader: true, cell: (x) => x.phone },
          { id: "status", header: "Verification status", cell: (x) => <StatusIndicator type={x.status === "Verified" ? "success" : "pending"}>{x.status}</StatusIndicator> },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button disabled={sel.length !== 1 || sel[0].status === "Verified"} onClick={() => { setOtp(""); setVerifyOpen(true); }}>Verify phone number</Button>
            <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete phone number</Button>
            <Button variant="primary" onClick={() => { setPhone(""); setAddOpen(true); }}>Add phone number</Button>
          </SpaceBetween>
        }
        empty={{ title: "No phone numbers added", action: <Button onClick={() => setAddOpen(true)}>Add phone number</Button> }}
      />
      <DeleteModal visible={del} resourceType="phone number" names={sel.map((x) => x.phone)} confirmText="delete me" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const x of sel) await api.deleteSmsSandboxPhoneNumber(x.phone); notify.success("Phone number deleted."); setSel([]); s.reload(); }} />
      <Modal visible={addOpen} onDismiss={() => setAddOpen(false)} header="Add phone number"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true); setError(null);
            try { await api.createSmsSandboxPhoneNumber(phone); notify.success(`"${phone}" added — a verification code was generated.${saveNotice("sns.sms.sandbox")}`); setAddOpen(false); s.reload(); }
            catch (e) { setError(e); } finally { setBusy(false); }
          }}>Send code</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <FormField label="Phone number"><Input value={phone} placeholder="+15555550100" onChange={({ detail }) => setPhone(detail.value)} ariaLabel="Phone number" /></FormField>
        </SpaceBetween>
      </Modal>
      <Modal visible={verifyOpen} onDismiss={() => setVerifyOpen(false)} header="Verify phone number"
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setVerifyOpen(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={async () => {
            setBusy(true); setError(null);
            try { await api.verifySmsSandboxPhoneNumber(sel[0].phone, otp); notify.success("Phone number verified."); setVerifyOpen(false); s.reload(); }
            catch (e) { setError(e); } finally { setBusy(false); }
          }}>Verify</Button>
        </SpaceBetween></Box>}>
        <SpaceBetween size="m">
          {error && <ErrorAlert error={error} />}
          <NotSimulatedContainer title="Verification code delivery" feature="SMS OTP delivery" note="Vyomi can't send a real text; it has no carrier to reach the phone with the code." />
          <FormField label="Verification code"><Input value={otp} onChange={({ detail }) => setOtp(detail.value)} ariaLabel="Verification code" /></FormField>
        </SpaceBetween>
      </Modal>
    </>
  );
}

function OptedOutNumbers() {
  const notify = useNotify();
  const o = useAsync(() => api.listPhoneNumbersOptedOut(), []);
  const [sel, setSel] = useState([]);
  const rows = (o.data || []).map((n) => ({ number: n }));
  return (
    <Table
      variant="container"
      items={rows}
      loading={o.loading}
      trackBy="number"
      selectionType="single"
      selectedItems={sel}
      onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
      header={<Header variant="h2" counter={`(${rows.length})`} actions={
        <Button disabled={sel.length !== 1} onClick={async () => { await api.optInPhoneNumber(sel[0].number); notify.success(`"${sel[0].number}" opted back in.`); setSel([]); o.reload(); }}>Opt in</Button>
      }>Opted-out phone numbers</Header>}
      columnDefinitions={[{ id: "number", header: "Number", cell: (x) => x.number }]}
      empty={<Box textAlign="center" color="inherit"><b>No numbers have been opted out.</b></Box>}
    />
  );
}
