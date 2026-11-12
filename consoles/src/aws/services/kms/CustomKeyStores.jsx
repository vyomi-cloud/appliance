/* Custom key stores. CRUD and connect/disconnect are real (core/kms_core.py): a CloudHSM key store connects to Vyomi's
 * software-HSM cluster, an external key store to Vyomi's built-in XKS proxy (or a reachable proxy's /health on the
 * offline appliance); keys created in a CONNECTED store keep their material in the store's partition
 * (core/capabilities/aws/kms.json: kms.custom-key-stores, kms.custom-key-store-keys). */
import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import StatusIndicator from "@cloudscape-design/components/status-indicator";
import ResourceTable from "../../kit/ResourceTable.jsx";
import { CapabilityBadge } from "../../kit/Capability.jsx";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import * as api from "./api.js";

const connState = (s) => <StatusIndicator type={s === "CONNECTED" ? "success" : s === "FAILED" ? "error" : "stopped"}>{s}</StatusIndicator>;

export function AwsCloudHsmKeyStores() {
  const notify = useNotify();
  const t = useAsync(() => api.describeCustomKeyStores().then((xs) => xs.filter((x) => x.CustomKeyStoreType === "AWS_CLOUDHSM")), []);
  const [sel, setSel] = useState([]);
  return (
    <ResourceTable
      resourceName="AWS CloudHSM key stores"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="CustomKeyStoreId"
      selectionType="single"
      selectedItems={sel}
      onSelectionChange={setSel}
      actions={
        <>
          <CapabilityBadge id="kms.custom-key-stores" />{" "}
          <ButtonDropdown
            items={[
              { id: "connect", text: "Connect", disabled: sel.length !== 1 },
              { id: "disconnect", text: "Disconnect", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete", disabled: sel.length !== 1 },
            ]}
            onItemClick={async ({ detail }) => {
              const id = sel[0]?.CustomKeyStoreId;
              try {
                if (detail.id === "connect") { await api.connectCustomKeyStore(id); notify.info("Connection attempted - see Connection state."); }
                else if (detail.id === "disconnect") { await api.disconnectCustomKeyStore(id); notify.success("Disconnected."); }
                else if (detail.id === "delete") { await api.deleteCustomKeyStore(id); notify.success("Deleted."); }
                setSel([]); t.reload();
              } catch (e) { notify.error(e); }
            }}
          >Key store actions</ButtonDropdown>{" "}
          <Button variant="primary" onClick={async () => {
            try {
              const name = `soft-hsm-${Math.random().toString(36).slice(2, 7)}`;
              const r = await api.createCustomKeyStore({ CustomKeyStoreName: name, CustomKeyStoreType: "AWS_CLOUDHSM", CloudHsmClusterId: "cluster-vyomisofthsm", TrustAnchorCertificate: "vyomi-soft-hsm-anchor", KeyStorePassword: "vyomi" });
              await api.connectCustomKeyStore(r.CustomKeyStoreId);
              notify.success(`Created and connected "${name}" on Vyomi's software HSM cluster.`); t.reload();
            } catch (e) { notify.error(e); }
          }}>Create software-HSM key store</Button>
        </>
      }
      empty={{ title: "You don't have any custom key stores in your account." }}
      columns={[
        { id: "n", header: "Custom key store name", isRowHeader: true, cell: (x) => x.CustomKeyStoreName },
        { id: "id", header: "Custom key store ID", cell: (x) => x.CustomKeyStoreId },
        { id: "cluster", header: "AWS CloudHSM cluster ID", cell: (x) => x.CloudHsmClusterId || "-" },
        { id: "conn", header: "Connection state", cell: (x) => <>{connState(x.ConnectionState)}{x.ConnectionErrorCode ? ` (${x.ConnectionErrorCode})` : ""}</> },
      ]}
    />
  );
}

export function ExternalKeyStores() {
  const notify = useNotify();
  const t = useAsync(() => api.describeCustomKeyStores().then((xs) => xs.filter((x) => x.CustomKeyStoreType === "EXTERNAL_KEY_STORE")), []);
  const [sel, setSel] = useState([]);
  return (
    <ResourceTable
      resourceName="External key stores"
      items={t.data || []}
      loading={t.loading}
      error={t.error}
      onRefresh={t.reload}
      trackBy="CustomKeyStoreId"
      selectionType="single"
      selectedItems={sel}
      onSelectionChange={setSel}
      empty={{ title: "No external key stores", action: <Button onClick={() => navigate("kms", "external-key-stores", "create")}>Create external key store</Button> }}
      columns={[
        { id: "n", header: "Custom key store name", isRowHeader: true, cell: (x) => x.CustomKeyStoreName },
        { id: "id", header: "Custom key store ID", cell: (x) => x.CustomKeyStoreId },
        { id: "proxy", header: "Proxy connectivity", cell: (x) => x.XksProxyConfiguration?.Connectivity || "-" },
        { id: "conn", header: "Connection state", cell: (x) => <>{connState(x.ConnectionState)}{x.ConnectionErrorCode ? ` (${x.ConnectionErrorCode})` : ""}</> },
      ]}
      actions={
        <>
          <CapabilityBadge id="kms.custom-key-stores" />
          {" "}
          <ButtonDropdown
            items={[
              { id: "connect", text: "Connect", disabled: sel.length !== 1 },
              { id: "disconnect", text: "Disconnect", disabled: sel.length !== 1 },
              { id: "delete", text: "Delete", disabled: sel.length !== 1 },
            ]}
            onItemClick={async ({ detail }) => {
              const id = sel[0]?.CustomKeyStoreId;
              try {
                if (detail.id === "connect") { await api.connectCustomKeyStore(id); notify.info("Connection attempted — see Connection state."); }
                else if (detail.id === "disconnect") { await api.disconnectCustomKeyStore(id); notify.success("Disconnected."); }
                else if (detail.id === "delete") { await api.deleteCustomKeyStore(id); notify.success("Deleted."); }
                setSel([]); t.reload();
              } catch (e) { notify.error(e); }
            }}
          >Key store actions</ButtonDropdown>
          {" "}
          <Button variant="primary" onClick={() => navigate("kms", "external-key-stores", "create")}>Create external key store</Button>
        </>
      }
    />
  );
}
