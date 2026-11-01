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

export const Events = honest("Events", "Scheduled maintenance events");
export const SpotRequests = capability("Spot Requests", "ec2.purchasing-options");
export const SavingsPlans = capability("Savings Plans", "ec2.purchasing-options");
export const ReservedInstances = capability("Reserved Instances", "ec2.purchasing-options");
export const DedicatedHosts = capability("Dedicated Hosts", "ec2.purchasing-options");
export const CapacityReservations = capability("Capacity Reservations", "ec2.purchasing-options");
export const UltraServers = capability("UltraServers", "ec2.purchasing-options");
export const CapacityManager = capability("Capacity Manager", "ec2.purchasing-options");
export const LifecycleManager = capability("Lifecycle Manager", "ec2.lifecycle-manager");
export const CreateLifecyclePolicy = capability("Create default policy", "ec2.lifecycle-manager");
export const TrustStores = capability("Trust stores", "ec2.trust-stores");
export const CreateTrustStore = capability("Create trust store", "ec2.trust-stores");
export const AutoScalingGroups = capability("Auto Scaling groups", "ec2.auto-scaling");

export const MigrateAServer = honest("Migrate a server", "AWS Application Migration Service");
export const RecycleBin = honest("Recycle Bin", "Recycle Bin for deleted AMIs/snapshots/volumes");
export const ImageBuilder = honest("EC2 Image Builder", "EC2 Image Builder pipelines");
export const InstanceTypeFinder = honest("Instance type finder", "The guided instance-type recommendation tool");
export const CreateIamProfile = honest("Create IAM profile", "IAM instance profile creation (use the IAM console)");
export const CompareSecurityGroupRules = honest("Compare security group rules", "Side-by-side security group rule comparison");
