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
import { KmsKeySelect, LogConfigFields, PolicyField } from "./BusSettings.jsx";
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
  const [kmsKey, setKmsKey] = useState("");
  const [logCfg, setLogCfg] = useState({ Level: "OFF", IncludeDetail: "NONE" });
  const [policy, setPolicy] = useState("");
  const [discovery, setDiscovery] = useState(false);
  const [archiveName, setArchiveName] = useState("");
  const [archiveDays, setArchiveDays] = useState("0");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = touched && !editing && !/^[a-zA-Z0-9._/-]{1,256}$/.test(name) ? "Enter a valid event bus name." : null;

  useEffect(() => {
    if (existing.data) {
      setDescription(existing.data.Description || "");
      setKmsKey(existing.data.KmsKeyIdentifier || ""); if (existing.data.LogConfig) setLogCfg(existing.data.LogConfig); if (existing.data.Policy) setPolicy(existing.data.Policy);
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
        await api.updateEventBusConfig(name, { Description: description, KmsKeyIdentifier: kmsKey, LogConfig: logCfg, ...(policy.trim() ? { Policy: policy } : {}) });
      } else {
        await api.createEventBus({ Name: name, Description: description, ...(kmsKey ? { KmsKeyIdentifier: kmsKey } : {}), ...(logCfg.Level !== "OFF" ? { LogConfig: logCfg } : {}), Tags: tags.filter((t) => t.key).map((t) => ({ Key: t.key, Value: t.value })) });
      }
      if (!editing && policy.trim()) await api.updateEventBusConfig(name, { Policy: policy });
      if (!editing && discovery) await api.createDiscoverer((await api.describeEventBus(name)).Arn, "");
      if (!editing && archiveName.trim()) {
        const busArn = (await api.describeEventBus(name)).Arn;
        await api.createArchive({ ArchiveName: archiveName.trim(), EventSourceArn: busArn, RetentionDays: Number(archiveDays) || 0, ...(kmsKey ? { KmsKeyIdentifier: kmsKey } : {}) });
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
                    { value: "partner", label: "Partner", description: "An event bus for a SaaS partner's events, created by associating a partner event source." },
                  ]} />
                </FormField>
              </Container>
            )}
            {!editing && busType === "partner" ? (
              <Container header={<Header variant="h2">Partner event bus</Header>}>
                <SpaceBetween size="s">
                  <Box>A partner event bus is created by associating a partner event source: the bus takes the source's name and receives the partner's events.</Box>
                  <Button variant="primary" href="#/eventbridge/partner-event-sources" onFollow={follow}>Go to partner event sources</Button>
                </SpaceBetween>
              </Container>
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
                      <FormField label="Retention period" description="Coming soon — events are never discarded for age.">
                        <Input type="number" value={retention} onChange={({ detail }) => setRetention(detail.value)} ariaLabel="Retention period" placeholder="e.g. 1" />
                      </FormField>
                      <FormField label="Enable event bus sharing">
                        <Toggle checked={sharing} onChange={({ detail }) => setSharing(detail.checked)}>Allow other AWS accounts to send events to this bus</Toggle>
                      </FormField>
                    </SpaceBetween>
                  </Container>
                )}

                <Container header={<Header variant="h2">Encryption</Header>}>
                  <KmsKeySelect value={kmsKey} onChange={setKmsKey} />
                </Container>

                <Container header={<Header variant="h2">Logs - new, optional</Header>}>
                  <LogConfigFields value={logCfg} onChange={setLogCfg} />
                </Container>

                <Container header={<Header variant="h2">Resource-based policy - optional</Header>}>
                  <PolicyField value={policy} onChange={setPolicy} />
                </Container>

                <Container header={<Header variant="h2">Archives - optional</Header>}>
                  <SpaceBetween size="l">
                    <FormField label="Archive name" description="Optional. Creates an archive on this bus right after the bus is created (CreateArchive)."><Input value={archiveName} disabled={editing} onChange={({ detail }) => setArchiveName(detail.value)} ariaLabel="Archive name" /></FormField>
                    <FormField label="Archive retention (days)" description="0 = indefinite."><Input type="number" value={archiveDays} disabled={editing} onChange={({ detail }) => setArchiveDays(detail.value)} ariaLabel="Archive retention days" /></FormField>
                  </SpaceBetween>
                </Container>

                <Container header={<Header variant="h2">Schema discovery - optional</Header>}>
                  <FormField label="Schema discovery" description="Infers an OpenAPI schema from every event sent to this bus (registry discovered-schemas)."><Toggle checked={discovery} disabled={editing} onChange={({ detail }) => setDiscovery(detail.checked)}>Enable schema discovery on this event bus</Toggle></FormField>
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
