import { Table, TableContainer } from "@mui/material";

// Scrollable grid: horizontal scroll when columns overflow, vertical scroll (sticky header)
// once the table is taller than maxHeight. Drop-in replacement for <Table>.
export const GRID_MAX_HEIGHT = "min(70vh, 640px)";

export default function ScrollTable({ maxHeight = GRID_MAX_HEIGHT, containerSx, sx, children, ...rest }) {
  return (
    <TableContainer sx={{ maxHeight, overflow: "auto", ...containerSx }} tabIndex={0}>
      <Table stickyHeader {...rest} sx={sx}>{children}</Table>
    </TableContainer>
  );
}
