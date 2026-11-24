from azure.mgmt.monitor import MonitorManagementClient
from azlab import arm, rid

m = arm(MonitorManagementClient).metrics.list(rid("Microsoft.Storage", "storageAccounts", "facilitiesdocs"), metricnames="Transactions", aggregation="Total",
                                              timespan="2026-11-17T00:00:00Z/2026-11-30T00:00:00Z", interval="PT1H")
print("platform metrics returned:", [x.name.value for x in m.value])
