/* Where an SDK or CLI should point to reach THIS Vyomi environment.
 *   offline appliance / sandbox → this page's origin (same native wire the console uses)
 *   Nano (in-browser)           → the local relay started with `npx vyomi-tunnel` */
const substrate = () => (typeof document !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content) || "offline";

export function sdkEndpoint() {
  if (substrate() === "nano") {
    return { url: "http://127.0.0.1:8090", nano: true, note: "Nano runs in this browser tab: start the local relay first with `npx vyomi-tunnel`, keep this tab open." };
  }
  return { url: location.origin, nano: false, note: "" };
}
