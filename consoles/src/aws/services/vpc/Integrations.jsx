/* VPC > Integrations: this VPC's transit gateway attachments and whether each gateway is registered in an AWS Network Manager global network. */
import Alert from "@cloudscape-design/components/alert";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { follow } from "../../../common/router.js";
import { awsQuery, asList } from "../../../common/wire.js";
import * as nm from "../networkmanager/api.js";

export default function VpcIntegrations({ vpcId }) {
  const t = useAsync(async () => {
    const r = await awsQuery("ec2", "DescribeTransitGatewayVpcAttachments", {}, { version: "2016-11-15" });
    const atts = asList(r.DescribeTransitGatewayVpcAttachmentsResponse?.transitGatewayVpcAttachments?.item).filter((a) => a.vpcId === vpcId);
    const regs = [];
    for (const g of await nm.listGlobalNetworks()) for (const x of await nm.listRegistrations(g.GlobalNetworkId)) regs.push({ ...x, gid: g.GlobalNetworkId });
    return atts.map((a) => ({ ...a, reg: regs.find((x) => x.TransitGatewayArn.endsWith("/" + a.transitGatewayId)) }));
  }, [vpcId]);
  return (
    <SpaceBetween size="m">
      <ResourceTable resourceName="Transit gateway attachments" variant="container" items={t.data || []} loading={t.loading} error={t.error} onRefresh={t.reload} trackBy="transitGatewayAttachmentId"
        empty={{ title: "No integrations", description: "This VPC is not attached to a transit gateway." }}
        columns={[{ id: "a", header: "Attachment", isRowHeader: true, cell: (a) => a.transitGatewayAttachmentId }, { id: "g", header: "Transit gateway", cell: (a) => a.transitGatewayId },
          { id: "s", header: "State", cell: (a) => a.state },
          { id: "n", header: "Network Manager", cell: (a) => a.reg ? <Link href={`#/networkmanager/global-networks/view?id=${a.reg.gid}`} onFollow={follow}>Registered in {a.reg.gid}</Link> : "Not registered" }]} />
      <Alert type="info">Network Manager registration is modelled. Third-party partner integrations (Aviatrix, Kentik and similar) are external services and are not simulated.</Alert>
    </SpaceBetween>
  );
}
