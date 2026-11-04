/* EC2 console → Load Balancing → Trust stores (ALB mutual TLS). Native wire: shares
 * core/elbv2_core.py's "elasticloadbalancing" Query-protocol engine. CreateTrustStore
 * really reads the referenced CA bundle from Vyomi's own S3 and validates it's a
 * well-formed PEM bundle — see ec2.trust-stores. */
import { useState } from "react";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Form from "@cloudscape-design/components/form";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { href, follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

export function TrustStores() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const t = useAsync(() => api.describeTrustStores(), []);
  const rows = t.data || [];

  return (
    <ContentLayout header={<Header variant="h1">Trust stores</Header>}>
      <ResourceTable
        resourceName="Trust Stores"
        items={rows}
        loading={t.loading}
        error={t.error}
        onRefresh={t.reload}
        trackBy="TrustStoreArn"
        selectionType="multi"
        selectedItems={sel}
        onSelectionChange={setSel}
        filterPlaceholder="Find trust stores"
        empty={{ title: "No trust stores", subtitle: "You don't have any trust stores configured." }}
        columns={[
          { id: "name", header: "Name", isRowHeader: true, cell: (s) => s.Name },
          { id: "status", header: "Status", cell: (s) => <StatusIndicator type={s.Status === "ACTIVE" ? "success" : "pending"}>{s.Status}</StatusIndicator> },
          { id: "certs", header: "CA certificates", cell: (s) => s.NumberOfCaCertificates },
          { id: "revoked", header: "Revoked entries", cell: (s) => s.TotalRevokedEntries },
          { id: "bundle", header: "CA bundle", cell: (s) => `s3://${s.CaCertificatesBundleS3Bucket}/${s.CaCertificatesBundleS3Key}` },
        ]}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <ButtonDropdown disabled={!sel.length} items={[{ id: "delete", text: "Delete" }]} onItemClick={() => setDel(true)}>Actions</ButtonDropdown>
            <Button variant="primary" href={href("ec2", "create-trust-store")} onFollow={follow}>Create trust store</Button>
          </SpaceBetween>
        }
      />
      <DeleteModal visible={del} resourceType="trust store" names={sel.map((s) => s.Name)} onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const s of sel) await api.deleteTrustStore(s.TrustStoreArn); notify.success(`${sel.length} trust store(s) deleted.`); setSel([]); t.reload(); }} />
    </ContentLayout>
  );
}

export function CreateTrustStore() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [bucket, setBucket] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const ts = await api.createTrustStore({ Name: name, CaCertificatesBundleS3Bucket: bucket, CaCertificatesBundleS3Key: key });
      notify.success(`Trust store "${name}" created (${ts.NumberOfCaCertificates} CA certificate(s) parsed from the bundle).`);
      navigate("ec2", "trust-stores");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create trust store</Header>}>
      <Form errorText={error && <ErrorAlert error={error} />} actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button formAction="none" href={href("ec2", "trust-stores")} onFollow={follow}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name || !bucket || !key} onClick={submit}>Create trust store</Button>
        </SpaceBetween>
      }>
        <Container header={<Header variant="h2">Trust store configuration</Header>}>
          <SpaceBetween size="l">
            <FormField label="Trust store name" constraintText="Up to 32 alphanumeric characters and hyphens.">
              <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="my-trust-store" ariaLabel="Trust store name" />
            </FormField>
            <FormField label="CA certificates bundle — S3 bucket" description="A PEM-formatted CA bundle object in one of Vyomi's own S3 buckets.">
              <Input value={bucket} onChange={({ detail }) => setBucket(detail.value)} placeholder="my-bucket" ariaLabel="CA bundle S3 bucket" />
            </FormField>
            <FormField label="CA certificates bundle — S3 key">
              <Input value={key} onChange={({ detail }) => setKey(detail.value)} placeholder="ca-bundle.pem" ariaLabel="CA bundle S3 key" />
            </FormField>
          </SpaceBetween>
        </Container>
      </Form>
    </ContentLayout>
  );
}
