/* AWS managed keys — read-only list of the aws/<service> aliases Vyomi has
 * auto-provisioned so far (on a service's first Encrypt/GenerateDataKey call),
 * exactly as AWS provisions them lazily. No selection, no header actions. */
import Link from "@cloudscape-design/components/link";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import { useAsync } from "../../../common/useAsync.js";
import { href, follow } from "../../../common/router.js";
import ResourceTable from "../../kit/ResourceTable.jsx";
import * as api from "./api.js";

export default function AwsManagedKeys() {
  const t = useAsync(() => api.listAwsManagedKeys(), []);
  return (
    <ResourceTable
      resourceName="AWS managed keys"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="KeyId"
      filterPlaceholder="Filter keys by properties or tags"
      empty={{ title: "No resources to display" }}
      columns={[
        { id: "alias", header: "Aliases", cell: (k) => <Link href={href("kms", "aws-managed-keys", k.KeyId)} onFollow={follow}>{k.alias.replace(/^alias\//, "")}</Link>, isRowHeader: true },
        { id: "id", header: "Key ID", cell: (k) => k.KeyId },
        { id: "status", header: "Status", cell: (k) => <StatusIndicator type={k.Enabled ? "success" : "stopped"}>{k.KeyState}</StatusIndicator> },
      ]}
    />
  );
}
