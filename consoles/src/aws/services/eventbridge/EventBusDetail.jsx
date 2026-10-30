import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Spinner from "@cloudscape-design/components/spinner";
import Tabs from "@cloudscape-design/components/tabs";
import TagEditor from "@cloudscape-design/components/tag-editor";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { ErrorAlert, KeyValue, NotSimulatedContainer } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { RulesTable } from "./Rules.jsx";
import { ArchivesTable } from "./Archives.jsx";
import * as api from "./api.js";

function TagsTab({ arn }) {
  const notify = useNotify();
  const { data: loaded, reload } = useAsync(() => api.listTagsForResource(arn), [arn]);
  const [tags, setTags] = useState(null);
  const [busy, setBusy] = useState(false);
  const shown = tags ?? (loaded || []).map((t) => ({ key: t.Key, value: t.Value }));
  const save = async () => {
    setBusy(true);
    try {
      const before = (loaded || []).map((t) => ({ key: t.Key, value: t.Value }));
      const removed = before.filter((b) => !shown.some((s) => s.key === b.key));
      const added = shown.filter((s) => s.key && !before.some((b) => b.key === s.key && b.value === s.value));
      if (removed.length) await api.untagResource(arn, removed.map((t) => t.key));
      if (added.length) await api.tagResource(arn, added.map((t) => ({ Key: t.key, Value: t.value })));
      notify.success("Tags updated.");
      setTags(null); reload();
    } catch (e) { notify.error(e); } finally { setBusy(false); }
  };
  return (
    <SpaceBetween size="l">
      <TagEditor tags={shown} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={{
        keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
        undoPrompt: "Removed upon saving", loading: "Loading tags", keyPlaceholder: "Key", valuePlaceholder: "Value",
        emptyTags: "No tags associated with this resource.", emptyKeyError: "You must specify a tag key",
        maxKeyCharLengthError: "128 character limit.", maxValueCharLengthError: "256 character limit.",
        duplicateKeyError: "Unique key required.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:",
        tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "Tag limit reached.", tagLimitExceeded: () => "Tag limit exceeded.",
      }} />
      <Box float="left"><Button loading={busy} onClick={save}>Save changes</Button></Box>
    </SpaceBetween>
  );
}

export default function EventBusDetail({ params }) {
  const name = params.name;
  const bus = useAsync(() => api.describeEventBus(name), [name]);
  if (bus.loading) return <Box textAlign="center" padding="xxl"><Spinner size="large" /></Box>;
  if (bus.error) return <ErrorAlert error={bus.error} />;
  const d = bus.data;

  return (
    <ContentLayout header={<Header variant="h1" actions={
      <SpaceBetween direction="horizontal" size="xs">
        <Button onClick={bus.reload} iconName="refresh" ariaLabel="Refresh" />
        <Button href={href("eventbridge", "event-buses", name, "edit")} onFollow={follow}>Edit</Button>
        <Button variant="primary" href={href("eventbridge", "event-buses", name, "send")} onFollow={follow}>Send events</Button>
      </SpaceBetween>
    }>{d.Name}</Header>}>
      <SpaceBetween size="l">
        <KeyValue title="Event bus details" columns={3} items={[
          ["Event bus name", d.Name], ["Description", d.Description || "-"], ["Event bus ARN", d.Arn],
        ]} />
        <Tabs tabs={[
          { id: "rules", label: "Rules", content: <RulesTable eventBusName={name} resourceName="Event pattern rules" createHref={`${href("eventbridge", "create-rule")}?bus=${encodeURIComponent(name)}`} /> },
          { id: "encryption", label: "Encryption", content: <NotSimulatedContainer title="Encryption" note="Events are stored unencrypted inside Vyomi's own store." /> },
          { id: "permissions", label: "Permissions", content: <NotSimulatedContainer title="Resource-based policy" note="A policy document can be stored via UpdateEventBus, but Vyomi never evaluates it against a cross-account PutEvents call." /> },
          { id: "monitoring", label: "Monitoring", content: <NotSimulatedContainer title="Monitoring" note="Metrics dashboard: CloudWatch metrics for EventBridge aren't aggregated in Vyomi." /> },
          { id: "logs", label: "Logs", content: <NotSimulatedContainer title="Logs" note="Delivering bus logs to CloudWatch Logs isn't modeled." /> },
          { id: "archives", label: "Archives & Replays", content: <ArchivesTable eventBusArn={d.Arn} resourceName="Archives" createHref={href("eventbridge", "create-archive")} /> },
          { id: "tags", label: "Tags", content: <TagsTab arn={d.Arn} /> },
        ]} />
      </SpaceBetween>
    </ContentLayout>
  );
}
