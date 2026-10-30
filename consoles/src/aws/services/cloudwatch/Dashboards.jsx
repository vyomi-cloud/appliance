import { useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Tabs from "@cloudscape-design/components/tabs";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import * as api from "./api.js";

const FAV_KEY = "vyomi.cloudwatch.favoriteDashboards";
const loadFavs = () => { try { return new Set(JSON.parse(localStorage.getItem(FAV_KEY)) || []); } catch { return new Set(); } };

export default function Dashboards() {
  const notify = useNotify();
  const t = useAsync(() => api.listDashboards(), []);
  const [selected, setSelected] = useState([]);
  const [deleting, setDeleting] = useState(false);
  const [favs, setFavs] = useState(loadFavs);

  const toggleFav = (name) => {
    const next = new Set(favs);
    next.has(name) ? next.delete(name) : next.add(name);
    setFavs(next);
    localStorage.setItem(FAV_KEY, JSON.stringify([...next]));
  };

  return (
    <ContentLayout header={<Header variant="h1">Dashboards</Header>}>
      <Tabs tabs={[
        {
          id: "custom", label: "Custom dashboards", content: (
            <SpaceBetween size="l">
              <ResourceTable
                resourceName="Custom dashboards"
                items={t.data || []}
                loading={t.loading}
                error={t.error}
                onRefresh={t.reload}
                trackBy="DashboardName"
                selectionType="multi"
                selectedItems={selected}
                onSelectionChange={setSelected}
                filterPlaceholder="Filter dashboards"
                actions={
                  <SpaceBetween direction="horizontal" size="xs">
                    <Button disabled={!selected.length} onClick={() => setDeleting(true)}>Delete</Button>
                    <ButtonDropdown
                      disabled={!selected.length}
                      items={[{ id: "delete", text: "Delete" }]}
                      onItemClick={({ detail }) => detail.id === "delete" && setDeleting(true)}
                    >
                      Actions
                    </ButtonDropdown>
                    <Button variant="primary" href={href("cloudwatch", "dashboards", "create")} onFollow={follow}>Create dashboard</Button>
                  </SpaceBetween>
                }
                columns={[
                  { id: "name", header: "Name", isRowHeader: true, sortingField: "DashboardName", cell: (d) => <Link href={href("cloudwatch", "dashboards", d.DashboardName)} onFollow={follow}>{d.DashboardName}</Link> },
                  { id: "sharing", header: "Sharing", cell: () => "Private" },
                  { id: "favorite", header: "Favorite", cell: (d) => (
                    <Button variant="icon" iconName={favs.has(d.DashboardName) ? "star-filled" : "star"} ariaLabel={`Favorite ${d.DashboardName}`} onClick={() => toggleFav(d.DashboardName)} />
                  ) },
                  { id: "updated", header: "Last updated (UTC)", cell: (d) => fmtDate(d.LastModified) },
                ]}
                empty={{ title: "No dashboards", subtitle: "Create a dashboard to visualize your metrics.", action: <Button href={href("cloudwatch", "dashboards", "create")} onFollow={follow}>Create dashboard</Button> }}
              />
              <DeleteModal
                visible={deleting}
                onDismiss={() => setDeleting(false)}
                resourceType="dashboard"
                names={selected.map((d) => d.DashboardName)}
                onConfirm={async () => { await api.deleteDashboards(selected.map((d) => d.DashboardName)); notify.success(`${selected.length > 1 ? "Dashboards" : "Dashboard"} deleted.`); setSelected([]); t.reload(); }}
              />
            </SpaceBetween>
          ),
        },
        { id: "automatic", label: "Automatic dashboards", content: <CapabilityContainer id="aws.cloudwatch.dashboards.automatic" title="Automatic dashboards" /> },
      ]} />
    </ContentLayout>
  );
}
