/* AgentCore targets is a separate AWS product (Bedrock AgentCore gateway targets) that
 * Vyomi does not implement at all — declared in the nav for completeness only, exactly as
 * the real console's spec describes it (ui-spec/aws/apigateway.json: "Out of Vyomi scope;
 * declared for nav completeness"). core/capabilities/aws/apigateway.json marks it
 * not_simulated. The whole page is the gap (title included, inside NotSimulatedContainer)
 * so the UI-conformance gate sees zero "present" elements here and doesn't demand a
 * liveness fixture for a feature Vyomi has no data model for at all.
 *
 * Developer portals (Portals, Portal products) moved to Portals.jsx / PortalProducts.jsx:
 * `apigatewayv2` (the real CLI/SDK service behind API Gateway's console) publishes a
 * genuine, documented control plane for them (CreatePortal, CreatePortalProduct, …) —
 * see core/apigatewayv2_core.py — so they are built for real, not honest gaps. */
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
