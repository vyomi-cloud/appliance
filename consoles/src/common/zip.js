/* Store-only ZIP writer (no compression) so Nano, which has no server route to stream a zip, can still hand over the bundle. */
const T = (() => { const t = []; for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc = (b) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = T[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const u16 = (n) => [n & 255, (n >>> 8) & 255], u32 = (n) => [n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255];

/** entries: [{ name, data: Uint8Array }] -> Blob (application/zip) */
export function zipBlob(entries) {
  const enc = new TextEncoder(), parts = [], central = [];
  let off = 0;
  for (const { name, data } of entries) {
    const nm = enc.encode(name), c = crc(data);
    const head = Uint8Array.from([0x50, 0x4b, 3, 4, 20, 0, 0, 8, 0, 0, 0, 0, 0x21, 0, ...u32(c), ...u32(data.length), ...u32(data.length), ...u16(nm.length), 0, 0]);
    parts.push(head, nm, data);
    central.push(Uint8Array.from([0x50, 0x4b, 1, 2, 20, 0, 20, 0, 0, 8, 0, 0, 0, 0, 0x21, 0, ...u32(c), ...u32(data.length), ...u32(data.length), ...u16(nm.length), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ...u32(off)]), nm);
    off += head.length + nm.length + data.length;
  }
  const cdSize = central.reduce((s, p) => s + p.length, 0);
  parts.push(...central, Uint8Array.from([0x50, 0x4b, 5, 6, 0, 0, 0, 0, ...u16(entries.length), ...u16(entries.length), ...u32(cdSize), ...u32(off), 0, 0]));
  return new Blob(parts, { type: "application/zip" });
}

export const bundleEntries = (bundle) => [
  ...Object.entries(bundle.files || {}).map(([name, text]) => ({ name, data: new TextEncoder().encode(text) })),
  ...Object.entries(bundle.binaries || {}).map(([name, b64]) => ({ name, data: Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0)) })),
];
