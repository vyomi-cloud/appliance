import Landing from "./Landing.jsx";
import AwsManagedKeys from "./AwsManagedKeys.jsx";
import AwsManagedKeyDetail from "./AwsManagedKeyDetail.jsx";
import CustomerManagedKeys from "./CustomerManagedKeys.jsx";
import CustomerManagedKeyDetail from "./CustomerManagedKeyDetail.jsx";
import CreateKey from "./CreateKey.jsx";
import { AwsCloudHsmKeyStores, ExternalKeyStores } from "./CustomKeyStores.jsx";
import CreateExternalKeyStore from "./CreateExternalKeyStore.jsx";

export default {
  nav: [
    { type: "link", text: "AWS managed keys", href: "#/kms/aws-managed-keys" },
    { type: "link", text: "Customer managed keys", href: "#/kms/customer-managed-keys" },
    { type: "section", text: "Custom key stores", items: [
      { type: "link", text: "AWS CloudHSM key stores", href: "#/kms/cloudhsm-key-stores" },
      { type: "link", text: "External key stores", href: "#/kms/external-key-stores" },
    ] },
  ],
  routes: [
    { pattern: "/kms", component: Landing, crumbs: () => [{ text: "AWS Key Management Service", href: "#/kms" }] },
    { pattern: "/kms/home", component: Landing, crumbs: () => [{ text: "AWS Key Management Service", href: "#/kms/home" }] },
    { pattern: "/kms/aws-managed-keys", component: AwsManagedKeys, crumbs: () => [{ text: "KMS", href: "#/kms" }, { text: "AWS managed keys", href: "#/kms/aws-managed-keys" }] },
    { pattern: "/kms/aws-managed-keys/:id", component: AwsManagedKeyDetail, crumbs: (p) => [{ text: "KMS", href: "#/kms" }, { text: "AWS managed keys", href: "#/kms/aws-managed-keys" }, { text: `Key ID: ${p.id}`, href: `#/kms/aws-managed-keys/${p.id}` }] },
    { pattern: "/kms/customer-managed-keys", component: CustomerManagedKeys, crumbs: () => [{ text: "KMS", href: "#/kms" }, { text: "Customer managed keys", href: "#/kms/customer-managed-keys" }] },
    { pattern: "/kms/customer-managed-keys/:id", component: CustomerManagedKeyDetail, crumbs: (p) => [{ text: "KMS", href: "#/kms" }, { text: "Customer managed keys", href: "#/kms/customer-managed-keys" }, { text: `Key ID: ${p.id}`, href: `#/kms/customer-managed-keys/${p.id}` }] },
    { pattern: "/kms/create-key", component: CreateKey, crumbs: () => [{ text: "KMS", href: "#/kms" }, { text: "Customer managed keys", href: "#/kms/customer-managed-keys" }, { text: "Create key", href: "#/kms/create-key" }] },
    { pattern: "/kms/cloudhsm-key-stores", component: AwsCloudHsmKeyStores, crumbs: () => [{ text: "KMS", href: "#/kms" }, { text: "AWS CloudHSM key stores", href: "#/kms/cloudhsm-key-stores" }] },
    { pattern: "/kms/external-key-stores", component: ExternalKeyStores, crumbs: () => [{ text: "KMS", href: "#/kms" }, { text: "External key stores", href: "#/kms/external-key-stores" }] },
    { pattern: "/kms/external-key-stores/create", component: CreateExternalKeyStore, crumbs: () => [{ text: "KMS", href: "#/kms" }, { text: "External key stores", href: "#/kms/external-key-stores" }, { text: "Create external key store", href: "#/kms/external-key-stores/create" }] },
  ],
};
