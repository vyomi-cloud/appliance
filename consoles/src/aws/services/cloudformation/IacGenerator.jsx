/* IaC generator — StartResourceScan really scans the live S3/DynamoDB/SNS/SQS/IAM/Logs
 * stores and CreateGeneratedTemplate builds a real template from the selected resources'
 * live properties (core/cloudformation_core.py: _scan_resources/_create_generated_template,
 * core/capabilities/aws/cloudformation.json: aws.cloudformation.iac-generator). Scanning
 * across every AWS resource type via Resource Explorer is the declared, narrower gap. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Container from "@cloudscape-design/components/container";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Table from "@cloudscape-design/components/table";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { KeyValue, ErrorAlert, fmtDate } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import * as api from "./api.js";

const idText = (id) => Object.entries(id || {}).map(([k, v]) => `${k}=${v}`).join(", ");

function CreateTemplateModal({ visible, onDismiss, onDone, scanResources }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [sel, setSel] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const close = () => { setName(""); setSel([]); setError(null); onDismiss(); };
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      await api.createGeneratedTemplate(name, sel.map((r) => ({ ResourceType: r.ResourceType, Identifier: r.Identifier })));
      notify.success(`Template "${name}" generated.`);
      close(); onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  return (
    <Modal visible={visible} onDismiss={close} size="large" header="Create template"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={close}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!name || !sel.length} onClick={submit}>Create template</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        {error && <ErrorAlert error={error} />}
        <FormField label="Template name"><Input value={name} onChange={({ detail }) => setName(detail.value)} ariaLabel="Template name" /></FormField>
        <FormField label="Resources" description="Resources found by the most recent scan.">
          <Table
            items={scanResources}
            trackBy={(r) => `${r.ResourceType}:${idText(r.Identifier)}`}
            selectionType="multi"
            selectedItems={sel}
            onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "t", header: "Resource type", cell: (r) => r.ResourceType },
              { id: "i", header: "Identifier", cell: (r) => idText(r.Identifier) },
              { id: "m", header: "Managed by stack", cell: (r) => (r.ManagedByStack ? "Yes" : "No") },
            ]}
            empty="No scanned resources yet — start a scan first."
          />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

export default function IacGenerator() {
  const notify = useNotify();
  const [tabId, setTabId] = useState("scan-summary");
  const [create, setCreate] = useState(false);
  const [tplSel, setTplSel] = useState([]);
  const [scanning, setScanning] = useState(false);
  const scans = useAsync(() => api.listResourceScans(), []);
  const latest = scans.data?.[0];
  const scanDetail = useAsync(() => (latest ? api.describeResourceScan(latest.ResourceScanId) : Promise.resolve(null)), [latest?.ResourceScanId]);
  const scanResources = useAsync(() => (latest ? api.listResourceScanResources(latest.ResourceScanId) : Promise.resolve([])), [latest?.ResourceScanId]);
  const templates = useAsync(() => api.listGeneratedTemplates(), []);

  const startScan = async () => {
    setScanning(true);
    try { await api.startResourceScan(); notify.success("Resource scan started."); setTabId("scan-summary"); await scans.reload(); }
    catch (e) { notify.error(e); } finally { setScanning(false); }
  };
  const openCreate = () => { setTabId("scan-summary"); setCreate(true); };
  const onTemplateCreated = async () => { setTabId("templates"); await templates.reload(); };

  return (
    <ContentLayout header={<Header variant="h1">IaC generator</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">How it works</Header>}>
          <SpaceBetween size="s">
            <Box variant="p">Scan this account's S3 buckets, DynamoDB tables, SNS topics, SQS queues, IAM roles and CloudWatch Logs log groups, then generate a CloudFormation template from the resources you select.</Box>
            <SpaceBetween direction="horizontal" size="xs">
              <Button loading={scanning} onClick={startScan}>Start a new scan</Button>
              <Button disabled={!latest} onClick={openCreate}>Create template</Button>
              <Button onClick={() => setTabId("templates")}>View templates</Button>
            </SpaceBetween>
          </SpaceBetween>
        </Container>
        <Tabs activeTabId={tabId} onChange={({ detail }) => setTabId(detail.activeTabId)} tabs={[
          { id: "scan-summary", label: "Scan summary", content: (
            <SpaceBetween size="l">
              <KeyValue title="Scans" actions={<Button loading={scanning} onClick={startScan}>Start a new scan</Button>} columns={4} items={[
                ["Last completed scan", latest ? fmtDate(latest.EndTime) : "-"],
                ["Days until expiry", latest ? Math.max(0, 30 - Math.floor((Date.now() - new Date(latest.StartTime)) / 86400000)) : "-"],
                ["Last attempted scan", latest ? fmtDate(latest.StartTime) : "-"],
                ["Resources scanned", scanDetail.data?.ResourcesScanned ?? (latest ? "-" : "0")],
                ["Scan status", latest ? latest.Status : "No scans yet"],
                ["Selected scan ID (active)", latest ? latest.ResourceScanId : "-"],
                ["Scan type", latest ? "Full" : "-"],
              ]} />
              <ResourceTable
                variant="container"
                resourceName="Scanned resources breakdown"
                items={scanResources.data || []}
                loading={scanResources.loading}
                error={scanResources.error}
                onRefresh={scanResources.reload}
                trackBy={(r) => `${r.ResourceType}:${idText(r.Identifier)}`}
                filterPlaceholder="Find scanned resources"
                columns={[
                  { id: "t", header: "Resource type", isRowHeader: true, cell: (r) => r.ResourceType },
                  { id: "i", header: "Identifier", cell: (r) => idText(r.Identifier) },
                  { id: "m", header: "Managed by stack", cell: (r) => (r.ManagedByStack ? "Yes" : "No") },
                ]}
                empty={{ title: "No scanned resources", subtitle: "Start a scan to see this account's resources.", action: <Button onClick={startScan}>Start a new scan</Button> }}
              />
            </SpaceBetween>
          ) },
          { id: "templates", label: "Templates", content: (
            <ResourceTable
              variant="container"
              resourceName="Templates"
              items={templates.data || []}
              loading={templates.loading}
              error={templates.error}
              onRefresh={templates.reload}
              trackBy="GeneratedTemplateName"
              selectionType="single"
              selectedItems={tplSel}
              onSelectionChange={setTplSel}
              columns={[
                { id: "n", header: "Template name", isRowHeader: true, cell: (t) => t.GeneratedTemplateName },
                { id: "s", header: "Template status", cell: (t) => t.Status },
                { id: "c", header: "Creation time", cell: (t) => fmtDate(t.CreationTime) },
                { id: "u", header: "Updated time", cell: (t) => fmtDate(t.LastUpdatedTime) },
                { id: "r", header: "Resources", cell: (t) => t.NumberOfResources },
              ]}
              actions={<SpaceBetween direction="horizontal" size="xs">
                <ButtonDropdown disabled={tplSel.length !== 1} items={[{ id: "delete", text: "Delete" }]}
                  onItemClick={async ({ detail }) => {
                    if (detail.id === "delete") {
                      try { await api.deleteGeneratedTemplate(tplSel[0].GeneratedTemplateName); notify.success(`Template "${tplSel[0].GeneratedTemplateName}" deleted.`); setTplSel([]); templates.reload(); }
                      catch (e) { notify.error(e); }
                    }
                  }}>Actions</ButtonDropdown>
                <Button variant="primary" disabled={!latest} onClick={() => setCreate(true)}>Create template</Button>
              </SpaceBetween>}
              empty={{ title: "No templates", subtitle: "Create a template from a resource scan.", action: <Button disabled={!latest} onClick={() => setCreate(true)}>Create template</Button> }}
            />
          ) },
        ]} />
      </SpaceBetween>
      <CreateTemplateModal visible={create} onDismiss={() => setCreate(false)} onDone={onTemplateCreated} scanResources={scanResources.data || []} />
    </ContentLayout>
  );
}
