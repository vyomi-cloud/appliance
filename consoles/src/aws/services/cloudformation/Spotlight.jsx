/* CloudFormation Spotlight: a gallery of Vyomi's own curated sample templates (not AWS's editorial feed). The Filters panel is real:
 * filter by tag, sort by newest/name, editor's-choice-only and bookmarks-only (bookmarks are per-browser). "Create stack" runs the
 * template through the real CreateStack. Every template only uses resource types the Vyomi CloudFormation core deploys. */
import { useMemo, useState } from "react";
import Alert from "@cloudscape-design/components/alert";
import Badge from "@cloudscape-design/components/badge";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Cards from "@cloudscape-design/components/cards";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import FormField from "@cloudscape-design/components/form-field";
import Header from "@cloudscape-design/components/header";
import Input from "@cloudscape-design/components/input";
import Modal from "@cloudscape-design/components/modal";
import Multiselect from "@cloudscape-design/components/multiselect";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Toggle from "@cloudscape-design/components/toggle";
import { ErrorAlert } from "../../kit/common.jsx";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";

const tpl = (desc, resources) => JSON.stringify({ AWSTemplateFormatVersion: "2010-09-09", Description: desc, Resources: resources }, null, 2);
export const CATALOG = [
  { id: "s3-versioned", title: "Versioned S3 bucket", added: "2026-10-30", editors: true, tags: ["Storage", "Getting started"], desc: "A private S3 bucket with versioning enabled.",
    body: tpl("Versioned S3 bucket", { Bucket: { Type: "AWS::S3::Bucket", Properties: { VersioningConfiguration: { Status: "Enabled" } } } }) },
  { id: "ddb-table", title: "DynamoDB on-demand table", added: "2026-10-28", editors: true, tags: ["Database", "Getting started"], desc: "An on-demand DynamoDB table with a string hash key.",
    body: tpl("DynamoDB on-demand table", { Table: { Type: "AWS::DynamoDB::Table", Properties: { BillingMode: "PAY_PER_REQUEST", AttributeDefinitions: [{ AttributeName: "id", AttributeType: "S" }], KeySchema: [{ AttributeName: "id", KeyType: "HASH" }] } } }) },
  { id: "sns-sqs", title: "SNS topic fanning out to an SQS queue", added: "2026-10-26", editors: false, tags: ["Messaging"], desc: "A topic, a queue and the subscription between them.",
    body: tpl("SNS to SQS fan-out", { Topic: { Type: "AWS::SNS::Topic" }, Queue: { Type: "AWS::SQS::Queue" }, Sub: { Type: "AWS::SNS::Subscription", Properties: { TopicArn: { Ref: "Topic" }, Protocol: "sqs", Endpoint: { "Fn::GetAtt": ["Queue", "Arn"] } } } }) },
  { id: "sqs-dlq", title: "SQS queue with a dead-letter queue", added: "2026-10-24", editors: true, tags: ["Messaging", "Getting started"], desc: "A work queue that moves poison messages to a DLQ after 3 receives.",
    body: tpl("SQS with DLQ", { Dlq: { Type: "AWS::SQS::Queue" }, Work: { Type: "AWS::SQS::Queue", Properties: { RedrivePolicy: { deadLetterTargetArn: { "Fn::GetAtt": ["Dlq", "Arn"] }, maxReceiveCount: 3 } } } }) },
  { id: "ssm-config", title: "SSM parameters for app configuration", added: "2026-10-20", editors: false, tags: ["Management"], desc: "Two SSM parameters holding application settings.",
    body: tpl("App config in SSM", { Region: { Type: "AWS::SSM::Parameter", Properties: { Type: "String", Value: "us-east-1", Name: "/app/region" } }, Mode: { Type: "AWS::SSM::Parameter", Properties: { Type: "String", Value: "production", Name: "/app/mode" } } }) },
];
const ALL_TAGS = [...new Set(CATALOG.flatMap((c) => c.tags))].sort();
const SORTS = [{ value: "newest", label: "Sort by newest" }, { value: "name", label: "Sort by name" }];
const KEY = "vyomi.cfn.spotlight.bookmarks";
const loadMarks = () => { try { return new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); } catch { return new Set(); } };
const saveMarks = (s) => { try { localStorage.setItem(KEY, JSON.stringify([...s])); } catch { /* per-viewer convenience only */ } };

export default function Spotlight() {
  const notify = useNotify();
  const [tags, setTags] = useState([]);
  const [sort, setSort] = useState(SORTS[0]);
  const [editorsOnly, setEditorsOnly] = useState(false);
  const [marksOnly, setMarksOnly] = useState(false);
  const [marks, setMarks] = useState(loadMarks);
  const [launch, setLaunch] = useState(null);
  const [name, setName] = useState("");
  const [err, setErr] = useState(null);
  const items = useMemo(() => {
    let xs = CATALOG.filter((c) => (!tags.length || tags.every((t) => c.tags.includes(t.value))) && (!editorsOnly || c.editors) && (!marksOnly || marks.has(c.id)));
    xs = [...xs].sort((a, b) => (sort.value === "name" ? a.title.localeCompare(b.title) : b.added.localeCompare(a.added)));
    return xs;
  }, [tags, sort, editorsOnly, marksOnly, marks]);
  const toggleMark = (id) => { const n = new Set(marks); n.has(id) ? n.delete(id) : n.add(id); setMarks(n); saveMarks(n); };
  const create = async () => {
    try { setErr(null); await api.createStack({ name, templateBody: launch.body }); notify.success(`Creating stack "${name}" from "${launch.title}".`); setLaunch(null); navigate("cloudformation", "stacks", name); }
    catch (e) { setErr(e); }
  };
  return (
    <ContentLayout header={<Header variant="h1" description="Vyomi's curated sample templates. Pick one and create a real stack from it.">CloudFormation Spotlight</Header>}>
      <SpaceBetween size="l">
        <Alert type="info">This gallery is Vyomi's own - AWS's editorial Spotlight feed is not reproduced. Bookmarks are stored in this browser only.</Alert>
        <Container header={<Header variant="h2">Filters</Header>}>
          <SpaceBetween size="m" direction="horizontal">
            <FormField label="Filter by"><Multiselect ariaLabel="Filter by tag" selectedOptions={tags} options={ALL_TAGS.map((t) => ({ value: t, label: t }))} onChange={({ detail }) => setTags(detail.selectedOptions)} placeholder="All tags" /></FormField>
            <FormField label="Sort by"><Select ariaLabel="Sort by" selectedOption={sort} options={SORTS} onChange={({ detail }) => setSort(detail.selectedOption)} /></FormField>
            <FormField label=" "><Toggle checked={editorsOnly} onChange={({ detail }) => setEditorsOnly(detail.checked)}>Show editor's choice only</Toggle></FormField>
            <FormField label=" "><Toggle checked={marksOnly} onChange={({ detail }) => setMarksOnly(detail.checked)}>Show bookmarks only</Toggle></FormField>
          </SpaceBetween>
        </Container>
        <Cards items={items} trackBy="id" cardsPerRow={[{ cards: 1 }, { minWidth: 700, cards: 2 }]} header={<Header counter={`(${items.length})`}>Templates</Header>}
          empty={<Box textAlign="center" color="inherit">No templates match these filters.</Box>}
          cardDefinition={{
            header: (c) => <SpaceBetween size="xs" direction="horizontal">{c.title}{c.editors && <Badge color="blue">Editor's choice</Badge>}</SpaceBetween>,
            sections: [
              { id: "d", content: (c) => c.desc },
              { id: "t", content: (c) => c.tags.map((t) => <Badge key={t}>{t}</Badge>) },
              { id: "a", header: "Added", content: (c) => c.added },
              { id: "x", content: (c) => <SpaceBetween direction="horizontal" size="xs">
                <Button variant="primary" onClick={() => { setErr(null); setName(`spotlight-${c.id}`); setLaunch(c); }}>Create stack</Button>
                <Button iconName={marks.has(c.id) ? "star-filled" : "star"} onClick={() => toggleMark(c.id)} ariaLabel={`${marks.has(c.id) ? "Remove bookmark" : "Bookmark"} ${c.title}`}>{marks.has(c.id) ? "Bookmarked" : "Bookmark"}</Button></SpaceBetween> },
            ],
          }} />
      </SpaceBetween>
      <Modal visible={!!launch} onDismiss={() => setLaunch(null)} size="large" header={`Create stack from "${launch?.title}"`}
        footer={<Box float="right"><SpaceBetween direction="horizontal" size="xs"><Button variant="link" onClick={() => setLaunch(null)}>Cancel</Button><Button variant="primary" onClick={create}>Create stack</Button></SpaceBetween></Box>}>
        <SpaceBetween size="m"><ErrorAlert error={err} />
          <FormField label="Stack name"><Input ariaLabel="Stack name" value={name} onChange={({ detail }) => setName(detail.value)} /></FormField>
          <Box variant="code"><pre style={{ margin: 0, maxHeight: 280, overflow: "auto" }}>{launch?.body}</pre></Box></SpaceBetween>
      </Modal>
    </ContentLayout>
  );
}
