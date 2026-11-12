import StateMachines from "./StateMachines.jsx";
import CreateStateMachine from "./CreateStateMachine.jsx";
import StateMachineDetail from "./StateMachineDetail.jsx";
import StartExecution from "./StartExecution.jsx";
import ExecutionDetail from "./ExecutionDetail.jsx";
import Activities from "./Activities.jsx";
import ActivityDetail from "./ActivityDetail.jsx";

export default {
  nav: [
    { type: "link", text: "State machines", href: "#/states/state-machines" },
    { type: "link", text: "Activities", href: "#/states/activities" },
  ],
  routes: [
    { pattern: "/states", component: StateMachines, crumbs: () => [{ text: "State machines", href: "#/states/state-machines" }] },
    { pattern: "/states/state-machines", component: StateMachines, crumbs: () => [{ text: "State machines", href: "#/states/state-machines" }] },
    { pattern: "/states/create", component: CreateStateMachine, crumbs: () => [{ text: "State machines", href: "#/states/state-machines" }, { text: "Create state machine", href: "#/states/create" }] },
    { pattern: "/states/state-machines/:name", component: StateMachineDetail, crumbs: (p) => [{ text: "State machines", href: "#/states/state-machines" }, { text: p.name, href: `#/states/state-machines/${p.name}` }] },
    { pattern: "/states/state-machines/:name/start", component: StartExecution, crumbs: (p) => [{ text: "State machines", href: "#/states/state-machines" }, { text: p.name, href: `#/states/state-machines/${p.name}` }, { text: "New execution", href: `#/states/state-machines/${p.name}/start` }] },
    { pattern: "/states/state-machines/:name/executions/:execName", component: ExecutionDetail, crumbs: (p) => [{ text: "State machines", href: "#/states/state-machines" }, { text: p.name, href: `#/states/state-machines/${p.name}` }, { text: p.execName, href: `#/states/state-machines/${p.name}/executions/${p.execName}` }] },
    { pattern: "/states/activities", component: Activities, crumbs: () => [{ text: "Activities", href: "#/states/activities" }] },
    { pattern: "/states/activities/:name", component: ActivityDetail, crumbs: (p) => [{ text: "Activities", href: "#/states/activities" }, { text: p.name, href: `#/states/activities/${p.name}` }] },
  ],
};
