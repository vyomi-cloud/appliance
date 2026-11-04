/* AWS Marketplace (Vyomi edition) native-wire calls — service aws-marketplace (Catalog API shapes + Vyomi subscription ops). */
import { awsRest } from "../../common/wire.js";

const CAT = "AWSMarketplace";
export async function listEntities(entityType, filters = []) {
  const out = []; let NextToken;
  do { const r = await awsRest("aws-marketplace", "POST", "/ListEntities", { body: { Catalog: CAT, EntityType: entityType, MaxResults: 50, NextToken, ...(filters.length ? { FilterList: filters } : {}) } }); out.push(...(r.EntitySummaryList || [])); NextToken = r.NextToken; } while (NextToken);
  return out;
}
export const describeEntity = (entityId) => awsRest("aws-marketplace", "GET", "/DescribeEntity", { query: { catalog: CAT, entityId } });
export const subscribe = (productId) => awsRest("aws-marketplace", "POST", "/agreements", { body: { productId, acceptEula: true } });
export const unsubscribe = (agreementId) => awsRest("aws-marketplace", "DELETE", `/agreements/${agreementId}`);
export const listAgreements = async (status = "ACTIVE") => (await awsRest("aws-marketplace", "GET", "/agreements", { query: { status } })).Agreements || [];
