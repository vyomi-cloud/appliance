import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function Events() {
  const t = useAsync(() => api.describeEvents());
  return (
    <ResourceTable
      resourceName="Events"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy={(e) => `${e.SourceIdentifier}-${e.Date}`}
      filterPlaceholder="Filter by events"
      empty={{ title: "No event found" }}
      columns={[
        { id: "source", header: "Source", isRowHeader: true, cell: (e) => e.SourceIdentifier },
        { id: "type", header: "Type", cell: (e) => e.SourceType },
        { id: "time", header: "Time", cell: (e) => fmtDate(e.Date) },
        { id: "message", header: "Message", cell: (e) => e.Message },
      ]}
    />
  );
}
