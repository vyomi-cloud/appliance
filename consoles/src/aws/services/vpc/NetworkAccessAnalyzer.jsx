/* Network Access Analyzer: real access scopes + analyses, reusing the SAME netsim evaluator
 * as Reachability Analyzer (core/vpc_core.py's _start_network_insights_access_scope_analysis).
 * Simplified vs. real AWS: match paths are resource-id lists (empty = every ENI / the
 * internet), evaluated as "is there an UNRESTRICTED path" (protocol=tcp, port=any) rather than
 * the full path-statement language — see aws.vpc.network-access-analyzer's limitations. */
import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Box from "@cloudscape-design/components/box";
import Table from "@cloudscape-design/components/table";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

function AnalysisFindings({ analysisId }) {
  const f = useAsync(() => api.describeNetworkInsightsAccessScopeAnalysisFindings(analysisId), [analysisId]);
  const findings = f.data?.Findings || [];
  return (
    <Box padding={{ top: "s" }}>
      <Table loading={f.loading} items={findings}
        header={<Header variant="h3" counter={`(${findings.length})`}>Findings — unrestricted paths found</Header>}
        columnDefinitions={[
          { id: "id", header: "Finding ID", cell: (r) => r.FindingId },
          { id: "comp", header: "Path components", cell: (r) => r.FindingComponents.join(" → ") },
        ]}
        empty={<Box textAlign="center" color="inherit">No findings — every evaluated path requires a specific port (or is blocked).</Box>} />
    </Box>
  );
}

export function NetworkAccessAnalyzer() {
  const notify = useNotify();
  const [sel, setSel] = useState([]);
  const [del, setDel] = useState(false);
  const [running, setRunning] = useState(null);
  const [open, setOpen] = useState(null);
  const scopes = useAsync(() => api.describeNetworkInsightsAccessScopes(), []);
  const analyses = useAsync(() => api.describeNetworkInsightsAccessScopeAnalyses(), []);
  const rows = scopes.data || [];

  const createScope = async () => {
    const s = await api.createNetworkInsightsAccessScope([{ source: [], destination: [] }]);
    notify.success(`Access scope "${s.networkInsightsAccessScopeId}" created (default: every ENI → the internet, unrestricted).`);
    scopes.reload();
  };
  const runAnalysis = async (scopeId) => {
    setRunning(scopeId);
    try {
      const a = await api.startNetworkInsightsAccessScopeAnalysis(scopeId);
      notify.success(`Analysis "${a.NetworkInsightsAccessScopeAnalysisId}" ${a.FindingsFound === "true" ? "found unrestricted paths." : "found no unrestricted paths."}`);
      analyses.reload();
      setOpen(a.NetworkInsightsAccessScopeAnalysisId);
    } finally { setRunning(null); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Network Access Analyzer</Header>}>
      <CapabilityContainer id="aws.vpc.network-access-analyzer" title="Network Access Scopes" counter={`(${rows.length})`}
        description="Evaluates your whole network's configuration against a scope — e.g. 'what's internet-accessible with no port restriction' — rather than one source/destination path (see Reachability Analyzer for that).">
        <SpaceBetween size="l">
          <ResourceTable
            resourceName="Access scopes" items={rows} loading={scopes.loading} error={scopes.error} onRefresh={scopes.reload}
            trackBy="NetworkInsightsAccessScopeId" selectionType="multi" selectedItems={sel} onSelectionChange={setSel}
            empty={<Box textAlign="center">No access scopes found</Box>}
            columns={[
              { id: "id", header: "Access scope ID", isRowHeader: true, cell: (s) => s.NetworkInsightsAccessScopeId },
              { id: "created", header: "Created", cell: (s) => s.CreatedDate },
              { id: "run", header: "Analysis", cell: (s) => <Button variant="inline-link" loading={running === s.NetworkInsightsAccessScopeId} onClick={() => runAnalysis(s.NetworkInsightsAccessScopeId)}>Run analysis</Button> },
            ]}
            actions={
              <SpaceBetween direction="horizontal" size="xs">
                <Button disabled={!sel.length} onClick={() => setDel(true)}>Delete</Button>
                <Button variant="primary" onClick={createScope}>Create access scope</Button>
              </SpaceBetween>
            }
          />
          <Table items={analyses.data || []}
            header={<Header variant="h3" counter={`(${(analyses.data || []).length})`}>Analyses</Header>}
            columnDefinitions={[
              { id: "id", header: "Analysis ID", cell: (a) => <Button variant="inline-link" onClick={() => setOpen(open === a.NetworkInsightsAccessScopeAnalysisId ? null : a.NetworkInsightsAccessScopeAnalysisId)}>{a.NetworkInsightsAccessScopeAnalysisId}</Button> },
              { id: "scope", header: "Access scope ID", cell: (a) => a.NetworkInsightsAccessScopeId },
              { id: "status", header: "Status", cell: (a) => <StatusIndicator type={a.Status === "succeeded" ? "success" : "pending"}>{a.Status}</StatusIndicator> },
              { id: "found", header: "Findings found", cell: (a) => String(a.FindingsFound) },
              { id: "start", header: "Start date", cell: (a) => a.StartDate },
            ]}
            empty={<Box textAlign="center" color="inherit">No analyses yet — run one from a scope above.</Box>} />
          {open && <AnalysisFindings analysisId={open} />}
        </SpaceBetween>
      </CapabilityContainer>
      <DeleteModal visible={del} resourceType="access scope" names={sel.map((s) => s.NetworkInsightsAccessScopeId)} confirmText="delete" onDismiss={() => setDel(false)}
        onConfirm={async () => { for (const s of sel) await api.deleteNetworkInsightsAccessScope(s.NetworkInsightsAccessScopeId); notify.success(`${sel.length} access scope(s) deleted.`); setSel([]); scopes.reload(); }} />
    </ContentLayout>
  );
}
