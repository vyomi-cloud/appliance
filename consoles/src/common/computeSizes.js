/* Compute sizes per substrate. The lists themselves come from the server (describe-instance-types / machineTypes.list / vmSizes),
 * which answers only with sizes the substrate can run (core/compute_sizes.py); each item carries `vyomiSubstrate` ("nano" | "mesh")
 * when the list is restricted. This helper only words the note shown above a size picker. */
import { isNano } from "./NanoVmPanel.jsx";
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

/* Images / OS / architecture on Nano. The in-browser VM (wasm/vm) boots ONE guest, Alpine Linux 3.21 on a 32-bit x86 kernel, whatever image the
 * cloud record names, so Nano offers exactly that image per cloud (the server lists / accepts the same one: core/compute_sizes.py NANO_IMAGES).
 * Mesh and offline keep the full catalogs. */
/** True on Nano. The size list the server answered is authoritative ("nano" | "mesh" mark); until it has loaded, the Nano page meta decides. */
export const onNano = (sizeRows) => { const s = sizeSubstrate(sizeRows); return s ? s === "nano" : isNano(); };

export const NANO_IMAGES = {
  aws: { name: "Alpine Linux 3.21 (i386) - Vyomi Nano", quickStart: "Alpine Linux", arch: "32-bit (x86)" },
  gcp: { os: ["vyomi-nano-cloud", "alpine-3-21-i386", "Alpine Linux", "Alpine Linux 3.21 (32-bit x86)"] },
  azure: { display: "Alpine Linux 3.21 (32-bit x86) - Vyomi Nano", arch: "x64", ref: { publisher: "vyomi", offer: "alpine-nano", sku: "3.21-i386", version: "latest" } },
};

export const NANO_REASON = "Not available on Nano: runs only in a Mesh";
export const IMAGES_NOTE = "Nano runs VMs inside your browser: only Alpine Linux 3.21 (32-bit x86) can run here. Everything else is greyed out; launch a Mesh for the full catalog.";
/** A size / image row the substrate can run. Nano lists everything and flags the rest `vyomiRunnable: false` (core/compute_sizes.py); other substrates never flag. */
export const runnableRow = (r) => !(r && (r.vyomiRunnable === false || r.vyomiRunnable === "false" || r.Runnable === false));
