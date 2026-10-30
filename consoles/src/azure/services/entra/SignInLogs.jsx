/* Default Directory | Sign-in logs — azure.entra.sign_in_logs is not_simulated: Vyomi has
 * no interactive sign-in flow to generate telemetry from. An honest gap renders ONLY its
 * title and a NotSimulated note, never a skeleton of the real grid over permanently-empty
 * data (copied column headers, disabled tabs, empty rows). */
import { CapabilityContainer } from "../../kit/Capability.jsx";
import EntraShell from "./EntraShell.jsx";

export default function SignInLogs() {
  return (
    <EntraShell active="signinlogs" title="Default Directory | Sign-in logs">
      <CapabilityContainer id="azure.entra.sign_in_logs" title="Sign-in logs" />
    </EntraShell>
  );
}
