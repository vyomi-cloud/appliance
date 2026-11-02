import Buckets from "./Buckets.jsx";
import CreateBucket from "./CreateBucket.jsx";
import BucketDetail from "./BucketDetail.jsx";
import ObjectDetail from "./ObjectDetail.jsx";
import UploadPage from "./UploadPage.jsx";
import CreateFolderPage from "./CreateFolderPage.jsx";
import EmptyBucketPage from "./EmptyBucketPage.jsx";
import DeleteBucketPage from "./DeleteBucketPage.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { AccessPointsSection } from "./Sweep.jsx";

// Account-level pages Vyomi has no backend for: each is a registered capability gap (core/capabilities/aws/s3.json).
const ns = (title, id) => () => <CapabilityContainer id={`s3.account.${id}`} title={title} />;

export default {
  nav: [
    { type: "link", text: "General purpose buckets", href: "#/s3" },
    { type: "link", text: "Directory buckets", href: "#/s3/directory-buckets" },
    { type: "link", text: "Table buckets", href: "#/s3/table-buckets" },
    { type: "link", text: "Access Grants", href: "#/s3/access-grants" },
    { type: "link", text: "Access Points", href: "#/s3/access-points" },
    { type: "link", text: "Object Lambda Access Points", href: "#/s3/olap" },
    { type: "link", text: "Multi-Region Access Points", href: "#/s3/mrap" },
    { type: "link", text: "Batch Operations", href: "#/s3/batch-operations" },
    { type: "link", text: "IAM Access Analyzer for S3", href: "#/s3/access-analyzer" },
    { type: "divider" },
    { type: "link", text: "Block Public Access settings for this account", href: "#/s3/settings" },
    { type: "section", text: "Storage Lens", items: [
      { type: "link", text: "Dashboards", href: "#/s3/lens/dashboards" },
      { type: "link", text: "Storage Lens groups", href: "#/s3/lens/groups" },
    ] },
  ],
  routes: [
    { pattern: "/s3", component: Buckets },
    { pattern: "/s3/buckets", component: Buckets },
    { pattern: "/s3/create", component: CreateBucket, crumbs: () => [{ text: "Create bucket", href: "#/s3/create" }] },
    { pattern: "/s3/buckets/:name", component: BucketDetail, crumbs: (p) => [{ text: "Buckets", href: "#/s3" }, { text: p.name, href: `#/s3/buckets/${p.name}` }] },
    { pattern: "/s3/object/:bucket", component: ObjectDetail, crumbs: (p) => [{ text: "Buckets", href: "#/s3" }, { text: p.bucket, href: `#/s3/buckets/${p.bucket}` }] },
    { pattern: "/s3/upload/:bucket", component: UploadPage, crumbs: (p) => [{ text: "Buckets", href: "#/s3" }, { text: p.bucket, href: `#/s3/buckets/${p.bucket}` }, { text: "Upload", href: `#/s3/upload/${p.bucket}` }] },
    { pattern: "/s3/bucket/:bucket/create/folder", component: CreateFolderPage, crumbs: (p) => [{ text: "Buckets", href: "#/s3" }, { text: p.bucket, href: `#/s3/buckets/${p.bucket}` }, { text: "Create folder", href: `#/s3/bucket/${p.bucket}/create/folder` }] },
    { pattern: "/s3/bucket/:bucket/empty", component: EmptyBucketPage, crumbs: (p) => [{ text: "Buckets", href: "#/s3" }, { text: p.bucket, href: `#/s3/buckets/${p.bucket}` }, { text: "Empty bucket", href: `#/s3/bucket/${p.bucket}/empty` }] },
    { pattern: "/s3/bucket/:bucket/delete", component: DeleteBucketPage, crumbs: (p) => [{ text: "Buckets", href: "#/s3" }, { text: p.bucket, href: `#/s3/buckets/${p.bucket}` }, { text: "Delete bucket", href: `#/s3/bucket/${p.bucket}/delete` }] },
    { pattern: "/s3/access-points", component: () => <AccessPointsSection />, crumbs: () => [{ text: "Access Points", href: "#/s3/access-points" }] },
    ...[["directory-buckets", "Directory buckets", "directory-buckets"], ["table-buckets", "Table buckets", "table-buckets"],
      ["access-grants", "Access Grants", "access-grants"], ["olap", "Object Lambda Access Points", "object-lambda-access-points"],
      ["mrap", "Multi-Region Access Points", "multi-region-access-points"], ["batch-operations", "Batch Operations", "batch-operations"],
      ["access-analyzer", "IAM Access Analyzer for S3", "external-access"], ["settings", "Block Public Access settings for this account", "account-public-access-block"],
      ["lens/dashboards", "Storage Lens dashboards", "storage-lens"], ["lens/groups", "Storage Lens groups", "storage-lens"],
      ["marketplace", "AWS Marketplace for S3", "marketplace"], ["get-started", "Amazon S3", "get-started"]]
      .map(([p, t, id]) => ({ pattern: `/s3/${p}`, component: ns(t, id), crumbs: () => [{ text: t, href: `#/s3/${p}` }] })),
  ],
};
