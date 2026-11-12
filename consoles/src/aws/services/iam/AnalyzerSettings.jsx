/* Access Analyzer settings — the unused-access age threshold really gates which findings
 * UnusedAccess.jsx returns (see core/iam_core.py: _compute_findings), not a stored-only
 * preference. Analyzers themselves are created on the Access Analyzer page. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Input from "@cloudscape-design/components/input";
import Link from "@cloudscape-design/components/link";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import * as api from "./api.js";

export default function AnalyzerSettings() {
  const notify = useNotify();
  const a = useAsync(() => api.listAnalyzers(), []);
  const unused = (a.data || []).filter((x) => x.Type === "ACCOUNT_UNUSED_ACCESS");
  const [ages, setAges] = useState({});

  return (
    <CapabilityContainer id="iam.access-analyzer" title="Analyzer settings">
      {unused.length === 0
        ? <Box textAlign="center" color="inherit">
            <b>No unused access analyzer</b>
            <Box variant="p" color="text-body-secondary">
              Create an "Unused access analyzer — account" on the <Link onFollow={(e) => { e.preventDefault(); navigate("iam", "access-analyzer"); }}>Access Analyzer</Link> page.
            </Box>
          </Box>
        : <Table variant="embedded" items={unused} loading={a.loading} trackBy="Name"
            columnDefinitions={[
              { id: "name", header: "Analyzer", cell: (x) => x.Name },
              { id: "age", header: "Unused access age (days)", cell: (x) => (
                <Input type="number" ariaLabel={`Unused access age for ${x.Name}`}
                  value={ages[x.Name] ?? x.UnusedAccessAge} onChange={({ detail }) => setAges((s) => ({ ...s, [x.Name]: detail.value }))} />
              ) },
              { id: "save", header: "", cell: (x) => (
                <Button onClick={async () => {
                  await api.updateAnalyzer(x.Name, Number(ages[x.Name] ?? x.UnusedAccessAge));
                  notify.success(`Unused access age for "${x.Name}" updated.`); a.reload();
                }}>Save</Button>
              ) },
            ]} />}
    </CapabilityContainer>
  );
}
