import { useEffect, useState } from "react";
import { Button } from "@fluentui/react-components";
import MonitorShell from "./MonitorShell.jsx";
import { listWorkspaces } from "./api.js";
import { CapabilityContainer } from "../../kit/Capability.jsx";
import { Loading } from "../../kit/common.jsx";

export default function Logs() {
  const [workspaces, setWorkspaces] = useState(null);
  useEffect(() => { listWorkspaces().then(setWorkspaces).catch(() => setWorkspaces([])); }, []);

  return (
    <MonitorShell active="logs">
      <CapabilityContainer id="azure.monitor.log_analytics_workspaces" title="Welcome to Log Analytics">
        {workspaces === null ? <Loading /> : (
          <p>
            Your subscription has {workspaces.length} Log Analytics workspace{workspaces.length === 1 ? "" : "s"}.{" "}
            <a href="#/monitor/loganalyticsworkspaces">Manage workspaces</a>
          </p>
        )}
        <Button appearance="primary" as="a" href="#/monitor/loganalyticsworkspaces">Create a Log Analytics workspace</Button>
      </CapabilityContainer>
      <CapabilityContainer id="azure.monitor.log_query" title="Run a query" />
    </MonitorShell>
  );
}
