/* EventBridge partner event sources (sweep AWS-13): customer view of SaaS partner sources + Vyomi's own SaaS-partner
 * simulators that play the partner role (CreatePartnerEventSource / PutPartnerEvents). Real wire ops, no static data. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Table from "@cloudscape-design/components/table";
import { ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

// Vyomi's built-in SaaS-partner simulators (the partner role; the account is the customer).
const PARTNERS = [
  { id: "vyomi-shop", label: "Vyomi Shop", stream: "orders", detailType: "Order Placed", sample: () => ({ orderId: Math.floor(Math.random() * 9000 + 1000), total: 42.5, currency: "USD" }) },
  { id: "vyomi-auth", label: "Vyomi Auth", stream: "logins", detailType: "User Signed In", sample: () => ({ userId: "u-" + Math.floor(Math.random() * 900 + 100), method: "password" }) },
  { id: "vyomi-billing", label: "Vyomi Billing", stream: "invoices", detailType: "Invoice Paid", sample: () => ({ invoice: "INV-" + Math.floor(Math.random() * 9000 + 1000), amount: 120 }) },
];
const ACCOUNT = "123456789012";
const srcName = (p) => `aws.partner/vyomi.cloud/${p.id}/${p.stream}`;

const state = (s) => <StatusIndicator type={s === "ACTIVE" ? "success" : s === "PENDING" ? "pending" : "stopped"}>{s}</StatusIndicator>;

export default function PartnerSources() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [busy, setBusy] = useState("");
  const { data = [], loading, error, reload } = useAsync(() => api.listEventSources(), []);
  const byName = Object.fromEntries(data.map((s) => [s.Name, s]));
  const run = async (key, fn, ok) => { setBusy(key); try { await fn(); if (ok) notify.success(ok); reload(); } catch (e) { notify.error(e); } finally { setBusy(""); } };
  const cur = sel[0];

  return (
    <ContentLayout header={<Header variant="h1" description="Events from SaaS partners arrive as partner event sources. Associate a source with an event bus to start receiving its events.">Partner event sources</Header>}>
      <SpaceBetween size="l">
        <Table
          header={<Header counter={`(${data.length})`} actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Button onClick={reload} iconName="refresh" ariaLabel="Refresh" />
              <Button disabled={!cur || cur.State !== "PENDING"} loading={busy === "assoc"} onClick={() => run("assoc", () => api.createEventBus({ Name: cur.Name, EventSourceName: cur.Name }), `Associated ${cur.Name} with an event bus of the same name.`)}>Associate with event bus</Button>
              <Button disabled={!cur || cur.State !== "ACTIVE"} onClick={() => run("deact", () => api.deactivateEventSource(cur.Name), "Event source deactivated.")}>Deactivate</Button>
              <Button disabled={!cur || cur.State !== "PENDING" || !cur.Name} onClick={() => run("act", () => api.activateEventSource(cur.Name), "Event source activated.")}>Activate</Button>
            </SpaceBetween>}>Partner event sources</Header>}
          items={data} loading={loading} loadingText="Loading partner event sources" trackBy="Name"
          selectionType="single" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          columnDefinitions={[
            { id: "name", header: "Name", cell: (s) => s.Name, isRowHeader: true },
            { id: "partner", header: "Partner", cell: (s) => s.CreatedBy },
            { id: "state", header: "Status", cell: (s) => state(s.State) },
            { id: "created", header: "Created", cell: (s) => fmtDate(s.CreationTime) },
            { id: "exp", header: "Expires", cell: (s) => (s.State === "PENDING" ? fmtDate(s.ExpirationTime) : "-") },
          ]}
          empty={<Box textAlign="center" color="inherit"><b>No partner event sources</b><Box variant="p" color="inherit">Use a Vyomi SaaS partner below to create one.</Box></Box>}
        />
        {error && <ErrorAlert error={error} />}
        <Container header={<Header variant="h2" description="Vyomi's own SaaS-partner simulators play the partner: they create a partner event source for your account and send real partner events once you associate the source with a bus.">Vyomi SaaS partners</Header>}>
          <Table
            variant="embedded" items={PARTNERS} trackBy="id"
            columnDefinitions={[
              { id: "p", header: "Partner", cell: (p) => p.label, isRowHeader: true },
              { id: "n", header: "Event source", cell: (p) => srcName(p) },
              { id: "s", header: "Status", cell: (p) => (byName[srcName(p)] ? state(byName[srcName(p)].State) : "Not set up") },
              { id: "a", header: "Actions", cell: (p) => {
                const s = byName[srcName(p)];
                return (
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button disabled={!!s} loading={busy === "c" + p.id} onClick={() => run("c" + p.id, () => api.createPartnerEventSource(srcName(p), ACCOUNT), `${p.label} created a pending partner event source for your account.`)}>Set up source</Button>
                    <Button disabled={!s || s.State !== "ACTIVE"} loading={busy === "e" + p.id} onClick={() => run("e" + p.id, async () => {
                      const r = await api.putPartnerEvents([{ Source: srcName(p), DetailType: p.detailType, Detail: JSON.stringify(p.sample()) }]);
                      if (r.FailedEntryCount) throw new Error(r.Entries[0].ErrorMessage);
                    }, `${p.label} sent a "${p.detailType}" event to the ${srcName(p)} bus.`)}>Send test event</Button>
                    <Button disabled={!s} onClick={() => run("d" + p.id, () => api.deletePartnerEventSource(srcName(p), ACCOUNT), "Partner event source deleted.")}>Remove source</Button>
                  </SpaceBetween>);
              } },
            ]}
          />
        </Container>
      </SpaceBetween>
    </ContentLayout>
  );
}
