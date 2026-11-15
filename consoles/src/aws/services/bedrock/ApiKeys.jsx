/* Bedrock > API keys (captures 006): How it works + Short-term / Long-term tabs. Long-term keys are IAM service-specific
 * credentials for bedrock.amazonaws.com (core/iam_core), created through the real IAM Query API. */
import { useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ExpandableSection from "@cloudscape-design/components/expandable-section";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import Modal from "@cloudscape-design/components/modal";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import Tabs from "@cloudscape-design/components/tabs";
import Input from "@cloudscape-design/components/input";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

const EXP = [{ label: "1 day", value: "1" }, { label: "30 days", value: "30" }, { label: "90 days", value: "90" }, { label: "1 year", value: "365" }, { label: "Never expires", value: "" }];
const fmt = (s) => (s ? new Date(s).toLocaleString() : "Never");

function KeyModal({ title, secret, user, onClose }) {
  return (
    <Modal visible onDismiss={onClose} header={title} footer={<Box float="right"><Button variant="primary" onClick={onClose}>Close</Button></Box>}>
      <SpaceBetween size="s">
        <Alert type="warning">This is the only time you can view this API key. Copy it now and store it securely.</Alert>
        {user && <FormField label="IAM user"><Box>{user}</Box></FormField>}
        <FormField label="API key"><Input readOnly value={secret} data-testid="api-key-secret" /></FormField>
        <Box variant="code" color="text-body-secondary">export AWS_BEARER_TOKEN_BEDROCK="{"<API key>"}"</Box>
      </SpaceBetween>
    </Modal>
  );
}

function Generate({ onDone, onClose }) {
  const [exp, setExp] = useState(EXP[2]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const go = async () => { setBusy(true); try { onDone(await api.createApiKey(exp.value)); } catch (e) { setErr(e); setBusy(false); } };
  return (
    <Modal visible onDismiss={onClose} header="Generate long-term API keys" footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={go}>Generate</Button></SpaceBetween></Box>}>
      <SpaceBetween size="m">
        <Alert type="info">A new IAM user with the AmazonBedrockLimitedAccess policy is created to own this key.</Alert>
        <FormField label="API key expiration" description="After this period the key stops working."><Select selectedOption={exp} onChange={({ detail }) => setExp(detail.selectedOption)} options={EXP} ariaLabel="Expiration" /></FormField>
        {err && <Alert type="error" header={err.code}>{err.message}</Alert>}
      </SpaceBetween>
    </Modal>
  );
}

export default function ApiKeys() {
  const keys = useAsync(() => api.listApiKeys(), []);
  const [tab, setTab] = useState("short");
  const [gen, setGen] = useState(false);
  const [shown, setShown] = useState(null);
  const [sel, setSel] = useState([]);
  const [err, setErr] = useState(null);
  const act = async (fn) => { setErr(null); try { await fn(); setSel([]); keys.reload(); } catch (e) { setErr(e); } };
  const short = () => {
    const tok = "bedrock-api-key-" + btoa(`bedrock.amazonaws.com/?Action=CallWithBearerToken&X-Amz-Expires=43200&X-Amz-Date=${new Date().toISOString()}&Version=1`);
    setShown({ title: "Short-term API key", secret: tok });
  };
  const c = sel[0];
  return (
    <SpaceBetween size="l">
      <Header variant="h1">API keys</Header>
      <Container header={<Header variant="h2">How it works</Header>}>
        <SpaceBetween size="m">
          <Box>To make API requests programmatically, you must authenticate with AWS credentials. Amazon Bedrock lets you generate an Amazon Bedrock API key that you can use as credentials to make Amazon Bedrock API requests. You can integrate the key into your set up for it to be recognized automatically.</Box>
          <ColumnLayout columns={2} borders="vertical">
            <SpaceBetween size="s"><Box variant="h4">Short-term API keys</Box><Box>A short-term Amazon Bedrock API key expires after your console session expires (12 hours by default). We recommend that you use short-term keys for setups that require a higher level of security.</Box><Link onFollow={short}>Generate short-term API keys</Link></SpaceBetween>
            <SpaceBetween size="s"><Box variant="h4">Long-term API keys</Box><Box>A long-term Amazon Bedrock API key can be set to last longer than 12 hours. We strongly recommend using long-term keys only for exploratory purposes to avoid security risks in production.</Box><Link onFollow={() => { setTab("long"); setGen(true); }}>Generate long-term API keys</Link></SpaceBetween>
          </ColumnLayout>
        </SpaceBetween>
      </Container>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "short", label: "Short-term API keys", content: (
          <Container header={<Header variant="h2" description="These API keys provide temporary access that automatically expires when your current console session, which can last up to 12 hours. Each API key generated inherits the permissions of your current console session. Make sure that your permissions include access to Amazon Bedrock actions. The AmazonBedrockLimitedAccess policy includes these permissions.">Generate short-term API keys</Header>}>
            <Button variant="primary" onClick={short}>Generate short-term API keys</Button>
          </Container>) },
        { id: "long", label: "Long-term API keys", content: (
          <ResourceTable variant="container" resourceName="Long-term API keys" items={keys.data || []} loading={keys.loading} error={keys.error} onRefresh={keys.reload} trackBy="id" selectionType="single" selectedItems={sel} onSelectionChange={setSel}
            empty={{ title: "No long-term API keys", action: <Button onClick={() => setGen(true)}>Generate long-term API keys</Button> }}
            actions={<SpaceBetween direction="horizontal" size="xs">
              <ButtonDropdown disabled={!c} items={[{ id: "toggle", text: c?.status === "Active" ? "Deactivate" : "Activate" }, { id: "reset", text: "Reset key" }, { id: "delete", text: "Delete" }]}
                onItemClick={({ detail }) => act(async () => {
                  if (detail.id === "toggle") await api.setApiKeyStatus(c, c.status === "Active" ? "Inactive" : "Active");
                  else if (detail.id === "reset") setShown({ title: "Reset API key", secret: await api.resetApiKey(c), user: c.user });
                  else await api.deleteApiKey(c);
                })}>Actions</ButtonDropdown>
              <Button variant="primary" onClick={() => setGen(true)}>Generate long-term API keys</Button></SpaceBetween>}
            columns={[
              { id: "name", header: "Name", isRowHeader: true, sortingField: "user", cell: (k) => k.user },
              { id: "status", header: "Status", sortingField: "status", cell: (k) => <StatusIndicator type={k.status === "Active" ? "success" : "stopped"}>{k.status}</StatusIndicator> },
              { id: "exp", header: "Expiration date", sortingField: "expires", cell: (k) => fmt(k.expires) },
              { id: "created", header: "Creation date", sortingField: "created", cell: (k) => fmt(k.created) },
            ]} />) },
      ]} />
      {err && <Alert type="error" header={err.code}>{err.message}</Alert>}
      {gen && <Generate onClose={() => setGen(false)} onDone={(k) => { setGen(false); keys.reload(); setShown({ title: "Long-term API key generated", secret: k.key, user: k.user }); }} />}
      {shown && <KeyModal {...shown} onClose={() => setShown(null)} />}
    </SpaceBetween>
  );
}
