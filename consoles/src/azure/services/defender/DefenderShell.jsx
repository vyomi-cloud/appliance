/* Microsoft Defender for Cloud's own left nav (the service IS the nav tree, like Cost Management). */
import ResourceBlade from "../../kit/ResourceBlade.jsx";
import { Glyph } from "../../kit/common.jsx";

export const MENU = [
  { id: "overview", label: "Overview" },
  { id: "gettingstarted", label: "Getting started" },
  { id: "recommendations", label: "Recommendations" },
  { id: "attackpath", label: "Attack path analysis" },
  { id: "alerts", label: "Security alerts" },
  { id: "inventory", label: "Inventory" },
  { id: "explorer", label: "Cloud Security Explorer" },
  { id: "workbooks", label: "Workbooks" },
  { id: "community", label: "Community" },
  { id: "diagnose", label: "Diagnose and solve problems" },
  { group: "Cloud Security", items: [
    { id: "posture", label: "Security posture" },
    { id: "compliance", label: "Regulatory compliance" },
    { id: "workloadprotections", label: "Workload protections" },
    { id: "datasecurity", label: "Data security" },
    { id: "firewallmanager", label: "Firewall Manager" },
    { id: "devops", label: "DevOps security" },
  ] },
  { group: "Management", items: [
    { id: "environment", label: "Environment settings" },
    { id: "solutions", label: "Security solutions" },
    { id: "automation", label: "Workflow automation" },
  ] },
];

export const LABEL = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));

export default function DefenderShell({ active, children }) {
  return (
    <ResourceBlade title="Microsoft Defender for Cloud" subtitle={LABEL[active] && `| ${LABEL[active]}`} glyph={<Glyph id="defender" size={28} />}
      menu={MENU} active={active} hrefFor={(id) => `#/defender/${id}`}>
      {children}
    </ResourceBlade>
  );
}
