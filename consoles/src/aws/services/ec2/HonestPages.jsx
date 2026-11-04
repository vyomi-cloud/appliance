/* Pages the real EC2 console declares but Vyomi does not simulate — out of scope for this
 * console (purchasing/capacity-planning products, load balancing/Auto Scaling which are their
 * own AWS services, and a handful of ad-hoc "Vyomi can't do this" destinations linked to from
 * elsewhere in the EC2 console). Each renders ONLY its title + an honest gap panel. */
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import { NotSimulatedContainer } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";

const page = (title, body) => () => (
  <ContentLayout header={<Header variant="h1">{title}</Header>}>{body}</ContentLayout>
);
const honest = (title, feature) => page(title, <NotSimulatedContainer title={title} feature={feature} />);
const capability = (title, id) => page(title, <CapabilityContainer id={id} title={title} />);

export const SavingsPlans = capability("Savings Plans", "ec2.purchasing.savings-plans");
export const UltraServers = capability("UltraServers", "ec2.purchasing.ultraservers");
export const CapacityManager = capability("Capacity Manager", "ec2.purchasing.capacity-manager");

export const MigrateAServer = honest("Migrate a server", "AWS Application Migration Service");
export const ImageBuilder = honest("EC2 Image Builder", "EC2 Image Builder pipelines");
