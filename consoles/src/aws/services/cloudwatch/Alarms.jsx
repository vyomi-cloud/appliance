import { useMemo, useState } from "react";
import Button from "@cloudscape-design/components/button";
import ButtonDropdown from "@cloudscape-design/components/button-dropdown";
import ContentLayout from "@cloudscape-design/components/content-layout";
import Header from "@cloudscape-design/components/header";
import Link from "@cloudscape-design/components/link";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Toggle from "@cloudscape-design/components/toggle";
import { useAsync } from "../../../common/useAsync.js";
import { useNotify } from "../../../common/notify.jsx";
import { follow, href, navigate } from "../../../common/router.js";
import { fmtDate } from "../../kit/common.jsx";
import ResourceTable from "../../kit/ResourceTable.jsx";
import DeleteModal from "../../kit/DeleteModal.jsx";
import { AlarmStateBadge, actionsText, conditionText } from "./common.jsx";
import * as api from "./api.js";

const STATE_OPTIONS = [{ label: "Any state", value: "" }, { label: "OK", value: "OK" }, { label: "In alarm", value: "ALARM" }, { label: "Insufficient data", value: "INSUFFICIENT_DATA" }];
const TYPE_OPTIONS = [{ label: "Any type", value: "" }, { label: "Metric alarm", value: "MetricAlarm" }, { label: "Composite alarm", value: "CompositeAlarm" }];
const ACTIONS_OPTIONS = [{ label: "Any actions status", value: "" }, { label: "Enabled", value: "enabled" }, { label: "Disabled", value: "disabled" }];

export default function Alarms({ query }) {
  const notify = useNotify();
  const t = useAsync(() => api.describeAlarms({}), []);
  const [selected, setSelected] = useState([]);
  const [deleting, setDeleting] = useState(false);
  const [hideAutoScaling, setHideAutoScaling] = useState(false);
  const [state, setState] = useState(query?.state || "");
  const [type, setType] = useState("");
  const [actionsStatus, setActionsStatus] = useState("");

  const all = useMemo(() => {
    const metric = (t.data?.MetricAlarms || []).map((a) => ({ ...a, Kind: "MetricAlarm" }));
    const composite = (t.data?.CompositeAlarms || []).map((a) => ({ ...a, Kind: "CompositeAlarm" }));
    return [...metric, ...composite];
  }, [t.data]);

  const isAutoScaling = (a) => ["OKActions", "AlarmActions", "InsufficientDataActions"].some((k) => (a[k] || []).some((arn) => arn.includes(":autoscaling:")));

  const items = all
    .filter((a) => !hideAutoScaling || !isAutoScaling(a))
    .filter((a) => !state || a.StateValue === state)
    .filter((a) => !type || a.Kind === type)
    .filter((a) => !actionsStatus || (actionsStatus === "enabled") === !!a.ActionsEnabled);

  return (
    <ContentLayout header={<Header variant="h1">Alarms</Header>}>
      <SpaceBetween size="l">
        <SpaceBetween direction="horizontal" size="l">
          <Select selectedOption={STATE_OPTIONS.find((o) => o.value === state)} onChange={({ detail }) => setState(detail.selectedOption.value)} options={STATE_OPTIONS} ariaLabel="Alarm state" />
          <Select selectedOption={TYPE_OPTIONS.find((o) => o.value === type)} onChange={({ detail }) => setType(detail.selectedOption.value)} options={TYPE_OPTIONS} ariaLabel="Alarm type" />
          <Select selectedOption={ACTIONS_OPTIONS.find((o) => o.value === actionsStatus)} onChange={({ detail }) => setActionsStatus(detail.selectedOption.value)} options={ACTIONS_OPTIONS} ariaLabel="Actions status" />
        </SpaceBetween>
        <ResourceTable
          resourceName="Alarms"
          items={items}
          loading={t.loading}
          error={t.error}
          onRefresh={t.reload}
          trackBy="AlarmArn"
          selectionType="single"
          selectedItems={selected}
          onSelectionChange={setSelected}
          filterPlaceholder="Search"
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              <Toggle checked={hideAutoScaling} onChange={({ detail }) => setHideAutoScaling(detail.checked)}>Hide Auto Scaling alarms</Toggle>
              <Button disabled={!selected.length} onClick={() => setSelected([])}>Clear selection</Button>
              <Button onClick={() => { sessionStorage.setItem("cw.alarmSource", "Alarms"); navigate("cloudwatch", "alarms", "create"); }}>Create composite alarm</Button>
              <ButtonDropdown
                disabled={!selected.length}
                items={[{ id: "delete", text: "Delete" }, { id: "edit", text: "Edit" }]}
                onItemClick={({ detail }) => { if (detail.id === "delete") setDeleting(true); if (detail.id === "edit") { location.hash = `#/cloudwatch/alarms/create?edit=${encodeURIComponent(selected[0].AlarmName)}`; } }}
              >
                Actions
              </ButtonDropdown>
              <Button variant="primary" href={href("cloudwatch", "alarms", "create")} onFollow={follow}>Create alarm</Button>
            </SpaceBetween>
          }
          columns={[
            { id: "name", header: "Name", isRowHeader: true, sortingField: "AlarmName", cell: (a) => <Link href={href("cloudwatch", "alarms", a.AlarmName)} onFollow={follow}>{a.AlarmName}</Link> },
            { id: "state", header: "State", cell: (a) => <AlarmStateBadge state={a.StateValue} /> },
            { id: "updated", header: "Last state update (UTC)", cell: (a) => fmtDate(a.StateUpdatedTimestamp) },
            { id: "conditions", header: "Conditions", cell: (a) => conditionText(a) },
            { id: "actions", header: "Actions", cell: (a) => actionsText(a) },
          ]}
          empty={{ title: "No alarms", subtitle: "Create an alarm to get notified about metric or alarm state changes.", action: <Button href={href("cloudwatch", "alarms", "create")} onFollow={follow}>Create alarm</Button> }}
        />
        <DeleteModal
          visible={deleting}
          onDismiss={() => setDeleting(false)}
          resourceType="alarm"
          names={selected.map((a) => a.AlarmName)}
          onConfirm={async () => { await api.deleteAlarms(selected.map((a) => a.AlarmName)); notify.success(`${selected.length > 1 ? "Alarms" : "Alarm"} deleted.`); setSelected([]); t.reload(); }}
        />
      </SpaceBetween>
    </ContentLayout>
  );
}
