/* Virtual machines browse blade (ARM list at subscription scope). */
import { Link } from "@fluentui/react-components";
import { useNotify } from "../../../common/notify.jsx";
import { navigate } from "../../../common/router.js";
import { useAsync } from "../../../common/useAsync.js";
import { locationLabel } from "../../kit/arm.js";
import BrowseGrid from "../../kit/BrowseGrid.jsx";
import { Glyph, NotSimulatedContainer } from "../../kit/common.jsx";
import { TitleRow } from "../../kit/ResourceBlade.jsx";
import { useSubscription } from "../../kit/subscription.js";
import * as api from "./api.js";

const osOf = (v) => (v.properties?.storageProfile?.osDisk?.osType) || (v.properties?.osProfile?.linuxConfiguration ? "Linux" : v.properties?.osProfile?.windowsConfiguration ? "Windows" : "Linux");
const statusOf = (v) => {
  const s = v.properties?.powerState || "PowerState/running";
  return s.replace("PowerState/", "").replace(/^./, (c) => c.toUpperCase());
};
const sizeOf = (v) => v.properties?.hardwareProfile?.vmSize || "--";
const disksOf = (v) => 1 + (v.properties?.storageProfile?.dataDisks || []).length;

export default function VirtualMachines() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listVms(), [sub.id]);
  const subName = sub.displayName || sub.id;
  return (
    <>
      <TitleRow title="Virtual machines" glyph={<Glyph id="vms" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="virtual machine"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("vms", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteVm(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} virtual machine${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="virtual-machines.csv"
          filterPlaceholder="Filter for any field..."
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/vms/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "type", label: "Type", value: () => "Virtual machine" },
            { key: "subscription", label: "Subscription", value: () => subName },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "status", label: "Status", value: statusOf },
            { key: "os", label: "Operating system", value: osOf },
            { key: "size", label: "Size", value: sizeOf },
            { key: "publicip", label: "Public IP address", value: () => "--" },
            { key: "disks", label: "Disks", value: disksOf },
          ]}
          emptyAction={<Link href="#/vms/create">Create virtual machine</Link>}
        />
        <NotSimulatedContainer feature="Switch to classic, Reservations, Open query (Azure Resource Graph), Assign tags, Start, Restart, Stop, Services and Maintenance from this list's command bar — open a virtual machine to start, restart or stop it" />
      </div>
    </>
  );
}
