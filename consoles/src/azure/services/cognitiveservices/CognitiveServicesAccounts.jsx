/* Azure AI services browse blade (Microsoft.CognitiveServices/accounts, ARM list at subscription scope). */
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

export default function CognitiveServicesAccounts() {
  const notify = useNotify();
  const sub = useSubscription();
  const { data, loading, error, reload } = useAsync(() => api.listAccounts(), [sub.id]);
  const subName = sub.displayName || sub.id;
  return (
    <>
      <TitleRow title="Azure AI services" subtitle="Vyomi simulator (default directory)" glyph={<Glyph id="cognitiveservices" />} closeHref="#/" />
      <div className="vy-page">
        <BrowseGrid
          resourceName="account"
          items={data || []}
          loading={loading}
          error={error}
          onRefresh={reload}
          onCreate={() => navigate("cognitiveservices", "create")}
          onDelete={async (rows) => {
            for (const r of rows) await api.deleteAccount(r.resourceGroup, r.name);
            notify.success(`Deleted ${rows.length} account${rows.length === 1 ? "" : "s"}.`, "Delete succeeded");
            reload();
          }}
          subscriptionLabel={subName}
          csvName="azure-ai-services.csv"
          extraCommands={<Link as="button" style={{ marginLeft: 8 }} onClick={() => navigate("cognitiveservices", "deleted")}>Manage deleted accounts</Link>}
          pills={[
            { key: "rg", label: "Resource group", value: (r) => r.resourceGroup },
            { key: "loc", label: "Location", value: (r) => locationLabel(r.location) },
          ]}
          columns={[
            { key: "name", label: "Name", render: (r) => <Link href={`#/cognitiveservices/${encodeURIComponent(r.resourceGroup)}/${encodeURIComponent(r.name)}`}>{r.name}</Link> },
            { key: "type", label: "Type", value: (r) => api.KIND_LABEL[r.kind] || r.kind },
            { key: "resourceGroup", label: "Resource group" },
            { key: "location", label: "Location", value: (r) => locationLabel(r.location) },
            { key: "subscription", label: "Subscription", value: () => subName },
          ]}
          emptyAction={<Link href="#/cognitiveservices/create">Create</Link>}
        />
        <NotSimulatedContainer feature="Manage view, Open query (Azure Resource Graph) and Assign tags from the command bar" />
      </div>
    </>
  );
}
