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

/* Images / OS / architecture on Nano. The in-browser VM (wasm/vm) boots any of the catalog images below (core/compute_sizes.py NANO_CATALOG is the
 * server twin; wasm/vm/images.json holds the boot files). Each image states exactly what it contains (`summary`); Alpine 3.21 is the default.
 * The 64-bit x86_64 / riscv64 emulated guests (Phase B) are listed but DISABLED with `reason`. Mesh and offline keep the full catalogs. */
/** True on Nano. The size list the server answered is authoritative ("nano" | "mesh" mark); until it has loaded, the Nano page meta decides. */
export const onNano = (sizeRows) => { const s = sizeSubstrate(sizeRows); return s ? s === "nano" : isNano(); };

export const PHASE_B_REASON = "x86_64/riscv64 emulation: coming later (needs legal review, ~90-200 MB download)";
export const NANO_CATALOG = [
  { key: "alpine", runnable: true, arch: "i386", archLabel: "32-bit (x86)", summary: "Alpine Linux 3.21, 32-bit x86: Python 3, pip, apk, git",
    aws: { name: "Alpine Linux 3.21 (i386) - Vyomi Nano", quickStart: "Alpine Linux" },
    gcp: { os: ["vyomi-nano-cloud", "alpine-3-21-i386", "Alpine Linux", "Alpine Linux 3.21 (32-bit x86)"] },
    azure: { display: "Alpine Linux 3.21 (32-bit x86) - Vyomi Nano", arch: "x64", ref: { publisher: "vyomi", offer: "alpine-nano", sku: "3.21-i386", version: "latest" } } },
  { key: "debian", runnable: true, arch: "i386", archLabel: "32-bit (x86)", summary: "Debian GNU/Linux 12 (bookworm), 32-bit x86: Python 3, pip, apt/dpkg, git",
    aws: { name: "Debian 12 (i386) - Vyomi Nano", quickStart: "Debian" },
    gcp: { os: ["vyomi-nano-cloud", "debian-12-i386", "Debian GNU/Linux (Vyomi Nano)", "Debian GNU/Linux 12 (bookworm, 32-bit x86)"] },
    azure: { display: "Debian GNU/Linux 12 (32-bit x86) - Vyomi Nano", arch: "x64", ref: { publisher: "vyomi", offer: "debian-nano", sku: "12-i386", version: "latest" } } },
  { key: "buildroot", runnable: true, arch: "i386", archLabel: "32-bit (x86)", summary: "Buildroot 2024.05, 32-bit x86, minimal: busybox shell only (no git, Python, pip or package manager)",
    aws: { name: "Buildroot 2024.05 (i386, minimal) - Vyomi Nano", quickStart: "Buildroot" },
    gcp: { os: ["vyomi-nano-cloud", "buildroot-2024-i386", "Buildroot Linux (Vyomi Nano)", "Buildroot 2024.05 (32-bit x86, minimal: busybox only)"] },
    azure: { display: "Buildroot 2024.05 (32-bit x86, minimal) - Vyomi Nano", arch: "x64", ref: { publisher: "vyomi", offer: "buildroot-nano", sku: "2024-i386", version: "latest" } } },
  { key: "debian64", runnable: false, reason: PHASE_B_REASON, arch: "x86_64", archLabel: "64-bit (x86)",
    summary: "Debian 12, 64-bit x86_64 (emulated, container2wasm/Bochs). " + PHASE_B_REASON + ". A riscv64 build (TinyEMU) is planned the same way; riscv64 is not a native architecture of AWS, GCP or Azure.",
    aws: { name: "Debian 12 (x86_64, emulated) - Vyomi Nano", quickStart: "Debian" },
    gcp: { os: ["vyomi-nano-cloud", "debian-12-x86-64-emulated", "Debian GNU/Linux x86_64 (emulated, Vyomi Nano)", "Debian GNU/Linux 12 (64-bit x86_64, emulated)"] },
    azure: { display: "Debian GNU/Linux 12 (64-bit x86_64, emulated) - Vyomi Nano", arch: "x64", ref: { publisher: "vyomi", offer: "debian-nano", sku: "12-x86_64-emulated", version: "latest" } } },
];
export const NANO_RUNNABLE = NANO_CATALOG.filter((e) => e.runnable);
export const NANO_DEFAULT = NANO_CATALOG[0];
/** Back-compat: the default (Alpine) entry per cloud. */
export const NANO_IMAGES = { aws: { ...NANO_DEFAULT.aws, arch: NANO_DEFAULT.archLabel }, gcp: { os: NANO_DEFAULT.gcp.os }, azure: NANO_DEFAULT.azure };
/** Catalog entry for an AMI name / image text, or undefined. */
export const nanoEntryByAwsName = (name) => NANO_CATALOG.find((e) => name && String(name).startsWith(e.aws.name));
export const nanoEntryByAzureDisplay = (d) => NANO_CATALOG.find((e) => e.azure.display === d);

export const NANO_REASON = "Not available on Nano: runs only in a Mesh";
/** Reason a row is disabled: its own (a Phase B image states why) or the generic one. */
export const rowReason = (r) => (r && (r.vyomiReason || r.Reason)) || NANO_REASON;
/** Back-compat: the default image's contents. Each image has its own `summary`; pickers show the SELECTED image's. */
export const IMAGE_SUMMARY = NANO_DEFAULT.summary;
export const IMAGES_NOTE = `Nano runs VMs inside your browser. Runnable images, each with exactly what it contains: ${NANO_RUNNABLE.map((e) => e.summary).join("; ")}. Everything else is greyed out with the reason; launch a Mesh for the full catalog.`;
/** A size / image row the substrate can run. Nano lists everything and flags the rest `vyomiRunnable: false` (core/compute_sizes.py); other substrates never flag. */
export const runnableRow = (r) => !(r && (r.vyomiRunnable === false || r.vyomiRunnable === "false" || r.Runnable === false));

/** GCP boot-disk OS list on Nano: runnable catalog images first (Alpine selected), then the disabled Phase B ones, then Google's own public images (all disabled).
 *  Returns {list, off(i), reason(i), summary(entry)}. Off Nano the base list is returned unchanged. */
export function gcpOsList(nano, base) {
  if (!nano) return { list: base, off: () => false, reason: () => "", summary: () => "" };
  const run = NANO_RUNNABLE.map((e) => e.gcp.os), later = NANO_CATALOG.filter((e) => !e.runnable).map((e) => e.gcp.os);
  const list = [...run, ...later, ...base];
  return { list, off: (i) => i >= run.length, reason: (i) => (i < run.length + later.length ? PHASE_B_REASON : NANO_REASON),
           summary: (entry) => (NANO_CATALOG.find((e) => entry && e.gcp.os[1] === entry[1]) || {}).summary || "" };
}
