/* Compute sizes per substrate. The lists themselves come from the server (describe-instance-types / machineTypes.list / vmSizes),
 * which answers only with sizes the substrate can run (core/compute_sizes.py); each item carries `vyomiSubstrate` ("nano" | "mesh")
 * when the list is restricted. This helper only words the note shown above a size picker. */
const LABEL = { nano: "Nano (browser VM)", mesh: "Mesh (Docker)" };

/** "nano" | "mesh" | "" for a list of size rows (field name differs per cloud, so pass a getter or use the default). */
export const sizeSubstrate = (rows, get = (r) => r.Substrate || r.vyomiSubstrate) => {
  for (const r of rows || []) { const s = get(r); if (s) return s; }
  return "";
};

/** The picker note, or "" on an unrestricted appliance. */
export function sizesNote(substrate) {
  if (!LABEL[substrate]) return "";
  const tail = substrate === "nano" ? " Each in-browser VM runs 1 vCPU with the size's memory." : "";
  return `Showing sizes available on ${LABEL[substrate]}.${tail}`;
}
