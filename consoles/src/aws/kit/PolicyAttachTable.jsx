/* Searchable, filterable, paginated table of managed policies with checkboxes: the "Attach policies directly" picker of
 * user / role / group > Add permissions. policies = ListPolicies result; value = selected ARNs; attached = ARNs that cannot be picked again. */
import { useMemo, useState } from "react";
import Table from "@cloudscape-design/components/table";
import TextFilter from "@cloudscape-design/components/text-filter";
import Pagination from "@cloudscape-design/components/pagination";
import Header from "@cloudscape-design/components/header";
import Select from "@cloudscape-design/components/select";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Box from "@cloudscape-design/components/box";

export const policyType = (p) => (/^arn:[^:]*:iam::aws:policy\//.test(p.Arn || "") ? "AWS managed" : "Customer managed");
const TYPES = [{ value: "all", label: "All types" }, { value: "AWS managed", label: "AWS managed" }, { value: "Customer managed", label: "Customer managed" }];

export default function PolicyAttachTable({ policies, value, onChange, attached = [], pageSize = 10 }) {
  const [text, setText] = useState("");
  const [type, setType] = useState("all");
  const [page, setPage] = useState(1);
  const rows = useMemo(() => policies.filter((p) => (type === "all" || policyType(p) === type) && (!text || p.PolicyName.toLowerCase().includes(text.toLowerCase()))).sort((a, b) => a.PolicyName.localeCompare(b.PolicyName)), [policies, text, type]);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const view = rows.slice((Math.min(page, pages) - 1) * pageSize, Math.min(page, pages) * pageSize);
  return (
    <Table variant="embedded" items={view} trackBy="Arn" selectionType="multi" ariaLabels={{ selectionGroupLabel: "Policies", itemSelectionLabel: (_, i) => `Select ${i.PolicyName}`, allItemsSelectionLabel: () => "Select all" }}
      selectedItems={policies.filter((p) => value.includes(p.Arn))} isItemDisabled={(p) => attached.includes(p.Arn)}
      onSelectionChange={({ detail }) => onChange([...new Set([...value.filter((a) => !view.some((v) => v.Arn === a)), ...detail.selectedItems.map((i) => i.Arn)])])}
      header={<Header counter={`(${rows.length})`} description="Choose one or more policies to attach.">Permissions policies</Header>}
      filter={<SpaceBetween direction="horizontal" size="xs">
        <TextFilter filteringText={text} filteringPlaceholder="Search" filteringAriaLabel="Filter policies" onChange={({ detail }) => { setText(detail.filteringText); setPage(1); }} countText={`${rows.length} matches`} />
        <Select ariaLabel="Policy type" selectedOption={TYPES.find((t) => t.value === type)} options={TYPES} onChange={({ detail }) => { setType(detail.selectedOption.value); setPage(1); }} />
      </SpaceBetween>}
      pagination={<Pagination currentPageIndex={Math.min(page, pages)} pagesCount={pages} onChange={({ detail }) => setPage(detail.currentPageIndex)} />}
      columnDefinitions={[
        { id: "n", header: "Policy name", cell: (p) => p.PolicyName },
        { id: "t", header: "Type", cell: (p) => policyType(p) },
        { id: "u", header: "Used as", cell: (p) => (attached.includes(p.Arn) ? "Already attached" : Number(p.AttachmentCount) > 0 ? `Permissions policy (${p.AttachmentCount})` : "None") },
      ]}
      empty={<Box textAlign="center" color="inherit"><b>No policies match</b></Box>} />
  );
}
