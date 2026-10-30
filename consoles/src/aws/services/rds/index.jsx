import Dashboard from "./Dashboard.jsx";
import Databases from "./Databases.jsx";
import DatabaseDetail from "./DatabaseDetail.jsx";
import CreateDatabase from "./CreateDatabase.jsx";
import QueryEditor from "./QueryEditor.jsx";
import Snapshots from "./Snapshots.jsx";
import TakeSnapshot from "./TakeSnapshot.jsx";
import ExportsInAmazonS3 from "./ExportsInAmazonS3.jsx";
import AutomatedBackups from "./AutomatedBackups.jsx";
import SubnetGroups from "./SubnetGroups.jsx";
import CreateSubnetGroup from "./CreateSubnetGroup.jsx";
import ParameterGroups from "./ParameterGroups.jsx";
import CreateParameterGroup from "./CreateParameterGroup.jsx";
import ParameterGroupDetail from "./ParameterGroupDetail.jsx";
import OptionGroups from "./OptionGroups.jsx";
import Proxies from "./Proxies.jsx";
import Events from "./Events.jsx";
import EventSubscriptions from "./EventSubscriptions.jsx";
import {
  CapacityReservations, CertificateUpdate, CreateCapacityReservation, CreateZeroEtlIntegration,
  CustomEngineVersions, Recommendations, ReservedInstances, RestoreFromS3, ZeroEtlIntegrations,
} from "./Peripheral.jsx";

const crumb = (text, href) => ({ text, href });
const root = [crumb("Aurora and RDS", "#/rds")];

export default {
  nav: [
    { type: "link", text: "Dashboard", href: "#/rds/dashboard" },
    { type: "link", text: "Databases", href: "#/rds/databases" },
    { type: "link", text: "Query editor", href: "#/rds/query-editor" },
    { type: "link", text: "Snapshots", href: "#/rds/snapshots" },
    { type: "link", text: "Exports in Amazon S3", href: "#/rds/exports-in-amazon-s3" },
    { type: "link", text: "Automated backups", href: "#/rds/automated-backups" },
    { type: "link", text: "Reserved instances", href: "#/rds/reserved-instances" },
    { type: "link", text: "Capacity reservations", href: "#/rds/capacity-reservations" },
    { type: "link", text: "Proxies", href: "#/rds/proxies" },
    { type: "link", text: "Subnet groups", href: "#/rds/subnet-groups" },
    { type: "link", text: "Parameter groups", href: "#/rds/parameter-groups" },
    { type: "link", text: "Option groups", href: "#/rds/option-groups" },
    { type: "link", text: "Custom engine versions", href: "#/rds/custom-engine-versions" },
    { type: "link", text: "Zero-ETL integrations", href: "#/rds/zero-etl-integrations" },
    { type: "link", text: "Events", href: "#/rds/events" },
    { type: "link", text: "Event subscriptions", href: "#/rds/event-subscriptions" },
    { type: "link", text: "Recommendations", href: "#/rds/recommendations" },
    { type: "link", text: "Certificate update", href: "#/rds/certificate-update" },
  ],
  routes: [
    { pattern: "/rds", component: Dashboard, crumbs: () => root },
    { pattern: "/rds/home", component: Dashboard, crumbs: () => root },
    { pattern: "/rds/databases", component: Databases, crumbs: () => [...root, crumb("Databases", "#/rds/databases")] },
    { pattern: "/rds/databases/:id", component: DatabaseDetail, crumbs: (p) => [...root, crumb("Databases", "#/rds/databases"), crumb(p.id, `#/rds/databases/${p.id}`)] },
    { pattern: "/rds/create-database", component: CreateDatabase, crumbs: () => [...root, crumb("Databases", "#/rds/databases"), crumb("Create database", "#/rds/create-database")] },
    { pattern: "/rds/restore-from-s3", component: RestoreFromS3, crumbs: () => [...root, crumb("Databases", "#/rds/databases"), crumb("Restore from S3", "#/rds/restore-from-s3")] },
    { pattern: "/rds/query-editor", component: QueryEditor, crumbs: () => [...root, crumb("Query editor", "#/rds/query-editor")] },
    { pattern: "/rds/snapshots", component: Snapshots, crumbs: () => [...root, crumb("Snapshots", "#/rds/snapshots")] },
    { pattern: "/rds/take-snapshot", component: TakeSnapshot, crumbs: () => [...root, crumb("Snapshots", "#/rds/snapshots"), crumb("Take snapshot", "#/rds/take-snapshot")] },
    { pattern: "/rds/exports-in-amazon-s3", component: ExportsInAmazonS3, crumbs: () => [...root, crumb("Exports in Amazon S3", "#/rds/exports-in-amazon-s3")] },
    { pattern: "/rds/automated-backups", component: AutomatedBackups, crumbs: () => [...root, crumb("Automated backups", "#/rds/automated-backups")] },
    { pattern: "/rds/reserved-instances", component: ReservedInstances, crumbs: () => [...root, crumb("Reserved instances", "#/rds/reserved-instances")] },
    { pattern: "/rds/capacity-reservations", component: CapacityReservations, crumbs: () => [...root, crumb("Capacity reservations", "#/rds/capacity-reservations")] },
    { pattern: "/rds/create-capacity-reservation", component: CreateCapacityReservation, crumbs: () => [...root, crumb("Capacity reservations", "#/rds/capacity-reservations"), crumb("Create capacity reservation", "#/rds/create-capacity-reservation")] },
    { pattern: "/rds/proxies", component: Proxies, crumbs: () => [...root, crumb("Proxies", "#/rds/proxies")] },
    { pattern: "/rds/subnet-groups", component: SubnetGroups, crumbs: () => [...root, crumb("Subnet groups", "#/rds/subnet-groups")] },
    { pattern: "/rds/create-db-subnet-group", component: CreateSubnetGroup, crumbs: () => [...root, crumb("Subnet groups", "#/rds/subnet-groups"), crumb("Create DB subnet group", "#/rds/create-db-subnet-group")] },
    { pattern: "/rds/parameter-groups", component: ParameterGroups, crumbs: () => [...root, crumb("Parameter groups", "#/rds/parameter-groups")] },
    { pattern: "/rds/create-parameter-group", component: CreateParameterGroup, crumbs: () => [...root, crumb("Parameter groups", "#/rds/parameter-groups"), crumb("Create parameter group", "#/rds/create-parameter-group")] },
    { pattern: "/rds/parameter-groups/:name", component: ParameterGroupDetail, crumbs: (p) => [...root, crumb("Parameter groups", "#/rds/parameter-groups"), crumb(p.name, `#/rds/parameter-groups/${p.name}`)] },
    { pattern: "/rds/option-groups", component: OptionGroups, crumbs: () => [...root, crumb("Option groups", "#/rds/option-groups")] },
    { pattern: "/rds/custom-engine-versions", component: CustomEngineVersions, crumbs: () => [...root, crumb("Custom engine versions", "#/rds/custom-engine-versions")] },
    { pattern: "/rds/zero-etl-integrations", component: ZeroEtlIntegrations, crumbs: () => [...root, crumb("Zero-ETL integrations", "#/rds/zero-etl-integrations")] },
    { pattern: "/rds/create-zero-etl-integration", component: CreateZeroEtlIntegration, crumbs: () => [...root, crumb("Zero-ETL integrations", "#/rds/zero-etl-integrations"), crumb("Create zero-ETL integration", "#/rds/create-zero-etl-integration")] },
    { pattern: "/rds/events", component: Events, crumbs: () => [...root, crumb("Events", "#/rds/events")] },
    { pattern: "/rds/event-subscriptions", component: EventSubscriptions, crumbs: () => [...root, crumb("Event subscriptions", "#/rds/event-subscriptions")] },
    { pattern: "/rds/recommendations", component: Recommendations, crumbs: () => [...root, crumb("Recommendations", "#/rds/recommendations")] },
    { pattern: "/rds/certificate-update", component: CertificateUpdate, crumbs: () => [...root, crumb("Certificate update", "#/rds/certificate-update")] },
  ],
};
