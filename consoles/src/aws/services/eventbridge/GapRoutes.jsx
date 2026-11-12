/* The Learn and Quick starts developer pages. They are editorial in the real console (no resource behind them), so they are rendered
 * as editorial pages whose every card links to a real Vyomi page or create flow - nothing here pretends to be a backend feature. */
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Cards from "@cloudscape-design/components/cards";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Container from "@cloudscape-design/components/container";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import { follow } from "../../../common/router.js";

const CONCEPTS = [
  { title: "Event buses", body: "A bus receives events from your applications, AWS services and SaaS partners and routes them with rules. Every account has a default bus.", href: "#/eventbridge/event-buses", cta: "Open event buses" },
  { title: "Rules", body: "A rule matches events with an event pattern (or fires on a schedule) and delivers matches to up to five targets such as Lambda, SQS, SNS, Step Functions or another bus.", href: "#/eventbridge/rules", cta: "Open rules" },
  { title: "Pipes", body: "A pipe connects one source (SQS, Kinesis, DynamoDB streams) to one target, with optional filtering and enrichment.", href: "#/eventbridge/pipes", cta: "Open pipes" },
  { title: "Scheduler", body: "Create one-time or recurring schedules (rate, cron, at) that invoke a target, organised in schedule groups.", href: "#/eventbridge/schedules", cta: "Open schedules" },
  { title: "Archive and replay", body: "Archive the events that match a pattern and replay them later onto the same bus.", href: "#/eventbridge/archives", cta: "Open archives" },
  { title: "Schema registry", body: "Registries hold OpenAPI / JSON Schema definitions of your events; discoverers infer schemas from live traffic.", href: "#/eventbridge/schemas", cta: "Open schemas" },
];

const STARTS = [
  { title: "Create a custom event bus", body: "A bus for your own application's events.", href: "#/eventbridge/create-event-bus", cta: "Create event bus" },
  { title: "React to events with a rule", body: "Match an event pattern and send it to a target.", href: "#/eventbridge/create-rule", cta: "Create rule" },
  { title: "Run something on a schedule", body: "A recurring schedule that invokes a target.", href: "#/eventbridge/create-schedule", cta: "Create schedule" },
  { title: "Connect a queue to a target", body: "Poll an SQS queue (or stream) and deliver to a target with a pipe.", href: "#/eventbridge/create-pipe", cta: "Create pipe" },
  { title: "Try an event pattern", body: "Test patterns against sample events in the sandbox before you ship a rule.", href: "#/eventbridge/sandbox", cta: "Open sandbox" },
  { title: "Archive a bus's events", body: "Keep matching events so you can replay them later.", href: "#/eventbridge/create-archive", cta: "Create archive" },
];

const page = (title, description, items) => () => (
  <ContentLayout header={<Header variant="h1" description={description}>{title}</Header>}>
    <SpaceBetween size="l">
      <Container><Box variant="small" color="text-body-secondary">This is a guide page: every card opens the real Vyomi page or create flow.</Box></Container>
      <Cards cardsPerRow={[{ cards: 1 }, { minWidth: 700, cards: 2 }, { minWidth: 1100, cards: 3 }]} items={items} trackBy="title"
        cardDefinition={{ header: (i) => i.title, sections: [{ id: "b", content: (i) => i.body }, { id: "a", content: (i) => <Button href={i.href} onFollow={follow}>{i.cta}</Button> }] }} />
    </SpaceBetween>
  </ContentLayout>
);

const PAGES = [
  { id: "learn", path: "learn", title: "Learn", component: page("Learn", "The main EventBridge concepts and where each one lives in this console.", CONCEPTS) },
  { id: "quick-starts", path: "quick-starts", title: "Quick starts", component: page("Quick starts", "Common first tasks, each one a real create flow.", STARTS) },
];

export default PAGES;
