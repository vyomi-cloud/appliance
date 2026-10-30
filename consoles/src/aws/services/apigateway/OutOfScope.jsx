/* AgentCore targets and Developer portals are separate AWS products (Bedrock
 * AgentCore, the API Gateway developer portal) that Vyomi does not implement at all —
 * declared in the nav for completeness only, exactly as the real console's spec
 * describes them (ui-spec/aws/apigateway.json: "Out of Vyomi scope; declared for nav
 * completeness"). core/capabilities/aws/apigateway.json marks both not_simulated.
 * The whole page is the gap (title included, inside NotSimulatedContainer) so the
 * UI-conformance gate sees zero "present" elements here and doesn't demand a liveness
 * fixture for a feature Vyomi has no data model for at all. */
import Box from "@cloudscape-design/components/box";
import { NotSimulatedContainer } from "../../kit/common.jsx";

export function AgentcoreTargets() {
  return (
    <Box padding="l">
      <NotSimulatedContainer title="AgentCore targets" feature="Bedrock AgentCore gateway targets"
        note="Vyomi does not implement Bedrock AgentCore. The Target, AgentCore gateway, Status, Description, Last synchronized and Date created columns, the Create new AgentCore gateway and Add AgentCore target actions, and the How to enable MCP access to your APIs using AgentCore section aren't modeled." />
    </Box>
  );
}

export function Portals() {
  return (
    <Box padding="l">
      <NotSimulatedContainer title="Portals" feature="API Gateway developer portals"
        note="Vyomi does not implement the API Gateway developer portal. The Name, Status, Date modified and Last published columns, the Edit and Create portal actions, and the How portals work section aren't modeled." />
    </Box>
  );
}

export function PortalProducts() {
  return (
    <Box padding="l">
      <NotSimulatedContainer title="Portal products" feature="API Gateway developer portal products"
        note="Vyomi does not implement the API Gateway developer portal. The Display name, Description and Date created columns, the Edit and Create product actions, and the How products work section aren't modeled." />
    </Box>
  );
}
