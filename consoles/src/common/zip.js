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

/** Read a .zip (stored or deflate) -> [{ name, data: Uint8Array }]. Deflate uses the browser's DecompressionStream. */
export async function unzip(buf) {
  const b = new Uint8Array(buf), dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  let e = b.length - 22;
  while (e >= 0 && dv.getUint32(e, true) !== 0x06054b50) e--;
  if (e < 0) throw new Error("not a zip file");
  const n = dv.getUint16(e + 10, true);
  let p = dv.getUint32(e + 16, true);
  const dec = new TextDecoder(), out = [];
  for (let i = 0; i < n; i++) {
    if (dv.getUint32(p, true) !== 0x02014b50) throw new Error("bad zip directory");
    const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), nlen = dv.getUint16(p + 28, true), xlen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true);
    const lho = dv.getUint32(p + 42, true), name = dec.decode(b.subarray(p + 46, p + 46 + nlen));
    p += 46 + nlen + xlen + clen;
    if (name.endsWith("/")) continue;
    const start = lho + 30 + dv.getUint16(lho + 26, true) + dv.getUint16(lho + 28, true), raw = b.subarray(start, start + csize);
    if (method === 0) out.push({ name, data: raw.slice() });
    else if (method === 8) out.push({ name, data: new Uint8Array(await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).arrayBuffer()) });
    else throw new Error(`${name}: unsupported zip method ${method}`);
  }
  return out;
}
