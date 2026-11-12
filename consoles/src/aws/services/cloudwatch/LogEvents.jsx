import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Toggle from "@cloudscape-design/components/toggle";
import { useAsync } from "../../../common/useAsync.js";
import { navigate } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import * as api from "./api.js";

const RANGES = { "1m": 60, "30m": 1800, "1h": 3600, "12h": 43200 };

export default function LogEvents({ params }) {
  const group = params.name, stream = params.stream;
  const [filterText, setFilterText] = useState("");
  const [appliedFilter, setAppliedFilter] = useState("");
  const [range, setRange] = useState(null);
  const [utc, setUtc] = useState(true);

  const t = useAsync(() => {
    const startTime = range ? Date.now() - RANGES[range] * 1000 : undefined;
    return appliedFilter
      ? api.filterLogEvents(group, { logStreamNames: [stream], filterPattern: appliedFilter, startTime })
      : api.getLogEvents(group, stream, { startFromHead: true, startTime });
  }, [group, stream, appliedFilter, range]);

  const fmt = (ms) => (utc ? new Date(ms).toISOString().replace("T", " ").replace("Z", "") : fmtDate(ms));

  return (
    <ContentLayout header={
      <Header variant="h1" actions={
        <SpaceBetween direction="horizontal" size="xs">
          <Button iconName="refresh" ariaLabel="Refresh" onClick={t.reload} />
          <ButtonDropdown items={[{ id: "metric-filter", text: "Create metric filter" }]} onItemClick={() => navigate("cloudwatch", "logs", group)}>Actions</ButtonDropdown>
          <Button onClick={() => navigate("cloudwatch", "live-tail")}>Start tailing</Button>
        </SpaceBetween>
      }>{stream}</Header>
    }>
      <SpaceBetween size="l">
        <SpaceBetween direction="horizontal" size="xs" alignItems="center">
          {["Clear", "1m", "30m", "1h", "12h", "Custom"].map((r) => (
            <Button key={r} variant={range === r ? "primary" : "normal"} disabled={r === "Custom"} onClick={() => setRange(r === "Clear" ? null : r)}>{r}</Button>
          ))}
          <Toggle checked={utc} onChange={({ detail }) => setUtc(detail.checked)}>UTC timezone</Toggle>
          <Toggle checked disabled>Display</Toggle>
        </SpaceBetween>
        <Input
          value={filterText}
          onChange={({ detail }) => setFilterText(detail.value)}
          onKeyDown={({ detail }) => { if (detail.key === "Enter") setAppliedFilter(filterText); }}
          placeholder="Filter events - press enter to search"
          ariaLabel="Filter events - press enter to search"
          type="search"
        />
        <Table
          items={t.data || []}
          loading={t.loading}
          columnDefinitions={[
            { id: "ts", header: "Timestamp", cell: (e) => fmt(e.timestamp) },
            { id: "msg", header: "Message", cell: (e) => <Box variant="code">{e.message}</Box> },
          ]}
          empty={<Box textAlign="center" color="inherit">No events</Box>}
        />
      </SpaceBetween>
    </ContentLayout>
  );
}
