/* Extensions catalog — a static directory of partner Lambda extensions. No Vyomi
 * resource backs this (there's nothing to create or list); it's reference content,
 * like the pilots' "Additional information" panels. */
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Cards from "@cloudscape-design/components/cards";
import Link from "@cloudscape-design/components/link";

const PARTNERS = [
  { name: "Datadog", description: "Monitoring and observability for Lambda functions." },
  { name: "AppDynamics", description: "Application performance monitoring." },
  { name: "HashiCorp Vault", description: "Fetch secrets at cold start." },
  { name: "Lumigo", description: "Distributed tracing and troubleshooting." },
];

export default function Extensions() {
  return (
    <ContentLayout header={<Header variant="h1" description="Lambda extensions augment a function's runtime with monitoring, security and operational tooling from AWS Partners.">Extensions</Header>}>
      <Cards
        items={PARTNERS}
        cardDefinition={{
          header: (p) => p.name,
          sections: [
            { id: "d", content: (p) => p.description },
            { id: "l", content: (p) => <Link external href="#">{`Go to ${p.name}`}</Link> },
          ],
        }}
        cardsPerRow={[{ cards: 1 }, { minWidth: 400, cards: 2 }]}
      />
    </ContentLayout>
  );
}
