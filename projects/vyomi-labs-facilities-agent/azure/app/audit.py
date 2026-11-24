import time
from azure.mgmt.monitor import MonitorManagementClient
from azlab import arm, RG

since = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() - 86400))
log = arm(MonitorManagementClient).activity_logs
events = list(log.list(filter=f"eventTimestamp ge '{since}'"))
ops = {e.operation_name.value for e in events if e.operation_name}
print("control-plane events:", len(events) > 0, "| vault create recorded:", "Microsoft.KeyVault/vaults/write" in ops, "| function app create recorded:", "Microsoft.Web/sites/write" in ops)
print("events for resource group", RG + ":", len(list(log.list(filter=f"eventTimestamp ge '{since}' and resourceGroupName eq '{RG}'"))) > 0)
