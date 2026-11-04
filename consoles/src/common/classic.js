/* Link to the classic (v3) console for products without a v4 page yet. The offline appliance
 * serves it at <base>/console/<cloud>; Nano ships it as <base>/<cloud>-console.html
 * (wasm/make_pages.py), so the link follows the substrate the bundle was built for. */
const NANO = typeof document !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content === "nano";

export function classicUrl(cloud, svc) {
  const base = location.pathname.split("/v4/")[0];
  return `${base}/${NANO ? `${cloud}-console.html` : `console/${cloud}`}${svc ? "#" + svc : ""}`;
}
