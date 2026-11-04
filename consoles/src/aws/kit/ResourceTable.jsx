/* The console's standard resource list: counter header, actions, text filter,
 * pagination, column preferences, selection. Every service list page is this. */
import { useMemo, useState } from "react";
import Table from "@cloudscape-design/components/table";
import Header from "@cloudscape-design/components/header";
import TextFilter from "@cloudscape-design/components/text-filter";
import Pagination from "@cloudscape-design/components/pagination";
import CollectionPreferences from "@cloudscape-design/components/collection-preferences";
import Box from "@cloudscape-design/components/box";
import SpaceBetween from "@cloudscape-design/components/space-between";
import Button from "@cloudscape-design/components/button";

export default function ResourceTable({
  resourceName,            // "Buckets"
  items = [],
  columns,                 // [{id, header, cell, sortingField?, isRowHeader?}]
  loading,
  error,
  onRefresh,
  actions,                 // header action buttons (node)
  selectionType,           // "single" | "multi" | undefined
  selectedItems = [],
  onSelectionChange,
  trackBy = "name",
  filterPlaceholder,
  empty,                   // {title, subtitle, action}
  description,
  info,
  variant = "full-page",
}) {
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(1);
  const [prefs, setPrefs] = useState({ pageSize: 10, visibleContent: columns.map((c) => c.id), wrapLines: false });
  const [sorting, setSorting] = useState({ sortingColumn: columns.find((c) => c.sortingField) || null, isDescending: false });

  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase();
    let xs = f ? items.filter((it) => JSON.stringify(it).toLowerCase().includes(f)) : items;
    const sf = sorting.sortingColumn?.sortingField;
    if (sf) {
      xs = [...xs].sort((a, b) => String(a[sf] ?? "").localeCompare(String(b[sf] ?? ""), undefined, { numeric: true }));
      if (sorting.isDescending) xs.reverse();
    }
    return xs;
  }, [items, filter, sorting]);

  const pages = Math.max(1, Math.ceil(filtered.length / prefs.pageSize));
  const shown = filtered.slice((page - 1) * prefs.pageSize, page * prefs.pageSize);
  const counter = selectedItems.length && selectionType ? `(${selectedItems.length}/${items.length})` : `(${items.length})`;

  return (
    <Table
      variant={variant === "full-page" ? "container" : variant}   // the rounded card on every list page
      items={shown}
      loading={loading}
      loadingText={`Loading ${resourceName.toLowerCase()}`}
      trackBy={trackBy}
      selectionType={selectionType}
      selectedItems={selectedItems}
      onSelectionChange={({ detail }) => onSelectionChange?.(detail.selectedItems)}
      columnDefinitions={columns}
      columnDisplay={prefs.visibleContent.map((id) => ({ id, visible: true }))}
      wrapLines={prefs.wrapLines}
      sortingColumn={sorting.sortingColumn}
      sortingDescending={sorting.isDescending}
      onSortingChange={({ detail }) => setSorting(detail)}
      stickyHeader
      header={
        <Header
          variant={variant === "full-page" ? "h1" : "h2"}
          counter={loading ? undefined : counter}
          description={description}
          info={info}
          actions={
            <SpaceBetween direction="horizontal" size="xs">
              {onRefresh && <Button iconName="refresh" ariaLabel="Refresh" onClick={onRefresh} />}
              {actions}
            </SpaceBetween>
          }
        >
          {resourceName}
        </Header>
      }
      filter={
        <TextFilter
          filteringText={filter}
          filteringPlaceholder={filterPlaceholder || `Find ${resourceName.toLowerCase()}`}
          countText={filter ? `${filtered.length} match${filtered.length === 1 ? "" : "es"}` : undefined}
          onChange={({ detail }) => { setFilter(detail.filteringText); setPage(1); }}
        />
      }
      pagination={<Pagination currentPageIndex={page} pagesCount={pages} onChange={({ detail }) => setPage(detail.currentPageIndex)} />}
      preferences={
        <CollectionPreferences
          title="Preferences"
          confirmLabel="Confirm"
          cancelLabel="Cancel"
          preferences={prefs}
          onConfirm={({ detail }) => setPrefs(detail)}
          pageSizePreference={{ title: "Page size", options: [10, 25, 50, 100].map((v) => ({ value: v, label: `${v} resources` })) }}
          wrapLinesPreference={{ label: "Wrap lines", description: "Select to see all the text and wrap the lines" }}
          contentDisplayPreference={{ title: "Column preferences", options: columns.map((c) => ({ id: c.id, label: typeof c.header === "string" ? c.header : c.id, alwaysVisible: c.isRowHeader })) }}
        />
      }
      empty={
        error ? (
          <Box textAlign="center" color="text-status-error">
            <b>Failed to load {resourceName.toLowerCase()}</b>
            <Box variant="p" color="inherit">{error.message}</Box>
            {onRefresh && <Button onClick={onRefresh}>Retry</Button>}
          </Box>
        ) : (
          <Box textAlign="center" color="inherit">
            <b>{empty?.title || `No ${resourceName.toLowerCase()}`}</b>
            <Box variant="p" color="inherit">{empty?.subtitle || `You don't have any ${resourceName.toLowerCase()}.`}</Box>
            {empty?.action}
          </Box>
        )
      }
    />
  );
}
