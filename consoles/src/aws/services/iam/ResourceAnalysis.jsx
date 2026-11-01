/* Access Analyzer's external-access findings — real, computed from IAM role trust
 * policies + S3 bucket policies naming a principal outside this account (see
 * core/iam_core.py: _compute_findings / iam.access-analyzer). Needs an analyzer of type
 * ACCOUNT, created on the Access Analyzer page. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Link from "@cloudscape-design/components/link";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { asList } from "../../../common/wire.js";
import { navigate } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function ResourceAnalysis() {
  const notify = useNotify();
  const analyzers = useAsync(() => api.listAnalyzers(), []);
  const analyzer = (analyzers.data || []).find((a) => a.Type === "ACCOUNT");
  const f = useAsync(() => (analyzer ? api.listFindings(analyzer.Name) : Promise.resolve([])), [analyzer?.Name]);
  const [sel, setSel] = useState([]);

  return (
    <CapabilityContainer id="iam.access-analyzer" title="Resource analysis" counter={analyzer ? `(${(f.data || []).length})` : undefined}
      actions={analyzer && <Button disabled={!sel.length} onClick={async () => {
        for (const x of sel) await api.updateFindingStatus(analyzer.Name, x.Id, "ARCHIVED");
        notify.success("Finding(s) archived."); setSel([]); f.reload();
      }}>Archive</Button>}>
      {!analyzer
        ? <Box textAlign="center" color="inherit">
            <b>No external access analyzer</b>
            <Box variant="p" color="text-body-secondary">
              Create an "External access analyzer — account" on the <Link onFollow={(e) => { e.preventDefault(); navigate("iam", "access-analyzer"); }}>Access Analyzer</Link> page.
            </Box>
          </Box>
        : <Table variant="embedded" items={f.data || []} loading={f.loading} trackBy="Id"
            selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "resource", header: "Resource", cell: (x) => x.Resource },
              { id: "type", header: "Resource type", cell: (x) => x.ResourceType },
              { id: "principal", header: "External principal", cell: (x) => asList(x.Principals?.member).join(", ") || "-" },
              { id: "status", header: "Status", cell: (x) => x.Status },
              { id: "created", header: "Analyzed at", cell: (x) => fmtDate(x.CreatedAt) },
            ]}
            empty={<Box textAlign="center" color="inherit"><b>No external access findings</b></Box>} />}
    </CapabilityContainer>
  );
}
