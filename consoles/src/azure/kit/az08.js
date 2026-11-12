/* Thin ARM helpers shared by the AZ-08 pages (Files, Storage Mover, AI Search, Marketplace, quota/billing extras).
 * Everything goes over the same native ARM wire the rest of the Azure lens uses. */
import { restJson } from "../../common/wire.js";
import { getSubscription } from "./arm.js";

export const subPath = (s) => `/subscriptions/${s || getSubscription()}`;
export const rgPath = (rg, s) => `${subPath(s)}/resourceGroups/${encodeURIComponent(rg)}`;
/** ARM call with an api-version (default is accepted by every AZ-08 engine). */
export const arm = (method, path, body, query = {}, version = "2024-01-01") =>
  restJson(method, path, { query: { "api-version": version, ...query }, body });
export const armList = async (path, query) => (await arm("GET", path, undefined, query)).value || [];

export const b64 = (bytes) => { let s = ""; const u = new Uint8Array(bytes); for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000)); return btoa(s); };
export const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
export const money = (v) => `$${Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
