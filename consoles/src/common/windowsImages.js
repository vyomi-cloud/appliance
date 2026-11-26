// Windows VM images are DISABLED (owner decision 2026-11-26): still listed, shown disabled with a reason, never selectable.
// Re-enable by flipping WINDOWS_IMAGES_ENABLED (and core/compute_sizes.py WINDOWS_IMAGES_ENABLED for the backend).
// See docs/architecture/v4.0/branches/disable-windows-images.md
export const WINDOWS_IMAGES_ENABLED = false;
export const WINDOWS_IMAGES_REASON = "Windows images are not supported yet.";
export const isWindowsImage = (x) => /windows/i.test(typeof x === "string" ? x : (x?.name || x?.platformDetails || ""));
export const windowsDisabled = (x) => !WINDOWS_IMAGES_ENABLED && isWindowsImage(x);
