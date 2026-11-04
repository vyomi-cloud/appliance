import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

export default function DaxEvents() {
  const events = useAsync(() => api.describeDaxEvents(), []);

  return (
    <ContentLayout header={<Header variant="h1" actions={<CapabilityBadge id="dynamodb.dax.events" />}>Events</Header>}>
      <ResourceTable
        resourceName="Events"
        items={events.data || []}
        loading={events.loading}
        error={events.error}
        onRefresh={events.reload}
        trackBy={(e) => `${e.Date}-${e.SourceName}-${e.Message}`}
        columns={[
          { id: "time", header: "Time", isRowHeader: true, cell: (e) => fmtDate(e.Date) },
          { id: "source-type", header: "Source type", cell: (e) => e.SourceType },
          { id: "source-id", header: "Source ID", cell: (e) => e.SourceName },
          { id: "event", header: "Event", cell: (e) => e.Message },
        ]}
        empty={{ title: "No events", subtitle: "DAX cluster, subnet group and parameter group lifecycle events show up here." }}
      />
    </ContentLayout>
  );
}
