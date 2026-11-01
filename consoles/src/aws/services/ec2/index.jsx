import Dashboard from "./Dashboard.jsx";
import Instances from "./Instances.jsx";
import InstanceDetail from "./InstanceDetail.jsx";
import LaunchInstance from "./LaunchInstance.jsx";
import CreateImage from "./CreateImage.jsx";
import { InstanceTypes, InstanceTypeDetail } from "./InstanceTypes.jsx";
import { LaunchTemplates, CreateLaunchTemplate } from "./LaunchTemplates.jsx";
import { Amis, AmiDetail } from "./Amis.jsx";
import AmiCatalog from "./AmiCatalog.jsx";
import { Volumes, VolumeDetail, CreateVolume } from "./Volumes.jsx";
import { Snapshots, CreateSnapshot } from "./Snapshots.jsx";
import { SecurityGroups, SecurityGroupDetail, CreateSecurityGroup, EditInboundRules, EditOutboundRules } from "./SecurityGroups.jsx";
import { ElasticIps, AllocateElasticIp } from "./ElasticIps.jsx";
import { PlacementGroups, CreatePlacementGroup } from "./PlacementGroups.jsx";
import { KeyPairs, CreateKeyPair, ImportKeyPair } from "./KeyPairs.jsx";
import NetworkInterfaces from "./NetworkInterfaces.jsx";
import Settings from "./Settings.jsx";
import { LoadBalancers, LoadBalancerDetail, CreateLoadBalancer } from "./LoadBalancers.jsx";
import { TargetGroups, TargetGroupDetail, CreateTargetGroup } from "./TargetGroups.jsx";
import { TrustStores, CreateTrustStore } from "./TrustStores.jsx";
import { LifecycleManager, CreateLifecyclePolicy } from "./LifecycleManager.jsx";
import { AutoScalingGroups, AutoScalingGroupDetail, CreateAutoScalingGroup } from "./AutoScaling.jsx";
import * as Honest from "./HonestPages.jsx";

const crumb = (text, ...path) => ({ text, href: `#/ec2/${path.join("/")}` });
const base = [crumb("EC2", "")];

export default {
  nav: [
    { type: "link", text: "Dashboard", href: "#/ec2/dashboard" },
    { type: "link", text: "Events", href: "#/ec2/events" },
    { type: "section", text: "Instances", items: [
      { type: "link", text: "Instances", href: "#/ec2/instances" },
      { type: "link", text: "Instance Types", href: "#/ec2/instance-types" },
      { type: "link", text: "Launch Templates", href: "#/ec2/launch-templates" },
      { type: "link", text: "Spot Requests", href: "#/ec2/spot-requests" },
      { type: "link", text: "Savings Plans", href: "#/ec2/savings-plans" },
      { type: "link", text: "Reserved Instances", href: "#/ec2/reserved-instances" },
      { type: "link", text: "Dedicated Hosts", href: "#/ec2/dedicated-hosts" },
      { type: "link", text: "Capacity Reservations", href: "#/ec2/capacity-reservations" },
      { type: "link", text: "UltraServers", href: "#/ec2/ultraservers" },
      { type: "link", text: "Capacity Manager", href: "#/ec2/capacity-manager" },
    ] },
    { type: "section", text: "Images", items: [
      { type: "link", text: "AMIs", href: "#/ec2/amis" },
      { type: "link", text: "AMI Catalog", href: "#/ec2/ami-catalog" },
    ] },
    { type: "section", text: "Elastic Block Store", items: [
      { type: "link", text: "Volumes", href: "#/ec2/volumes" },
      { type: "link", text: "Snapshots", href: "#/ec2/snapshots" },
      { type: "link", text: "Lifecycle Manager", href: "#/ec2/lifecycle-manager" },
    ] },
    { type: "section", text: "Network & Security", items: [
      { type: "link", text: "Security Groups", href: "#/ec2/security-groups" },
      { type: "link", text: "Elastic IPs", href: "#/ec2/elastic-ips" },
      { type: "link", text: "Placement Groups", href: "#/ec2/placement-groups" },
      { type: "link", text: "Key Pairs", href: "#/ec2/key-pairs" },
      { type: "link", text: "Network Interfaces", href: "#/ec2/network-interfaces" },
    ] },
    { type: "section", text: "Load Balancing", items: [
      { type: "link", text: "Load Balancers", href: "#/ec2/load-balancers" },
      { type: "link", text: "Target Groups", href: "#/ec2/target-groups" },
      { type: "link", text: "Trust Stores", href: "#/ec2/trust-stores" },
    ] },
    { type: "section", text: "Auto Scaling", items: [
      { type: "link", text: "Auto Scaling Groups", href: "#/ec2/auto-scaling-groups" },
    ] },
    { type: "link", text: "Settings", href: "#/ec2/settings" },
  ],
  routes: [
    { pattern: "/ec2", component: Dashboard, crumbs: () => base },
    { pattern: "/ec2/home", component: Dashboard, crumbs: () => base },
    { pattern: "/ec2/dashboard", component: Dashboard, crumbs: () => [crumb("EC2", ""), crumb("Dashboard", "dashboard")] },
    { pattern: "/ec2/events", component: Honest.Events, crumbs: () => [crumb("EC2", ""), crumb("Events", "events")] },

    { pattern: "/ec2/instances", component: Instances, crumbs: () => [crumb("EC2", ""), crumb("Instances", "instances")] },
    { pattern: "/ec2/instances/:id", component: InstanceDetail, crumbs: (p) => [crumb("EC2", ""), crumb("Instances", "instances"), crumb(p.id, "instances", p.id)] },
    { pattern: "/ec2/instances/:id/create-image", component: CreateImage, crumbs: (p) => [crumb("EC2", ""), crumb("Instances", "instances"), crumb(p.id, "instances", p.id), crumb("Create image", "instances", p.id, "create-image")] },
    { pattern: "/ec2/launch-instance", component: LaunchInstance, crumbs: () => [crumb("EC2", ""), crumb("Instances", "instances"), crumb("Launch an instance", "launch-instance")] },
    { pattern: "/ec2/instance-types", component: InstanceTypes, crumbs: () => [crumb("EC2", ""), crumb("Instance types", "instance-types")] },
    { pattern: "/ec2/instance-types/:type", component: InstanceTypeDetail, crumbs: (p) => [crumb("EC2", ""), crumb("Instance types", "instance-types"), crumb(p.type, "instance-types", p.type)] },
    { pattern: "/ec2/launch-templates", component: LaunchTemplates, crumbs: () => [crumb("EC2", ""), crumb("Launch templates", "launch-templates")] },
    { pattern: "/ec2/create-launch-template", component: CreateLaunchTemplate, crumbs: () => [crumb("EC2", ""), crumb("Launch templates", "launch-templates"), crumb("Create launch template", "create-launch-template")] },

    { pattern: "/ec2/spot-requests", component: Honest.SpotRequests, crumbs: () => [crumb("EC2", ""), crumb("Spot Requests", "spot-requests")] },
    { pattern: "/ec2/savings-plans", component: Honest.SavingsPlans, crumbs: () => [crumb("EC2", ""), crumb("Savings Plans", "savings-plans")] },
    { pattern: "/ec2/reserved-instances", component: Honest.ReservedInstances, crumbs: () => [crumb("EC2", ""), crumb("Reserved Instances", "reserved-instances")] },
    { pattern: "/ec2/dedicated-hosts", component: Honest.DedicatedHosts, crumbs: () => [crumb("EC2", ""), crumb("Dedicated Hosts", "dedicated-hosts")] },
    { pattern: "/ec2/capacity-reservations", component: Honest.CapacityReservations, crumbs: () => [crumb("EC2", ""), crumb("Capacity Reservations", "capacity-reservations")] },
    { pattern: "/ec2/ultraservers", component: Honest.UltraServers, crumbs: () => [crumb("EC2", ""), crumb("UltraServers", "ultraservers")] },
    { pattern: "/ec2/capacity-manager", component: Honest.CapacityManager, crumbs: () => [crumb("EC2", ""), crumb("Capacity Manager", "capacity-manager")] },

    { pattern: "/ec2/amis", component: Amis, crumbs: () => [crumb("EC2", ""), crumb("AMIs", "amis")] },
    { pattern: "/ec2/amis/:id", component: AmiDetail, crumbs: (p) => [crumb("EC2", ""), crumb("AMIs", "amis"), crumb(p.id, "amis", p.id)] },
    { pattern: "/ec2/ami-catalog", component: AmiCatalog, crumbs: () => [crumb("EC2", ""), crumb("AMI Catalog", "ami-catalog")] },

    { pattern: "/ec2/volumes", component: Volumes, crumbs: () => [crumb("EC2", ""), crumb("Volumes", "volumes")] },
    { pattern: "/ec2/volumes/:id", component: VolumeDetail, crumbs: (p) => [crumb("EC2", ""), crumb("Volumes", "volumes"), crumb(p.id, "volumes", p.id)] },
    { pattern: "/ec2/create-volume", component: CreateVolume, crumbs: () => [crumb("EC2", ""), crumb("Volumes", "volumes"), crumb("Create volume", "create-volume")] },
    { pattern: "/ec2/snapshots", component: Snapshots, crumbs: () => [crumb("EC2", ""), crumb("Snapshots", "snapshots")] },
    { pattern: "/ec2/create-snapshot", component: CreateSnapshot, crumbs: () => [crumb("EC2", ""), crumb("Snapshots", "snapshots"), crumb("Create snapshot", "create-snapshot")] },
    { pattern: "/ec2/create-snapshot/:volumeId", component: CreateSnapshot, crumbs: () => [crumb("EC2", ""), crumb("Snapshots", "snapshots"), crumb("Create snapshot", "create-snapshot")] },
    { pattern: "/ec2/lifecycle-manager", component: LifecycleManager, crumbs: () => [crumb("EC2", ""), crumb("Lifecycle Manager", "lifecycle-manager")] },
    { pattern: "/ec2/create-lifecycle-policy", component: CreateLifecyclePolicy, crumbs: () => [crumb("EC2", ""), crumb("Lifecycle Manager", "lifecycle-manager"), crumb("Create policy", "create-lifecycle-policy")] },

    { pattern: "/ec2/security-groups", component: SecurityGroups, crumbs: () => [crumb("EC2", ""), crumb("Security Groups", "security-groups")] },
    { pattern: "/ec2/security-groups/:id", component: SecurityGroupDetail, crumbs: (p) => [crumb("EC2", ""), crumb("Security Groups", "security-groups"), crumb(p.id, "security-groups", p.id)] },
    { pattern: "/ec2/security-groups/:id/edit-inbound-rules", component: EditInboundRules, crumbs: (p) => [crumb("EC2", ""), crumb("Security Groups", "security-groups"), crumb(p.id, "security-groups", p.id), crumb("Edit inbound rules", "security-groups", p.id, "edit-inbound-rules")] },
    { pattern: "/ec2/security-groups/:id/edit-outbound-rules", component: EditOutboundRules, crumbs: (p) => [crumb("EC2", ""), crumb("Security Groups", "security-groups"), crumb(p.id, "security-groups", p.id), crumb("Edit outbound rules", "security-groups", p.id, "edit-outbound-rules")] },
    { pattern: "/ec2/create-security-group", component: CreateSecurityGroup, crumbs: () => [crumb("EC2", ""), crumb("Security Groups", "security-groups"), crumb("Create security group", "create-security-group")] },

    { pattern: "/ec2/elastic-ips", component: ElasticIps, crumbs: () => [crumb("EC2", ""), crumb("Elastic IP addresses", "elastic-ips")] },
    { pattern: "/ec2/allocate-elastic-ip", component: AllocateElasticIp, crumbs: () => [crumb("EC2", ""), crumb("Elastic IP addresses", "elastic-ips"), crumb("Allocate Elastic IP address", "allocate-elastic-ip")] },
    { pattern: "/ec2/placement-groups", component: PlacementGroups, crumbs: () => [crumb("EC2", ""), crumb("Placement groups", "placement-groups")] },
    { pattern: "/ec2/create-placement-group", component: CreatePlacementGroup, crumbs: () => [crumb("EC2", ""), crumb("Placement groups", "placement-groups"), crumb("Create placement group", "create-placement-group")] },
    { pattern: "/ec2/key-pairs", component: KeyPairs, crumbs: () => [crumb("EC2", ""), crumb("Key pairs", "key-pairs")] },
    { pattern: "/ec2/create-key-pair", component: CreateKeyPair, crumbs: () => [crumb("EC2", ""), crumb("Key pairs", "key-pairs"), crumb("Create key pair", "create-key-pair")] },
    { pattern: "/ec2/import-key-pair", component: ImportKeyPair, crumbs: () => [crumb("EC2", ""), crumb("Key pairs", "key-pairs"), crumb("Import key pair", "import-key-pair")] },
    { pattern: "/ec2/network-interfaces", component: NetworkInterfaces, crumbs: () => [crumb("EC2", ""), crumb("Network interfaces", "network-interfaces")] },

    { pattern: "/ec2/load-balancers", component: LoadBalancers, crumbs: () => [crumb("EC2", ""), crumb("Load balancers", "load-balancers")] },
    { pattern: "/ec2/load-balancers/:id", component: LoadBalancerDetail, crumbs: (p) => [crumb("EC2", ""), crumb("Load balancers", "load-balancers"), crumb(p.id, "load-balancers", p.id)] },
    { pattern: "/ec2/create-load-balancer", component: CreateLoadBalancer, crumbs: () => [crumb("EC2", ""), crumb("Load balancers", "load-balancers"), crumb("Create load balancer", "create-load-balancer")] },
    { pattern: "/ec2/target-groups", component: TargetGroups, crumbs: () => [crumb("EC2", ""), crumb("Target groups", "target-groups")] },
    { pattern: "/ec2/target-groups/:id", component: TargetGroupDetail, crumbs: (p) => [crumb("EC2", ""), crumb("Target groups", "target-groups"), crumb(p.id, "target-groups", p.id)] },
    { pattern: "/ec2/create-target-group", component: CreateTargetGroup, crumbs: () => [crumb("EC2", ""), crumb("Target groups", "target-groups"), crumb("Create target group", "create-target-group")] },
    { pattern: "/ec2/trust-stores", component: TrustStores, crumbs: () => [crumb("EC2", ""), crumb("Trust stores", "trust-stores")] },
    { pattern: "/ec2/create-trust-store", component: CreateTrustStore, crumbs: () => [crumb("EC2", ""), crumb("Trust stores", "trust-stores"), crumb("Create trust store", "create-trust-store")] },
    { pattern: "/ec2/auto-scaling-groups", component: AutoScalingGroups, crumbs: () => [crumb("EC2", ""), crumb("Auto Scaling groups", "auto-scaling-groups")] },
    { pattern: "/ec2/auto-scaling-groups/:id", component: AutoScalingGroupDetail, crumbs: (p) => [crumb("EC2", ""), crumb("Auto Scaling groups", "auto-scaling-groups"), crumb(p.id, "auto-scaling-groups", p.id)] },
    { pattern: "/ec2/create-auto-scaling-group", component: CreateAutoScalingGroup, crumbs: () => [crumb("EC2", ""), crumb("Auto Scaling groups", "auto-scaling-groups"), crumb("Create Auto Scaling group", "create-auto-scaling-group")] },
    { pattern: "/ec2/settings", component: Settings, crumbs: () => [crumb("EC2", ""), crumb("Settings", "settings")] },

    { pattern: "/ec2/migrate-a-server", component: Honest.MigrateAServer, crumbs: () => [crumb("EC2", ""), crumb("Migrate a server", "migrate-a-server")] },
    { pattern: "/ec2/recycle-bin", component: Honest.RecycleBin, crumbs: () => [crumb("EC2", ""), crumb("Recycle Bin", "recycle-bin")] },
    { pattern: "/ec2/image-builder", component: Honest.ImageBuilder, crumbs: () => [crumb("EC2", ""), crumb("EC2 Image Builder", "image-builder")] },
    { pattern: "/ec2/instance-type-finder", component: Honest.InstanceTypeFinder, crumbs: () => [crumb("EC2", ""), crumb("Instance type finder", "instance-type-finder")] },
    { pattern: "/ec2/create-iam-profile", component: Honest.CreateIamProfile, crumbs: () => [crumb("EC2", ""), crumb("Create IAM profile", "create-iam-profile")] },
    { pattern: "/ec2/compare-security-group-rules", component: Honest.CompareSecurityGroupRules, crumbs: () => [crumb("EC2", ""), crumb("Compare security group rules", "compare-security-group-rules")] },
  ],
};
