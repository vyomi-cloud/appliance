import VirtualMachines from "./VirtualMachines.jsx";
import CreateVirtualMachine from "./CreateVirtualMachine.jsx";
import VmBlade, { MENU } from "./VmBlade.jsx";

const label = Object.fromEntries(MENU.flatMap((m) => (m.group ? m.items : [m])).map((i) => [i.id, i.label]));
const vm = (p) => ({ text: p.name, href: `#/vms/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/vms", component: VirtualMachines },
    { pattern: "/vms/create", component: CreateVirtualMachine, crumbs: () => [{ text: "Create a virtual machine", href: "#/vms/create" }] },
    { pattern: "/vms/:rg/:name", component: VmBlade, crumbs: (p) => [vm(p)] },
    { pattern: "/vms/:rg/:name/:panel", component: VmBlade, crumbs: (p) => [vm(p), { text: label[p.panel] || p.panel, href: `#/vms/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
