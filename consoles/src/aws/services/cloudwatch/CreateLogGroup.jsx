import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import Checkbox from "@cloudscape-design/components/checkbox";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Form from "@cloudscape-design/components/form";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import TagEditor from "@cloudscape-design/components/tag-editor";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import { RETENTION_OPTIONS } from "./common.jsx";
import * as api from "./api.js";

const LOG_CLASSES = [{ label: "Standard", value: "STANDARD" }, { label: "Infrequent Access", value: "INFREQUENT_ACCESS" }, { label: "Delivery", value: "DELIVERY" }];
const TAG_I18N = {
  keyHeader: "Key", valueHeader: "Value", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo",
  undoPrompt: "Removed upon saving", loading: "Loading tags", keyPlaceholder: "Key", valuePlaceholder: "Value",
  emptyTags: "No tags are associated with this log group.", emptyKeyError: "You must specify a tag key",
  maxKeyCharLengthError: "128 character limit.", maxValueCharLengthError: "256 character limit.",
  duplicateKeyError: "Unique key required.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:",
  tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "Tag limit reached.", tagLimitExceeded: () => "Tag limit exceeded.",
};

export default function CreateLogGroup() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [retention, setRetention] = useState("0");
  const [logClass, setLogClass] = useState("STANDARD");
  const [kmsKeyArn, setKmsKeyArn] = useState("");
  const [deletionProtection, setDeletionProtection] = useState(false);
  const [tags, setTags] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!name) return;
    setBusy(true); setError(null);
    try {
      await api.createLogGroup(name, {
        logGroupClass: logClass, kmsKeyId: kmsKeyArn || undefined,
        deletionProtectionEnabled: deletionProtection,
        tags: Object.fromEntries(tags.filter((t) => t.key).map((t) => [t.key, t.value])),
      });
      if (retention !== "0") await api.putRetentionPolicy(name, Number(retention));
      notify.success(`Log group ${name} was created.`);
      navigate("cloudwatch", "logs", name);
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  return (
    <ContentLayout header={<Header variant="h1">Create log group</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" onClick={() => navigate("cloudwatch", "logs")}>Cancel</Button>
            <Button formAction="submit" variant="primary" loading={busy} disabled={!name}>Create</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            {error && <ErrorAlert error={error} />}
            <Container header={<Header variant="h2">Log group details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Log group name"><Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="Enter log group name" ariaLabel="Log group name" /></FormField>
                <FormField label="Retention setting"><Select selectedOption={RETENTION_OPTIONS.find((o) => o.value === retention) || { label: "Never expire", value: "0" }} onChange={({ detail }) => setRetention(detail.selectedOption.value)} options={[{ label: "Never expire", value: "0" }, ...RETENTION_OPTIONS.filter((o) => o.value !== "0")]} ariaLabel="Retention setting" /></FormField>
                <FormField label="Log class"><Select selectedOption={LOG_CLASSES.find((o) => o.value === logClass)} onChange={({ detail }) => setLogClass(detail.selectedOption.value)} options={LOG_CLASSES} ariaLabel="Log class" /></FormField>
                <FormField label="KMS key ARN - optional" secondaryControl={<Button href={href("kms", "create-key")} onFollow={follow} iconName="add-plus">Create an AWS KMS key</Button>}>
                  <Input value={kmsKeyArn} onChange={({ detail }) => setKmsKeyArn(detail.value)} placeholder="Choose an AWS KMS key or enter an ARN" ariaLabel="KMS key ARN" />
                </FormField>
                <FormField label="Deletion protection" description="Deletion protection is turned off by default.">
                  <Checkbox checked={deletionProtection} onChange={({ detail }) => setDeletionProtection(detail.checked)}>Enable deletion protection</Checkbox>
                </FormField>
              </SpaceBetween>
            </Container>
            <Container header={<Header variant="h2">Tags</Header>}>
              <FormField label="Tags">
                <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={TAG_I18N} />
              </FormField>
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
