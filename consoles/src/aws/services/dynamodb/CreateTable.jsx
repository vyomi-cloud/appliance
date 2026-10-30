import { useState } from "react";
import Form from "@cloudscape-design/components/form";
import Header from "@cloudscape-design/components/header";
import Container from "@cloudscape-design/components/container";
import FormField from "@cloudscape-design/components/form-field";
import Input from "@cloudscape-design/components/input";
import Select from "@cloudscape-design/components/select";
import Tiles from "@cloudscape-design/components/tiles";
import RadioGroup from "@cloudscape-design/components/radio-group";
import Checkbox from "@cloudscape-design/components/checkbox";
import Toggle from "@cloudscape-design/components/toggle";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";
import Grid from "@cloudscape-design/components/grid";
import Table from "@cloudscape-design/components/table";
import Box from "@cloudscape-design/components/box";
import Modal from "@cloudscape-design/components/modal";
import TagEditor from "@cloudscape-design/components/tag-editor";
import ContentLayout from "@cloudscape-design/components/content-layout";
import { useNotify } from "../../../common/notify.jsx";
import { follow, navigate } from "../../../common/router.js";
import { ErrorAlert, NotSimulated, NotSimulatedContainer } from "../../kit/common.jsx";
import * as api from "./api.js";

const TYPES = [{ value: "S", label: "String" }, { value: "N", label: "Number" }, { value: "B", label: "Binary" }];
const PROJECTIONS = [{ value: "ALL", label: "All attributes" }, { value: "KEYS_ONLY", label: "Only keys" }];

function KeyField({ label, typeLabel, desc, name, setName, type, setType, placeholder }) {
  const err = name && !/^[a-zA-Z0-9_.-]{1,255}$/.test(name) ? "Key names can contain only a-z, A-Z, 0-9, underscore (_), dash (-) and dot (.)" : null;
  return (
    <Grid gridDefinition={[{ colspan: 8 }, { colspan: 4 }]}>
      <FormField label={label} description={desc} errorText={err} constraintText="1 to 255 characters and case sensitive.">
        <Input value={name} onChange={({ detail }) => setName(detail.value)} placeholder={placeholder} ariaLabel={label} />
      </FormField>
      <FormField label={typeLabel}>
        <Select selectedOption={TYPES.find((t) => t.value === type)} onChange={({ detail }) => setType(detail.selectedOption.value)} options={TYPES} ariaLabel={typeLabel} />
      </FormField>
    </Grid>
  );
}

function LsiModal({ visible, onDismiss, onSave }) {
  const [lname, setLname] = useState(""); const [lsk, setLsk] = useState(""); const [lskType, setLskType] = useState("S"); const [proj, setProj] = useState("ALL");
  return (
    <Modal visible={visible} size="medium" onDismiss={onDismiss} header="Create local index"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!lname || !lsk} onClick={() => { onSave({ name: lname, sk: lsk, skType: lskType, projection: proj }); setLname(""); setLsk(""); }}>Create local index</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        <FormField label="Index name"><Input value={lname} onChange={({ detail }) => setLname(detail.value)} ariaLabel="Index name" /></FormField>
        <KeyField label="Sort key" typeLabel="Sort key type" desc="Local indexes share the table's partition key." name={lsk} setName={setLsk} type={lskType} setType={setLskType} placeholder="Enter the sort key name" />
        <FormField label="Select attribute projection">
          <Select selectedOption={PROJECTIONS.find((p) => p.value === proj)} onChange={({ detail }) => setProj(detail.selectedOption.value)} options={PROJECTIONS} ariaLabel="Select attribute projection" />
        </FormField>
      </SpaceBetween>
    </Modal>
  );
}

function GsiModal({ visible, onDismiss, onSave }) {
  const [gname, setGname] = useState(""); const [gpk, setGpk] = useState(""); const [gpkType, setGpkType] = useState("S");
  const [gsk, setGsk] = useState(""); const [gskType, setGskType] = useState("S"); const [proj, setProj] = useState("ALL");
  return (
    <Modal visible={visible} size="medium" onDismiss={onDismiss} header="Create global index"
      footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs">
        <Button variant="link" onClick={onDismiss}>Cancel</Button>
        <Button variant="primary" disabled={!gname || !gpk} onClick={() => { onSave({ name: gname, pk: gpk, pkType: gpkType, sk: gsk, skType: gskType, projection: proj }); setGname(""); setGpk(""); setGsk(""); }}>Create global index</Button>
      </SpaceBetween></Box>}>
      <SpaceBetween size="l">
        <FormField label="Index name"><Input value={gname} onChange={({ detail }) => setGname(detail.value)} ariaLabel="Index name" /></FormField>
        <KeyField label="Partition key" typeLabel="Partition key type" name={gpk} setName={setGpk} type={gpkType} setType={setGpkType} placeholder="Enter the partition key name" />
        <KeyField label="Sort key - optional" typeLabel="Sort key type" name={gsk} setName={setGsk} type={gskType} setType={setGskType} placeholder="Enter the sort key name" />
        <FormField label="Select attribute projection">
          <Select selectedOption={PROJECTIONS.find((p) => p.value === proj)} onChange={({ detail }) => setProj(detail.selectedOption.value)} options={PROJECTIONS} ariaLabel="Select attribute projection" />
        </FormField>
      </SpaceBetween>
    </Modal>
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
  const [tableClass, setTableClass] = useState("STANDARD");
  const [sseType, setSseType] = useState("OWNED");
  const [deletionProtection, setDeletionProtection] = useState(false);
  const [gsis, setGsis] = useState([]);
  const [gsiSel, setGsiSel] = useState([]);
  const [gsiModal, setGsiModal] = useState(false);
  const [lsis, setLsis] = useState([]);
  const [lsiSel, setLsiSel] = useState([]);
  const [lsiModal, setLsiModal] = useState(false);
  const [tags, setTags] = useState([]);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const nameErr = touched && !/^[a-zA-Z0-9_.-]{3,255}$/.test(name) ? "Table name must be between 3 and 255 characters long, and contain only a-z, A-Z, 0-9, underscore (_), dash (-) and dot (.)." : null;
  const pkErr = touched && !pk ? "Partition key is required." : null;
  const custom = settings === "custom";

  const submit = async () => {
    setTouched(true);
    if (!/^[a-zA-Z0-9_.-]{3,255}$/.test(name) || !pk) return;
    setBusy(true); setError(null);
    const attrs = [{ AttributeName: pk, AttributeType: pkType }, ...(sk ? [{ AttributeName: sk, AttributeType: skType }] : [])];
    const addAttr = (n, t) => { if (n && !attrs.some((a) => a.AttributeName === n)) attrs.push({ AttributeName: n, AttributeType: t }); };
    const billing = settings === "default" ? "PAY_PER_REQUEST" : mode;
    const indexes = custom ? gsis.map((g) => {
      addAttr(g.pk, g.pkType); addAttr(g.sk, g.skType);
      return { IndexName: g.name, KeySchema: [{ AttributeName: g.pk, KeyType: "HASH" }, ...(g.sk ? [{ AttributeName: g.sk, KeyType: "RANGE" }] : [])], Projection: { ProjectionType: g.projection } };
    }) : [];
    const localIndexes = custom ? lsis.map((l) => {
      addAttr(l.sk, l.skType);
      return { IndexName: l.name, KeySchema: [{ AttributeName: pk, KeyType: "HASH" }, { AttributeName: l.sk, KeyType: "RANGE" }], Projection: { ProjectionType: l.projection } };
    }) : [];
    try {
      await api.createTable({
        TableName: name,
        AttributeDefinitions: attrs,
        KeySchema: [{ AttributeName: pk, KeyType: "HASH" }, ...(sk ? [{ AttributeName: sk, KeyType: "RANGE" }] : [])],
        BillingMode: billing,
        ...(billing === "PROVISIONED" ? { ProvisionedThroughput: { ReadCapacityUnits: Number(rcu), WriteCapacityUnits: Number(wcu) } } : {}),
        ...(custom ? { TableClass: tableClass, DeletionProtectionEnabled: deletionProtection } : {}),
        ...(custom && sseType !== "OWNED" ? { SSESpecification: { Enabled: true, SSEType: "KMS" } } : {}),
        ...(indexes.length ? { GlobalSecondaryIndexes: indexes } : {}),
        ...(localIndexes.length ? { LocalSecondaryIndexes: localIndexes } : {}),
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
                <KeyField label="Partition key" typeLabel="Partition key type" desc="The partition key is part of the table's primary key. It is a hash value that is used to retrieve items from your table and allocate data across hosts for scalability and availability." name={pk} setName={setPk} type={pkType} setType={setPkType} placeholder="Enter the partition key name" />
                {pkErr && <ErrorAlert error={{ message: pkErr }} header="Missing partition key" />}
                <KeyField label="Sort key - optional" typeLabel="Sort key type" desc="You can use a sort key as the second part of a table's primary key. The sort key allows you to sort or search among all items sharing the same partition key." name={sk} setName={setSk} type={skType} setType={setSkType} placeholder="Enter the sort key name" />
              </SpaceBetween>
            </Container>

            <Container header={<Header variant="h2">Table settings</Header>}>
              <SpaceBetween size="l">
                <Tiles value={settings} onChange={({ detail }) => setSettings(detail.value)} items={[
                  { value: "default", label: "Default settings", description: "The fastest way to create your table. You can modify most of these settings after your table has been created." },
                  { value: "custom", label: "Customize settings", description: "Use these advanced features to make DynamoDB work better for your needs." },
                ]} />
                {!custom ? (
                  <Table variant="embedded" header={<Header variant="h3">Default table settings</Header>} items={defaults}
                    columnDefinitions={[{ id: "s", header: "Setting", cell: (r) => r[0] }, { id: "v", header: "Value", cell: (r) => r[1] }, { id: "e", header: "Editable after creation", cell: (r) => r[2] }]} />
                ) : (
                  <SpaceBetween size="l">
                    <FormField label="Table class">
                      <RadioGroup value={tableClass} onChange={({ detail }) => setTableClass(detail.value)} items={[
                        { value: "STANDARD", label: "DynamoDB Standard" },
                        { value: "STANDARD_INFREQUENT_ACCESS", label: "DynamoDB Standard-IA" },
                      ]} />
                    </FormField>

                    <Container header={<Header variant="h3">Read/write capacity settings</Header>}>
                      <SpaceBetween size="l">
                        <FormField label="Capacity mode">
                          <Tiles value={mode} onChange={({ detail }) => setMode(detail.value)} items={[
                            { value: "PAY_PER_REQUEST", label: "On-demand", description: "Simplify billing by paying for the actual reads and writes your application performs." },
                            { value: "PROVISIONED", label: "Provisioned", description: "Manage and optimize the price you pay by allocating read/write capacity in advance." },
                          ]} />
                        </FormField>
                        {mode === "PAY_PER_REQUEST" ? (
                          <FormField label="Maximum table throughput">
                            <SpaceBetween size="xs">
                              <Checkbox checked={false} disabled>Set maximum table throughput</Checkbox>
                              <NotSimulated feature="Maximum table throughput" note="On-demand throughput caps aren't enforced by Vyomi." />
                            </SpaceBetween>
                          </FormField>
                        ) : (
                          <SpaceBetween size="l">
                            <FormField label="Provisioned capacity units">
                              <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
                                <FormField label="Read capacity units"><Input type="number" value={rcu} onChange={({ detail }) => setRcu(detail.value)} ariaLabel="Read capacity units" /></FormField>
                                <FormField label="Write capacity units"><Input type="number" value={wcu} onChange={({ detail }) => setWcu(detail.value)} ariaLabel="Write capacity units" /></FormField>
                              </Grid>
                            </FormField>
                            <SpaceBetween size="xs">
                              <Toggle checked disabled>Read capacity auto scaling</Toggle>
                              <Toggle checked disabled>Write capacity auto scaling</Toggle>
                              <NotSimulated feature="Auto scaling" note="Application Auto Scaling for provisioned capacity isn't modeled by Vyomi; set fixed units above." />
                            </SpaceBetween>
                          </SpaceBetween>
                        )}
                      </SpaceBetween>
                    </Container>

                    <NotSimulatedContainer title="Warm throughput" note="Computed warm-throughput values aren't modeled by Vyomi." />

                    <Container header={<Header variant="h3">Secondary indexes</Header>}>
                      <SpaceBetween size="l">
                        <Table variant="embedded" items={lsis} selectionType="single" selectedItems={lsiSel} onSelectionChange={({ detail }) => setLsiSel(detail.selectedItems)}
                          trackBy="name"
                          header={<Header variant="h3" counter={`(${lsis.length})`} description={!sk ? "Add a sort key to the table's primary key above to create local indexes." : undefined} actions={
                            <SpaceBetween direction="horizontal" size="xs">
                              <Button formAction="none" disabled={!lsiSel.length} onClick={() => { setLsis(lsis.filter((l) => !lsiSel.includes(l))); setLsiSel([]); }}>Delete</Button>
                              <Button formAction="none" disabled={!sk} onClick={() => setLsiModal(true)}>Create local index</Button>
                            </SpaceBetween>
                          }>Local indexes</Header>}
                          columnDefinitions={[
                            { id: "n", header: "Name", cell: (l) => l.name },
                            { id: "pk", header: "Partition key", cell: () => pk },
                            { id: "sk", header: "Sort key", cell: (l) => l.sk },
                            { id: "p", header: "Projected attributes", cell: (l) => PROJECTIONS.find((p) => p.value === l.projection)?.label },
                          ]}
                          empty={<Box textAlign="center" color="inherit"><b>No local secondary indexes</b></Box>} />
                        <Table variant="embedded" items={gsis} selectionType="single" selectedItems={gsiSel} onSelectionChange={({ detail }) => setGsiSel(detail.selectedItems)}
                          trackBy="name"
                          header={<Header variant="h3" counter={`(${gsis.length})`} actions={
                            <SpaceBetween direction="horizontal" size="xs">
                              <Button formAction="none" disabled={!gsiSel.length} onClick={() => { setGsis(gsis.filter((g) => !gsiSel.includes(g))); setGsiSel([]); }}>Delete</Button>
                              <Button formAction="none" onClick={() => setGsiModal(true)}>Create global index</Button>
                            </SpaceBetween>
                          }>Global indexes</Header>}
                          columnDefinitions={[
                            { id: "n", header: "Name", cell: (g) => g.name },
                            { id: "pk", header: "Partition key", cell: (g) => g.pk },
                            { id: "sk", header: "Sort key", cell: (g) => g.sk || "-" },
                            { id: "p", header: "Projected attributes", cell: (g) => PROJECTIONS.find((p) => p.value === g.projection)?.label },
                          ]}
                          empty={<Box textAlign="center" color="inherit"><b>No global secondary indexes</b></Box>} />
                      </SpaceBetween>
                    </Container>

                    <Container header={<Header variant="h3">Encryption at rest</Header>}>
                      <FormField label="Encryption key management">
                        <RadioGroup value={sseType} onChange={({ detail }) => setSseType(detail.value)} items={[
                          { value: "OWNED", label: "Owned by Amazon DynamoDB" },
                          { value: "AWS_KMS", label: "AWS managed key" },
                          { value: "CUSTOMER_KMS", label: "Stored in your account, and owned and managed by you" },
                        ]} />
                      </FormField>
                    </Container>

                    <Container header={<Header variant="h3">Deletion protection</Header>}>
                      <Checkbox checked={deletionProtection} onChange={({ detail }) => setDeletionProtection(detail.checked)}>Turn on deletion protection</Checkbox>
                    </Container>
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
      <LsiModal visible={lsiModal} onDismiss={() => setLsiModal(false)} onSave={(l) => { setLsis([...lsis, l]); setLsiModal(false); }} />
      <GsiModal visible={gsiModal} onDismiss={() => setGsiModal(false)} onSave={(g) => { setGsis([...gsis, g]); setGsiModal(false); }} />
    </ContentLayout>
  );
}
