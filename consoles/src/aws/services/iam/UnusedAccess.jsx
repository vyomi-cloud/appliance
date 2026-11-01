/* Access Analyzer's unused-access findings — real, computed from IAM user access keys
 * that have never appeared in Vyomi's native-wire activity log (see core/iam_core.py:
 * _compute_findings / iam.access-analyzer). Needs an analyzer of type
 * ACCOUNT_UNUSED_ACCESS, created on the Access Analyzer page. */
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

export default function UnusedAccess() {
  const notify = useNotify();
  const analyzers = useAsync(() => api.listAnalyzers(), []);
  const analyzer = (analyzers.data || []).find((a) => a.Type === "ACCOUNT_UNUSED_ACCESS");
  const f = useAsync(() => (analyzer ? api.listFindings(analyzer.Name) : Promise.resolve([])), [analyzer?.Name]);
  const [sel, setSel] = useState([]);

  return (
    <CapabilityContainer id="iam.access-analyzer" title="Unused access" counter={analyzer ? `(${(f.data || []).length})` : undefined}
      actions={analyzer && <Button disabled={!sel.length} onClick={async () => {
        for (const x of sel) await api.updateFindingStatus(analyzer.Name, x.Id, "ARCHIVED");
        notify.success("Finding(s) archived."); setSel([]); f.reload();
      }}>Archive</Button>}>
      {!analyzer
        ? <Box textAlign="center" color="inherit">
            <b>No unused access analyzer</b>
            <Box variant="p" color="text-body-secondary">
              Create an "Unused access analyzer — account" on the <Link onFollow={(e) => { e.preventDefault(); navigate("iam", "access-analyzer"); }}>Access Analyzer</Link> page.
            </Box>
          </Box>
        : <Table variant="embedded" items={f.data || []} loading={f.loading} trackBy="Id"
            selectionType="multi" selectedItems={sel} onSelectionChange={({ detail }) => setSel(detail.selectedItems)}
            columnDefinitions={[
              { id: "resource", header: "Resource", cell: (x) => x.Resource },
              { id: "type", header: "Finding type", cell: (x) => x.FindingType },
              { id: "principal", header: "Principal", cell: (x) => asList(x.Principals?.member).join(", ") || "-" },
              { id: "age", header: "Age (days)", cell: (x) => x.AgeDays ?? "-" },
              { id: "status", header: "Status", cell: (x) => x.Status },
              { id: "created", header: "Analyzed at", cell: (x) => fmtDate(x.CreatedAt) },
            ]}
            empty={<Box textAlign="center" color="inherit"><b>No unused access findings</b></Box>} />}
    </CapabilityContainer>
  );
}
