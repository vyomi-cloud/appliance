/* Microsoft Foundry hub (Azure portal "AI Foundry" menu view): lists the AI resources the real ARM wire holds.
 * Thin adapter only: Microsoft.CognitiveServices/accounts (core/azure_cognitiveservices_core.py) and
 * Microsoft.Search/searchServices (core/azure_search_core.py), both through the subscription-scope ARM list. */
import { restJson } from "../../../common/wire.js";
import { armType, getSubscription, parseId } from "../../kit/arm.js";

const cogs = armType("Microsoft.CognitiveServices", "accounts", "2024-10-01");
const SEARCH_API = "2023-11-01";

const shape = (v) => ({ ...v, resourceGroup: parseId(v.id).resourceGroup });
export const listAccounts = async () => (await cogs.list()).map(shape);
export const listSearch = async () =>
  ((await restJson("GET", `/subscriptions/${getSubscription()}/providers/Microsoft.Search/searchServices`, { query: { "api-version": SEARCH_API } })).value || []).map(shape);
