/* AWS Cost Explorer over its native wire (X-Amz-Target AWSInsightsIndexService.*, signed as "ce"), plus the Vyomi-only
 * VyomiGetSavings action that feeds the "Saved by Vyomi" dashboard (core/ce_core.py). */
import { awsJson } from "../../../common/wire.js";

const call = (op, body) => awsJson("ce", `AWSInsightsIndexService.${op}`, body, { version: "1.1" });
export const getCostAndUsage = (body) => call("GetCostAndUsage", body);
export const getCostForecast = (body) => call("GetCostForecast", body);
export const getSavings = () => call("VyomiGetSavings", {});
