/* Shared CSV download (the exact action labels the native console uses differ per page —
 * "Download users (Preview)", "Download groups" — so each list wires its own ToolbarButton
 * around this, rather than relying on BrowseGrid's generic "Export to CSV"). */
export function downloadCsv(filename, columns, rows) {
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const text = [columns.map((c) => esc(c.label)).join(","), ...rows.map((r) => columns.map((c) => esc(c.csv ? c.csv(r) : (c.value ? c.value(r) : r[c.key]))).join(","))].join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
