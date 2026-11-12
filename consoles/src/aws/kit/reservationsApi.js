/* Vyomi-only reservations service (core/reservations_core.py): DynamoDB reserved capacity + RDS capacity reservations,
 * each a record with real utilisation math against provisioned tables / running DB instances. rest-json POST /<Operation>. */
import { awsRest } from "../../common/wire.js";

const V = (op, body = {}) => awsRest("vyomi-reservations", "POST", `/${op}`, { body });
export const describeDdbReserved = () => V("DescribeDynamoDBReservedCapacity");
export const purchaseDdbReserved = (b) => V("PurchaseDynamoDBReservedCapacity", b);
export const deleteDdbReserved = (ReservationId) => V("DeleteDynamoDBReservedCapacity", { ReservationId });
export const describeRdsReservations = () => V("DescribeRDSCapacityReservations").then((r) => r.CapacityReservations || []);
export const createRdsReservation = (b) => V("CreateRDSCapacityReservation", b);
export const cancelRdsReservation = (ReservationId) => V("CancelRDSCapacityReservation", { ReservationId });
