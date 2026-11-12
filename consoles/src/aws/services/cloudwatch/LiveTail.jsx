/* Live Tail — real events, polled. The native Live Tail protocol is a bidirectional
 * WebSocket stream; Vyomi polls FilterLogEvents on an interval instead (see
 * core/capabilities/aws/cloudwatch.json: aws.cloudwatch.logs.live-tail, "limited"). */
import { useEffect, useRef, useState } from "react";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Multiselect from "@cloudscape-design/components/multiselect";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import { useAsync } from "../../../common/useAsync.js";
import * as api from "./api.js";

const POLL_MS = 2000;

export default function LiveTail() {
  const groups = useAsync(() => api.describeLogGroups({}), []);
  const [selectedGroups, setSelectedGroups] = useState([]);
  const [selectedStreams, setSelectedStreams] = useState([]);
  const [pattern, setPattern] = useState("");
  const [tailing, setTailing] = useState(false);
  const [events, setEvents] = useState([]);
  const timer = useRef(null);
  const since = useRef(0);

  const streamsForGroups = useAsync(async () => {
    const lists = await Promise.all(selectedGroups.map((g) => api.describeLogStreams(g.value)));
    return lists.flat().map((s) => s.logStreamName);
  }, [selectedGroups]);

  const poll = async () => {
    const results = await Promise.all(selectedGroups.map((g) => api.filterLogEvents(g.value, {
      filterPattern: pattern || undefined,
      logStreamNames: selectedStreams.length ? selectedStreams.map((s) => s.value) : undefined,
      startTime: since.current,
    }).then((evs) => evs.map((e) => ({ ...e, group: g.value }))).catch(() => [])));
    const fresh = results.flat();
    if (fresh.length) {
      since.current = Math.max(since.current, ...fresh.map((e) => e.timestamp + 1));
      setEvents((prev) => [...prev, ...fresh].slice(-500));
    }
  };

  useEffect(() => {
    if (!tailing) return;
    poll();
    timer.current = setInterval(poll, POLL_MS);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tailing]);

  const start = () => { if (!selectedGroups.length) return; since.current = Date.now() - 60000; setEvents([]); setTailing(true); };
  const clear = () => { setTailing(false); setEvents([]); setSelectedGroups([]); setSelectedStreams([]); setPattern(""); };

  return (
    <ContentLayout header={<Header variant="h1">Live Tail</Header>}>
      <SpaceBetween size="l">
        <Container header={<Header variant="h2">Filter</Header>}>
          <SpaceBetween size="l">
            <FormField label="Select log groups">
              <Multiselect selectedOptions={selectedGroups} onChange={({ detail }) => setSelectedGroups(detail.selectedOptions)}
                options={(groups.data || []).map((g) => ({ label: g.logGroupName, value: g.logGroupName }))} ariaLabel="Select log groups" placeholder="Choose log groups" />
            </FormField>
            <FormField label="Select log streams - optional">
              <Multiselect selectedOptions={selectedStreams} onChange={({ detail }) => setSelectedStreams(detail.selectedOptions)}
                options={(streamsForGroups.data || []).map((s) => ({ label: s, value: s }))} ariaLabel="Select log streams - optional" placeholder="All streams" disabled={!selectedGroups.length} />
            </FormField>
            <FormField label="Add filter pattern - optional">
              <Input value={pattern} onChange={({ detail }) => setPattern(detail.value)} ariaLabel="Add filter pattern - optional" />
            </FormField>
            <SpaceBetween direction="horizontal" size="xs">
              <Button variant="primary" onClick={start} disabled={!selectedGroups.length}>Start</Button>
              <Button onClick={clear}>Clear</Button>
              {tailing && <Badge color="green">Tailing — polling every {POLL_MS / 1000}s</Badge>}
            </SpaceBetween>
          </SpaceBetween>
        </Container>
        {tailing && (
          <Table
            items={events}
            columnDefinitions={[
              { id: "ts", header: "Timestamp", cell: (e) => new Date(e.timestamp).toISOString() },
              { id: "group", header: "Log group", cell: (e) => e.group },
              { id: "stream", header: "Log stream", cell: (e) => e.logStreamName },
              { id: "msg", header: "Message", cell: (e) => <Box variant="code">{e.message}</Box> },
            ]}
            empty={<Box textAlign="center" color="inherit">Waiting for events...</Box>}
          />
        )}
      </SpaceBetween>
    </ContentLayout>
  );
}
