/* Where an SDK or CLI should point to reach THIS Vyomi environment.
 *   offline appliance / sandbox → this page's origin (same native wire the console uses)
 *   Nano (in-browser)           → the local relay started with `npx vyomi-tunnel` */
const substrate = () => (typeof document !== "undefined" && document.querySelector('meta[name="vyomi-substrate"]')?.content) || "offline";

/** An absolute URL, on the host the user's SDK/CLI/browser actually reaches, for a ROOT-relative router path (`/azure-data/blob/<acct>`).
 *  Nano: the local relay (`npx vyomi-tunnel`), never this page's own `/nano/_wire` service-worker path; offline: this origin. */
export const extUrl = (path) => sdkEndpoint().url.replace(/\/$/, "") + path;

/** Is the console running on Nano (in-browser)? Used where a connect string differs (e.g. Service Bus raw AMQP on the relay). */
export const isNano = () => substrate() === "nano";

export function sdkEndpoint() {
  if (substrate() === "nano") {
    return { url: "http://127.0.0.1:8090", nano: true, note: "Nano runs in this browser tab: start the local relay first with `npx vyomi-tunnel`, keep this tab open." };
  }
  return { url: location.origin, nano: false, note: "" };
}
