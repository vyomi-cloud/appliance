/* S3 account-level pages: AWS Marketplace for S3 (Vyomi SaaS spaces, core/marketplace_core.py) and the Get started page.
 * Capability ids: s3.account.marketplace, s3.account.get-started. */
import { useState } from "react";
import Box from "@cloudscape-design/components/box";
import Button from "@cloudscape-design/components/button";
import Cards from "@cloudscape-design/components/cards";
import ColumnLayout from "@cloudscape-design/components/column-layout";
import Container from "@cloudscape-design/components/container";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Table from "@cloudscape-design/components/table";
import Tabs from "@cloudscape-design/components/tabs";
import { useAsync } from "../../../common/useAsync.js";
import { follow, href } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ProductBrowser, SubscriptionsTable } from "../../kit/MarketplaceBrowser.jsx";
import * as api from "./api.js";

export function S3Marketplace() {
  const [tab, setTab] = useState("discover");
  const [rev, setRev] = useState(0);
  return (
    <ContentLayout header={<Header variant="h1" description="Subscribe to Vyomi SaaS spaces: simulated third-party APIs you can point your app at while developing against the cloud.">AWS Marketplace for S3</Header>}>
      <CapabilityContainer id="s3.account.marketplace" title="Marketplace">
        <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
          { id: "discover", label: "Discover products", content: <ProductBrowser key={`d${rev}`} entityType="SaaSProduct" noun="SaaS spaces" onChanged={() => setRev((x) => x + 1)} /> },
          { id: "subs", label: "Manage subscriptions", content: <SubscriptionsTable key={`s${rev}`} onChanged={() => setRev((x) => x + 1)} /> },
        ]} />
      </CapabilityContainer>
    </ContentLayout>
  );
}

const CLASSES = [
  ["S3 Standard", "Frequently accessed data", "Milliseconds", "3 AZs"],
  ["S3 Intelligent-Tiering", "Unknown or changing access", "Milliseconds", "3 AZs"],
  ["S3 Standard-IA", "Infrequently accessed data", "Milliseconds", "3 AZs"],
  ["S3 One Zone-IA", "Re-creatable infrequent data", "Milliseconds", "1 AZ"],
  ["S3 Glacier Instant Retrieval", "Archive, instant access", "Milliseconds", "3 AZs"],
  ["S3 Glacier Deep Archive", "Long-term archive", "Hours", "3 AZs"],
];

export function S3GetStarted() {
  const b = useAsync(() => api.listBuckets(), []);
  const steps = [
    ["1. Create a bucket", "Buckets hold your objects. Names are globally unique.", "Create bucket", href("s3", "create")],
    ["2. Upload objects", "Add files or folders to a bucket.", "View buckets", href("s3", "buckets")],
    ["3. Secure and share", "Block Public Access, bucket policies and access points control who can read.", "Account settings", href("s3", "settings")],
    ["4. Analyse and optimise", "Storage Lens dashboards show usage and activity trends.", "Storage Lens", href("s3", "lens", "dashboards")],
  ];
  return (
    <ContentLayout header={<Header variant="h1" description="Object storage built to store and retrieve any amount of data from anywhere.">Amazon S3</Header>}>
      <SpaceBetween size="l">
        <CapabilityContainer id="s3.account.get-started" title="Get started">
          <ColumnLayout columns={3} variant="text-grid">
            <div><Box variant="awsui-key-label">Buckets in this account</Box><Box variant="awsui-value-large" data-testid="gs-bucket-count">{b.loading ? "-" : (b.data || []).length}</Box></div>
            <div><Box variant="awsui-key-label">Region</Box><div>us-east-1</div></div>
            <div><Box variant="awsui-key-label">Create</Box><Button variant="primary" href={href("s3", "create")} onFollow={follow}>Create bucket</Button></div>
          </ColumnLayout>
        </CapabilityContainer>
        <Cards header={<Header variant="h2">How it works</Header>} cardsPerRow={[{ cards: 1 }, { minWidth: 600, cards: 2 }, { minWidth: 1000, cards: 4 }]} items={steps}
          cardDefinition={{ header: (s) => s[0], sections: [{ id: "d", content: (s) => s[1] }, { id: "a", content: (s) => <Button href={s[3]} onFollow={follow}>{s[2]}</Button> }] }} />
        <Table variant="container" header={<Header variant="h2">Storage classes</Header>} items={CLASSES} trackBy={(x) => x[0]}
          columnDefinitions={[{ id: "n", header: "Storage class", cell: (x) => x[0] }, { id: "u", header: "Designed for", cell: (x) => x[1] }, { id: "l", header: "Retrieval", cell: (x) => x[2] }, { id: "z", header: "Availability Zones", cell: (x) => x[3] }]} />
      </SpaceBetween>
    </ContentLayout>
  );
}
