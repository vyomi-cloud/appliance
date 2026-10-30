/* Temporary delegation requests — real ListAccountAccessRequests (Vyomi-only wire call,
 * see core/iam_core.py). Real AWS lets a member account request centralized root access
 * from the management account; Vyomi has no member accounts to originate one, so there is
 * no "Request access" action here — only the record a request would leave behind. */
import Button from "@cloudscape-design/components/button";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityContainer, saveNotice } from "../../kit/Capability.jsx";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function TemporaryDelegationRequests() {
  const notify = useNotify();
  const r = useAsync(() => api.listAccountAccessRequests(), []);

  return (
    <SpaceBetween size="l">
      <ResourceTable
        resourceName="Temporary delegation requests"
        items={r.data || []}
        loading={r.loading}
        error={r.error}
        onRefresh={r.reload}
        trackBy="RequestId"
        empty={{ title: "No requests" }}
        columns={[
          { id: "id", header: "Request Id", isRowHeader: true, cell: (x) => x.RequestId },
          { id: "status", header: "Status", cell: (x) => x.Status },
          { id: "requestor", header: "Requestor Id", cell: (x) => x.RequestorId },
          { id: "initiated", header: "Initiated by", cell: (x) => x.InitiatedBy },
          { id: "created", header: "Request created", cell: (x) => fmtDate(x.RequestCreated) },
          { id: "expires", header: "Request expires", cell: (x) => fmtDate(x.RequestExpires) },
        ]}
      />
      <CapabilityContainer id="iam.organizations.access-requests" title="Configure request notifications"
        actions={<Button onClick={() => notify.success(`Notification preference saved.${saveNotice("iam.organizations.access-requests")}`)}>Configure notifications</Button>} />
    </SpaceBetween>
  );
}
