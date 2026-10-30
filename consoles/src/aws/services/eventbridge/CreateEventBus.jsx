import { useEffect, useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tiles from "@cloudscape-design/components/tiles";
import Toggle from "@cloudscape-design/components/toggle";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { ErrorAlert, NotSimulated } from "../../kit/common.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import * as api from "./api.js";

export default function CreateEventBus({ params }) {
  const editing = !!params?.name;
  const notify = useNotify();
  const existing = useAsync(() => (editing ? api.describeEventBus(params.name) : Promise.resolve(null)), [params?.name]);

  const [busType, setBusType] = useState("custom");
  const [name, setName] = useState(editing ? params.name : "");
  const [description, setDescription] = useState("");
  const [retention, setRetention] = useState("");
  const [sharing, setSharing] = useState(false);
  const [tags, setTags] = useState([]);
  const [existingTags, setExistingTags] = useState([]);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = touched && !editing && !/^[a-zA-Z0-9._/-]{1,256}$/.test(name) ? "Enter a valid event bus name." : null;

  useEffect(() => {
    if (existing.data) {
      setDescription(existing.data.Description || "");
      api.listTagsForResource(existing.data.Arn).then((ts) => {
        const mapped = ts.map((t) => ({ key: t.Key, value: t.Value }));
        setExistingTags(mapped); setTags(mapped);
      });
    }
  }, [existing.data]);

  const submit = async () => {
    setTouched(true);
    if (!editing && !/^[a-zA-Z0-9._/-]{1,256}$/.test(name)) return;
    setBusy(true); setError(null);
    try {
      if (editing) {
        await api.updateEventBus(name, description);
      } else {
        await api.createEventBus({ Name: name, Description: description, Tags: tags.filter((t) => t.key).map((t) => ({ Key: t.key, Value: t.value })) });
      }
      const arn = editing ? existing.data.Arn : (await api.describeEventBus(name)).Arn;
      const removed = existingTags.filter((e) => !tags.some((t) => t.key === e.key));
      const added = tags.filter((t) => t.key && !existingTags.some((e) => e.key === t.key && e.value === t.value));
      if (removed.length) await api.untagResource(arn, removed.map((t) => t.key));
      if (added.length) await api.tagResource(arn, added.map((t) => ({ Key: t.key, Value: t.value })));
      notify.success(editing ? `Updated event bus ${name}.` : `Creating the ${name} event bus. It will be available for use shortly.`);
      navigate("eventbridge", "event-buses", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">{editing ? "Edit event bus" : "Create custom event bus"}</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/eventbridge/event-buses" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>{editing ? "Save" : "Create"}</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            {!editing && (
              <Container header={<Header variant="h2">Bus type</Header>}>
                <FormField label="Bus type">
                  <Tiles value={busType} onChange={({ detail }) => setBusType(detail.value)} items={[
                    { value: "custom", label: "Custom", description: "An event bus for your own applications and AWS services." },
                    { value: "partner", label: "Partner", description: "An event bus for a SaaS partner's events (not simulated in Vyomi)." },
                  ]} />
                </FormField>
              </Container>
            )}
            {!editing && busType === "partner" ? (
              <NotSimulated feature="Partner event buses" note="EventBridge partner integrations aren't modeled in Vyomi." />
            ) : (
              <>
                <Container header={<Header variant="h2">Event bus detail</Header>}>
                  <SpaceBetween size="l">
                    <FormField label="Name" errorText={nameErr}>
                      <Input value={name} disabled={editing} onChange={({ detail }) => setName(detail.value)} ariaLabel="Name" />
                    </FormField>
                    <FormField label="Description - optional">
                      <Input value={description} onChange={({ detail }) => setDescription(detail.value)} ariaLabel="Description" />
                    </FormField>
                  </SpaceBetween>
                </Container>

                {!editing && (
                  <Container header={<Header variant="h2">Additional configuration - optional</Header>}>
                    <SpaceBetween size="l">
                      <FormField label="Retention period" description="Not simulated — events are never discarded for age.">
                        <Input type="number" value={retention} onChange={({ detail }) => setRetention(detail.value)} ariaLabel="Retention period" placeholder="e.g. 1" />
                      </FormField>
                      <FormField label="Enable event bus sharing">
                        <Toggle checked={sharing} onChange={({ detail }) => setSharing(detail.checked)}>Allow other AWS accounts to send events to this bus</Toggle>
                      </FormField>
                    </SpaceBetween>
                  </Container>
                )}

                <Container header={<Header variant="h2">Encryption</Header>}>
                  <FormField label="AWS Key Management Service (KMS) key">
                    <NotSimulated feature="Event bus encryption with a customer KMS key" note="Events are stored unencrypted inside Vyomi's own store." />
                  </FormField>
                </Container>

                <Container header={<Header variant="h2">Logs - new, optional</Header>}>
                  <FormField label="Log destination">
                    <NotSimulated feature="Delivering bus logs to CloudWatch Logs / S3 / Firehose" />
                  </FormField>
                </Container>

                <Container header={<Header variant="h2">Resource-based policy - optional</Header>}>
                  <FormField label="Resource-based policy">
                    <NotSimulated feature="Resource-based policy enforcement" note="A policy document can be attached but Vyomi never evaluates it against a cross-account PutEvents call." />
                  </FormField>
                </Container>

                <Container header={<Header variant="h2">Archives - optional</Header>}>
                  <FormField label="Archive" description="Create or manage archives from the Archives tab after the bus exists.">
                    <NotSimulated feature="Attaching an archive at bus-creation time" />
                  </FormField>
                </Container>

                <Container header={<Header variant="h2">Schema discovery - optional</Header>}>
                  <FormField label="Schema discovery">
                    <NotSimulated feature="Schema discovery" note="The Schema registry isn't modeled in Vyomi." />
                  </FormField>
                </Container>

                <Container header={<Header variant="h2" description="Tags are pairs of keys and optional values that you can assign to AWS resources.">Tags - optional</Header>}>
                  <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} />
                </Container>
              </>
            )}
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}

const TAG_I18N = {
  keyHeader: "Key", valueHeader: "Value - optional", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
  undoPrompt: "This tag will be removed upon saving changes", loading: "Loading tags", keyPlaceholder: "Enter key", valuePlaceholder: "Enter value",
  emptyTags: "No tags are associated with the resource.", tooManyKeysSuggestion: "You have more keys than can be displayed",
  tooManyValuesSuggestion: "You have more values than can be displayed", keysSuggestionLoading: "Loading tag keys",
  keysSuggestionError: "Tag keys could not be retrieved", valuesSuggestionLoading: "Loading tag values", valuesSuggestionError: "Tag values could not be retrieved",
  emptyKeyError: "You must specify a tag key", maxKeyCharLengthError: "The maximum number of characters you can use in a tag key is 128.",
  maxValueCharLengthError: "The maximum number of characters you can use in a tag value is 256.", duplicateKeyError: "You must specify a unique tag key.",
  invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:",
  tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "You have reached the limit of 50 tags.", tagLimitExceeded: () => "You have exceeded the limit of 50 tags.",
};
