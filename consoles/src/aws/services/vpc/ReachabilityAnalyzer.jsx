/* Reachability Analyzer — Network Insights paths + analyses over the native EC2 Query
 * wire (api.js: CreateNetworkInsightsPath / StartNetworkInsightsAnalysis / ...), answered
 * by the shared netsim evaluator core/vpc_core.py already runs for AnalyzeReachability.
 * See core/capabilities/aws/vpc.json#aws.vpc.reachability-analyzer for what the explanation
 * codes mean and what isn't a path component (transit gateways, VPN, endpoints, load balancers).
 * Network Access Analyzer (a separate, finding-based engine) stays honest: HonestPages.jsx. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import Link from "@cloudscape-design/components/link";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import Spinner from "@cloudscape-design/components/spinner";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert, KeyValue } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

const PROTOCOLS = ["tcp", "udp"];

export function ReachabilityAnalyzer() {
  const notify = useNotify();
  const t = useAsync(() => api.describeNetworkInsightsPaths(), []);
  const rows = t.data || [];
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [create, setCreate] = useState(false);
  const [busy, setBusy] = useState(false);

  const runAnalysis = async () => {
    setBusy(true);
    try {
      await api.startNetworkInsightsAnalysis(sel[0].NetworkInsightsPathId);
      notify.success(`Analysis started for ${sel[0].NetworkInsightsPathId}.`);
      navigate("vpc", "reachability-analyzer", sel[0].NetworkInsightsPathId);
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Reachability Analyzer</Header>}>
      <CapabilityContainer id="aws.vpc.reachability-analyzer" title="Network Insights paths" counter={`(${rows.length})`}
        actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button onClick={t.reload}>Refresh</Button>
            <ButtonDropdown disabled={!sel.length} items={[
              { id: "run", text: "Run reachability analysis", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete path" },
            ]} onItemClick={({ detail }) => { if (detail.id === "run") runAnalysis(); else if (detail.id === "delete") setDel(true); }}>Actions</ButtonDropdown>
            <Button variant="primary" loading={busy} onClick={() => setCreate(true)}>Create and analyze path</Button>
          </SpaceBetween>
        }>
        <Table
          variant="embedded"
          items={rows}
          loading={t.loading}
          selectionType="multi"
          selectedItems={sel}
          onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
          trackBy="NetworkInsightsPathId"
          filter={<Input type="search" placeholder="Search" />}
          columnDefinitions={[
            { id: "id", header: "Network Insights Path ID", cell: (p) => <Link href={href("vpc", "reachability-analyzer", p.NetworkInsightsPathId)} onFollow={follow}>{p.NetworkInsightsPathId}</Link> },
            { id: "source", header: "Source", cell: (p) => p.Source },
            { id: "destination", header: "Destination", cell: (p) => p.Destination || p.DestinationIp || "-" },
            { id: "protocol", header: "Protocol", cell: (p) => p.Protocol.toUpperCase() },
            { id: "port", header: "Destination port", cell: (p) => p.DestinationPort ?? "-" },
            { id: "created", header: "Created", cell: (p) => p.CreatedDate },
          ]}
          empty={<Box textAlign="center"><b>No paths found</b><Box padding={{ top: "s" }}><Button onClick={() => setCreate(true)}>Create and analyze path</Button></Box></Box>}
        />
      </CapabilityContainer>
      <DeleteModal visible={del} resourceType="Network Insights path" names={sel.map((p) => p.NetworkInsightsPathId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => {
          for (const p of sel) {
            for (const a of await api.describeNetworkInsightsAnalyses(p.NetworkInsightsPathId)) await api.deleteNetworkInsightsAnalysis(a.NetworkInsightsAnalysisId);
            await api.deleteNetworkInsightsPath(p.NetworkInsightsPathId);
          }
          notify.success(`${sel.length} path(s) deleted.`); setSel([]); t.reload();
        }} />
      {create && <CreatePathModal onDismiss={() => setCreate(false)} onCreated={(id) => { setCreate(false); navigate("vpc", "reachability-analyzer", id); }} />}
    </ContentLayout>
  );
}

function CreatePathModal({ onDismiss, onCreated }) {
  const notify = useNotify();
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState("");
  const [protocol, setProtocol] = useState("tcp");
  const [port, setPort] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const p = await api.createNetworkInsightsPath(source, destination, protocol, port ? Number(port) : undefined);
      await api.startNetworkInsightsAnalysis(p.NetworkInsightsPathId);
      notify.success(`Path "${p.NetworkInsightsPathId}" created and analyzed.`);
      onCreated(p.NetworkInsightsPathId);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <Modal visible onDismiss={onDismiss} size="large" header="Create and analyze path"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button formAction="none" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!source || !destination} onClick={submit}>Create and analyze path</Button>
      </SpaceBetween></Box>}>
      <Form errorText={error && <ErrorAlert error={error} />}>
        <SpaceBetween size="l">
          <FormField label="Source" description="An instance ID, network interface ID or internet gateway ID.">
            <Input value={source} onChange={({ detail }) => setSource(detail.value)} placeholder="i-0123456789abcdef0" />
          </FormField>
          <FormField label="Destination" description="An instance ID, network interface ID or internet gateway ID.">
            <Input value={destination} onChange={({ detail }) => setDestination(detail.value)} placeholder="i-0123456789abcdef0" />
          </FormField>
          <FormField label="Protocol">
            <Select selectedOption={{ value: protocol, label: protocol.toUpperCase() }}
              options={PROTOCOLS.map((p) => ({ value: p, label: p.toUpperCase() }))}
              onChange={({ detail }) => setProtocol(detail.selectedOption.value)} />
          </FormField>
          <FormField label="Destination port — optional"><Input value={port} onChange={({ detail }) => setPort(detail.value)} placeholder="443" /></FormField>
        </SpaceBetween>
      </Form>
    </Modal>
  );
}

export function ReachabilityAnalyzerDetail({ params }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeNetworkInsightsPath(params.id), [params.id]);
  const analyses = useAsync(() => api.describeNetworkInsightsAnalyses(params.id), [params.id]);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState([]);

  const runAnalysis = async () => {
    setBusy(true);
    try { await api.startNetworkInsightsAnalysis(params.id); notify.success("Analysis started."); analyses.reload(); }
    catch (e) { notify.error(e); } finally { setBusy(false); }
  };

  if (t.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (!t.data) return <ErrorAlert error={{ message: "Network Insights path not found" }} />;
  const p = t.data;
  const rows = analyses.data || [];
  const latest = rows[0];
  const selected = sel[0] || latest;

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <ButtonDropdown items={[{ id: "delete", text: "Delete path" }]} onItemClick={async () => {
        if (confirm(`Delete ${p.NetworkInsightsPathId}?`)) {
          for (const a of rows) await api.deleteNetworkInsightsAnalysis(a.NetworkInsightsAnalysisId);
          await api.deleteNetworkInsightsPath(p.NetworkInsightsPathId);
          notify.success("Path deleted."); navigate("vpc", "reachability-analyzer");
        }
      }}>Actions</ButtonDropdown>
    }>{p.NetworkInsightsPathId}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Details" columns={3} items={[
          ["Network Insights Path ID", p.NetworkInsightsPathId], ["Source", p.Source], ["Destination", p.Destination || p.DestinationIp || "-"],
          ["Protocol", p.Protocol.toUpperCase()], ["Destination port", p.DestinationPort ?? "-"], ["Created", p.CreatedDate],
        ]} />
        <Container header={<Header variant="h2" counter={`(${rows.length})`} actions={<Button variant="primary" loading={busy} onClick={runAnalysis}>Run reachability analysis</Button>}>Analysis results</Header>}>
          <Table
            variant="embedded"
            items={rows}
            selectionType="single"
            selectedItems={sel}
            onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            trackBy="NetworkInsightsAnalysisId"
            columnDefinitions={[
              { id: "id", header: "Analysis ID", cell: (a) => a.NetworkInsightsAnalysisId },
              { id: "status", header: "Status", cell: (a) => a.Status },
              { id: "found", header: "Path found", cell: (a) => <StatusIndicator type={a.NetworkPathFound ? "success" : "stopped"}>{a.NetworkPathFound ? "True" : "False"}</StatusIndicator> },
              { id: "started", header: "Started", cell: (a) => a.StartDate },
            ]}
            empty={<Box textAlign="center" color="inherit">No analysis runs yet</Box>}
          />
        </Container>
        {selected && (
          <Container header={<Header variant="h2">Explanation</Header>}>
            {selected.NetworkPathFound ? (
              <StatusIndicator type="success">Path is clear — the destination is reachable.</StatusIndicator>
            ) : (
              <SpaceBetween size="m">
                <StatusIndicator type="stopped">Network path is not reachable</StatusIndicator>
                {selected.Explanations.map((e, i) => (
                  <KeyValue key={i} columns={3} items={[
                    ["Explanation code", e.ExplanationCode], ["Component", e.ComponentId || "-"], ["Direction", e.Direction || "-"],
                  ]} />
                ))}
              </SpaceBetween>
            )}
            {selected.ForwardPathComponents.length > 0 && (
              <Box padding={{ top: "m" }}>
                <Box variant="awsui-key-label">Forward path components</Box>
                <ol>{selected.ForwardPathComponents.map((c) => <li key={c.SequenceNumber}>{c.Component.Name} ({c.Component.Id})</li>)}</ol>
              </Box>
            )}
          </Container>
        )}
      </SpaceBetween>
    </ContentLayout>
  );
}
