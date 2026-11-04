import { useState } from "react";
import Header from "@cloudscape-design/components/header";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Tabs from "@cloudscape-design/components/tabs";
import Button from "@cloudscape-design/components/button";
import { useAsync } from "../../../common/useAsync.js";
import { href, follow } from "../../../common/router.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { ProductBrowser } from "../../kit/MarketplaceBrowser.jsx";
import * as mp from "../../kit/marketplaceApi.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import * as api from "./api.js";

export default function AmiCatalog() {
  const [tab, setTab] = useState("quickstart");
  const t = useAsync(() => api.describeImages(), []);
  const images = t.data || [];
  const quickstart = images.filter((x) => x.imageOwnerId === "amazon");
  const mine = images.filter((x) => x.imageOwnerId === "123456789012");
  const community = useAsync(() => mp.listEntities("CommunityAmi"), []);

  const amiTable = (items, loading = t.loading) => (
    <ResourceTable
      resourceName="AMIs"
      items={items}
      loading={loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="imageId"
      filterPlaceholder='Search for an AMI by entering a search term e.g. "Windows"'
      columns={[
        { id: "ami", header: "AMI", isRowHeader: true, cell: (x) => `${x.name} (${x.imageId})` },
        { id: "select", header: "Select", cell: (x) => <Button href={href("ec2", "launch-instance") + `?ami=${x.imageId}`} onFollow={follow}>Select</Button> },
      ]}
      empty={{ title: "No AMIs" }}
    />
  );

  return (
    <ContentLayout header={<Header variant="h1">AMI Catalog</Header>}>
      <Tabs activeTabId={tab} onChange={({ detail }) => setTab(detail.activeTabId)} tabs={[
        { id: "quickstart", label: `Quickstart AMIs (${quickstart.length})`, content: amiTable(quickstart) },
        { id: "mine", label: `My AMIs (${mine.length})`, content: amiTable(mine) },
        { id: "marketplace", label: "AWS Marketplace AMIs", content: <CapabilityContainer id="ec2.ami-catalog.marketplace-community" title="AWS Marketplace AMIs"><ProductBrowser entityType="AmiProduct" noun="AMIs" onChanged={t.reload} /></CapabilityContainer> },
        { id: "community", label: "Community AMIs", content: <CapabilityContainer id="ec2.ami-catalog.marketplace-community" title="Community AMIs">{amiTable((community.data || []).map((c) => ({ imageId: c.EntityId, name: c.Name })), community.loading)}</CapabilityContainer> },
      ]} />
    </ContentLayout>
  );
}
