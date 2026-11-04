/* Marketplace browsers shared by S3 (SaaS spaces) and EC2 (AMI catalog): product table with category filter, details + EULA
 * subscribe flow, and the subscriptions list. Backed by core/marketplace_core.py. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import Modal from "@cloudscape-design/components/modal";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "./ResourceTable.jsx";
import { KeyValue } from "./common.jsx";
import { useAsync } from "../../common/useAsync.js";
import { useNotify } from "../../common/notify.jsx";
import * as mp from "./marketplaceApi.js";

export function ProductBrowser({ entityType, noun, onChanged, testid }) {
  const notify = useNotify();
  const list = useAsync(() => Promise.all([mp.listEntities(entityType), mp.listAgreements()]), [entityType]);
  const [products, agreements] = list.data || [[], []];
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const [eula, setEula] = useState(false);
  const [busy, setBusy] = useState(false);
  const reload = () => { list.reload(); onChanged && onChanged(); };
  const open = async (p) => { setSel(p); setEula(false); setDetail(null); try { setDetail(await mp.describeEntity(p.EntityId)); } catch (e) { notify.error(e); } };
  const agreementOf = (p) => agreements.find((a) => a.ProductId === p.EntityId);
  const act = async (fn, okMsg) => { setBusy(true); try { await fn(); notify.success(okMsg); setSel(null); reload(); } catch (e) { notify.error(e); } finally { setBusy(false); } };
  const ag = sel && agreementOf(sel);
  const d = detail?.Details || {};
  return (
    <>
      <ResourceTable
        resourceName={noun} items={products} loading={list.loading} error={list.error} onRefresh={reload} trackBy="EntityId"
        filterPlaceholder={`Search ${noun.toLowerCase()}`}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (p) => <Button variant="inline-link" onClick={() => open(p)}>{p.Name}</Button> },
          { id: "vendor", header: "Vendor", cell: (p) => p.Vendor },
          { id: "cat", header: "Category", cell: (p) => p.Category },
          { id: "desc", header: "Description", cell: (p) => p.Description },
          { id: "sub", header: "Subscription", cell: (p) => p.Subscribed ? <StatusIndicator type="success">Subscribed</StatusIndicator> : <StatusIndicator type="stopped">Not subscribed</StatusIndicator> },
        ]}
        empty={{ title: `No ${noun.toLowerCase()}` }} />
      <Modal visible={!!sel} onDismiss={() => setSel(null)} size="large" header={sel?.Name || ""}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
          <Button variant="link" onClick={() => setSel(null)}>Close</Button>
          {ag ? <Button loading={busy} onClick={() => act(() => mp.unsubscribe(ag.AgreementId), `Successfully cancelled the subscription to ${sel.Name}.`)}>Cancel subscription</Button>
            : <Button variant="primary" loading={busy} disabled={!eula} onClick={() => act(() => mp.subscribe(sel.EntityId), `Successfully subscribed to ${sel.Name}.`)}>Subscribe</Button>}
        </SpaceBetween></Box>}>
        {sel && <SpaceBetween size="m">
          <KeyValue columns={2} items={[["Vendor", d.Vendor || sel.Vendor], ["Category", d.Category || sel.Category], ["Pricing", d.Pricing || "-"],
            ...(d.Architecture ? [["Architecture", d.Architecture], ["Product code", d.ProductCode]] : [])]} />
          <Box>{d.Description || sel.Description}</Box>
          {d.Operations && <Box variant="code">{d.Operations.join("\n")}</Box>}
          {ag ? <KeyValue columns={2} items={[["Agreement", ag.AgreementId], ["Started", ag.StartTime],
            ...(ag.Space ? [["Endpoint", ag.Space.Endpoint], ["API key", ag.Space.ApiKey]] : []), ...(ag.ImageId ? [["AMI", ag.ImageId]] : [])]} />
            : <Checkbox checked={eula} onChange={({ detail: x }) => setEula(x.checked)} data-testid="mp-eula">I accept the end-user license agreement for {sel.Name}.</Checkbox>}
          {!ag && <Alert type="info">This is a Vyomi simulation: nothing is charged and no third-party service is contacted.</Alert>}
        </SpaceBetween>}
      </Modal>
    </>
  );
}

export function SubscriptionsTable({ onChanged }) {
  const notify = useNotify();
  const list = useAsync(() => mp.listAgreements(), []);
  return (
    <ResourceTable resourceName="Subscriptions" items={list.data || []} loading={list.loading} error={list.error} onRefresh={list.reload} trackBy="AgreementId"
      columns={[
        { id: "p", header: "Product", isRowHeader: true, cell: (a) => a.ProductName },
        { id: "t", header: "Type", cell: (a) => a.ProductType === "SaaSProduct" ? "SaaS space" : "AMI" },
        { id: "id", header: "Agreement ID", cell: (a) => a.AgreementId },
        { id: "r", header: "Endpoint / AMI", cell: (a) => a.Space?.Endpoint || a.ImageId },
        { id: "s", header: "Started", cell: (a) => a.StartTime },
        { id: "x", header: "Actions", cell: (a) => <Button onClick={async () => { try { await mp.unsubscribe(a.AgreementId); notify.success("Subscription cancelled."); list.reload(); onChanged && onChanged(); } catch (e) { notify.error(e); } }}>Cancel</Button> },
      ]}
      empty={{ title: "No subscriptions" }} />
  );
}
