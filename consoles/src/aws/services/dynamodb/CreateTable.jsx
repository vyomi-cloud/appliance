import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Tiles from "@cloudscape-design/components/tiles";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Grid from "@cloudscape-design/components/grid";
import Table from "@cloudscape-design/components/table";
import TagEditor from "@cloudscape-design/components/tag-editor";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert } from "../../kit/common.jsx";
import * as api from "./api.js";

const TYPES = [{ value: "S", label: "String" }, { value: "N", label: "Number" }, { value: "B", label: "Binary" }];

function KeyField({ label, desc, name, setName, type, setType, optional }) {
  const err = name && !/^[a-zA-Z0-9_.-]{1,255}$/.test(name) ? "Key names can contain only a-z, A-Z, 0-9, underscore (_), dash (-) and dot (.)" : null;
  return (
    <FormField label={label} description={desc} errorText={err} constraintText="1 to 255 characters and case sensitive.">
      <Grid gridDefinition={[{ colspan: 8 }, { colspan: 4 }]}>
        <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder={optional ? "Enter the sort key name" : "Enter the partition key name"} ariaLabel={label} />
        <Select selectedOption={TYPES.find((t) => t.value === type)} onChange={({ detail }) => setType(detail.selectedOption.value)} options={TYPES} ariaLabel={`${label} type`} />
      </Grid>
    </FormField>
  );
}

export default function CreateTable() {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [pk, setPk] = useState(""); const [pkType, setPkType] = useState("S");
  const [sk, setSk] = useState(""); const [skType, setSkType] = useState("S");
  const [settings, setSettings] = useState("default");
  const [mode, setMode] = useState("PAY_PER_REQUEST");
  const [rcu, setRcu] = useState("5"); const [wcu, setWcu] = useState("5");
  const [tags, setTags] = useState([]);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = touched && !/^[a-zA-Z0-9_.-]{3,255}$/.test(name) ? "Table name must be between 3 and 255 characters long, and contain only a-z, A-Z, 0-9, underscore (_), dash (-) and dot (.)." : null;
  const pkErr = touched && !pk ? "Partition key is required." : null;

  const submit = async () => {
    setTouched(true);
    if (!/^[a-zA-Z0-9_.-]{3,255}$/.test(name) || !pk) return;
    setBusy(true); setError(null);
    const attrs = [{ AttributeName: pk, AttributeType: pkType }, ...(sk ? [{ AttributeName: sk, AttributeType: skType }] : [])];
    const billing = settings === "default" ? "PAY_PER_REQUEST" : mode;
    try {
      await api.createTable({
        TableName: name,
        AttributeDefinitions: attrs,
        KeySchema: [{ AttributeName: pk, KeyType: "HASH" }, ...(sk ? [{ AttributeName: sk, KeyType: "RANGE" }] : [])],
        BillingMode: billing,
        ...(billing === "PROVISIONED" ? { ProvisionedThroughput: { ReadCapacityUnits: Number(rcu), WriteCapacityUnits: Number(wcu) } } : {}),
        ...(tags.filter((t) => !t.markedForRemoval && t.key).length ? { Tags: tags.filter((t) => !t.markedForRemoval && t.key).map((t) => ({ Key: t.key, Value: t.value })) } : {}),
      });
      notify.success(`Creating the ${name} table. It will be available for use shortly.`);
      navigate("dynamodb", "tables");
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  };

  const defaults = [
    ["Table class", "DynamoDB Standard", "Yes"], ["Capacity mode", "On-demand", "Yes"], ["Read capacity", "-", "Yes"], ["Write capacity", "-", "Yes"],
    ["Auto scaling", "Not applicable", "Yes"], ["Local secondary indexes", "-", "No"], ["Global secondary indexes", "-", "Yes"],
    ["Encryption key management", "Owned by Amazon DynamoDB", "Yes"], ["Deletion protection", "Off", "Yes"], ["Resource-based policy", "Not active", "Yes"],
  ];

  return (
    <ContentLayout header={<Header variant="h1">Create table</Header>}>
      <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Form errorText={error && <ErrorAlert error={error} />} actions={
          <SpaceBetween direction="horizontal" size="xs">
            <Button formAction="none" variant="link" href="#/dynamodb/tables" onFollow={follow}>Cancel</Button>
            <Button variant="primary" loading={busy}>Create table</Button>
          </SpaceBetween>
        }>
          <SpaceBetween size="l">
            <Container header={<Header variant="h2">Table details</Header>}>
              <SpaceBetween size="l">
                <FormField label="Table name" description="This will be used to identify your table." errorText={nameErr}
                  constraintText="Between 3 and 255 characters, containing only letters, numbers, underscores (_), hyphens (-), and periods (.).">
                  <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder="Enter a table name" ariaLabel="Table name" />
                </FormField>
                <KeyField label="Partition key" desc="The partition key is part of the table's primary key. It is a hash value that is used to retrieve items from your table and allocate data across hosts for scalability and availability." name={pk} setName={setPk} type={pkType} setType={setPkType} />
                {pkErr && <ErrorAlert error={{ message: pkErr }} header="Missing partition key" />}
                <KeyField label="Sort key - optional" desc="You can use a sort key as the second part of a table's primary key. The sort key allows you to sort or search among all items sharing the same partition key." name={sk} setName={setSk} type={skType} setType={setSkType} optional />
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Table settings</Header>}>
              <SpaceBetween size="l">
                <Tiles value={settings} onChange={({ detail }) => setSettings(detail.value)} items={[
                  { value: "default", label: "Default settings", description: "The fastest way to create your table. You can modify most of these settings after your table has been created." },
                  { value: "custom", label: "Customize settings", description: "Use these advanced features to make DynamoDB work better for your needs." },
                ]} />
                {settings === "default" ? (
                  <Table variant="embedded" header={<Header variant="h3">Default table settings</Header>} items={defaults}
                    columnDefinitions={[{ id: "s", header: "Setting", cell: (r) => r[0] }, { id: "v", header: "Value", cell: (r) => r[1] }, { id: "e", header: "Editable after creation", cell: (r) => r[2] }]} />
                ) : (
                  <SpaceBetween size="l">
                    <FormField label="Read/write capacity settings">
                      <Tiles value={mode} onChange={({ detail }) => setMode(detail.value)} items={[
                        { value: "PAY_PER_REQUEST", label: "On-demand", description: "Simplify billing by paying for the actual reads and writes your application performs." },
                        { value: "PROVISIONED", label: "Provisioned", description: "Manage and optimize the price you pay by allocating read/write capacity in advance." },
                      ]} />
                    </FormField>
                    {mode === "PROVISIONED" && (
                      <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
                        <FormField label="Read capacity units"><Input type="number" value={rcu} onChange={({ detail }) => setRcu(detail.value)} /></FormField>
                        <FormField label="Write capacity units"><Input type="number" value={wcu} onChange={({ detail }) => setWcu(detail.value)} /></FormField>
                      </Grid>
                    )}
                  </SpaceBetween>
                )}
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2" description="Tags are pairs of keys and optional values that you can assign to AWS resources.">Tags</Header>}>
              <TagEditor tags={tags} onChange={({ detail }) => setTags(detail.tags)} i18nStrings={{ keyHeader: "Key", valueHeader: "Value - optional", addButton: "Add new tag", removeButton: "Remove", undoButton: "Undo", undoPrompt: "This tag will be removed upon saving changes", loading: "Loading tags", keyPlaceholder: "Enter key", valuePlaceholder: "Enter value", emptyTags: "No tags are associated with the resource.", tooManyKeysSuggestion: "You have more keys than can be displayed", tooManyValuesSuggestion: "You have more values than can be displayed", keysSuggestionLoading: "Loading tag keys", keysSuggestionError: "Tag keys could not be retrieved", valuesSuggestionLoading: "Loading tag values", valuesSuggestionError: "Tag values could not be retrieved", emptyKeyError: "You must specify a tag key", maxKeyCharLengthError: "The maximum number of characters you can use in a tag key is 128.", maxValueCharLengthError: "The maximum number of characters you can use in a tag value is 256.", duplicateKeyError: "You must specify a unique tag key.", invalidKeyError: "Invalid key.", invalidValueError: "Invalid value.", awsPrefixError: "Cannot start with aws:", tagLimit: (a) => `You can add up to ${a} more tags.`, tagLimitReached: () => "You have reached the limit of 50 tags.", tagLimitExceeded: () => "You have exceeded the limit of 50 tags." }} />
            </Container>
          </SpaceBetween>
        </Form>
      </form>
    </ContentLayout>
  );
}
