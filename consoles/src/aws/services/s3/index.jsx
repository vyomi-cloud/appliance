import Buckets from "./Buckets.jsx";
import CreateBucket from "./CreateBucket.jsx";
import BucketDetail from "./BucketDetail.jsx";
import ObjectDetail from "./ObjectDetail.jsx";
import UploadPage from "./UploadPage.jsx";
import CreateFolderPage from "./CreateFolderPage.jsx";
import EmptyBucketPage from "./EmptyBucketPage.jsx";
import DeleteBucketPage from "./DeleteBucketPage.jsx";
import { NotSimulatedContainer } from "../../kit/common.jsx";

const ns = (title) => () => <NotSimulatedContainer title={title} />;

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
    ...[["directory-buckets", "Directory buckets"], ["table-buckets", "Table buckets"], ["access-grants", "Access Grants"], ["access-points", "Access Points"],
      ["olap", "Object Lambda Access Points"], ["mrap", "Multi-Region Access Points"], ["batch-operations", "Batch Operations"],
      ["access-analyzer", "IAM Access Analyzer for S3"], ["settings", "Block Public Access settings for this account"],
      ["lens/dashboards", "Storage Lens dashboards"], ["lens/groups", "Storage Lens groups"],
      ["marketplace", "AWS Marketplace for S3"], ["get-started", "Amazon S3"]]
      .map(([p, t]) => ({ pattern: `/s3/${p}`, component: ns(t), crumbs: () => [{ text: t, href: `#/s3/${p}` }] })),
  ],
};
