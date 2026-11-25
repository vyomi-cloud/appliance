import boto3

import vymodels

cw = boto3.client("cloudwatch")
BUDGETS = {"model": 0.005, "search": 0.001, "memory": 0.0001}        # notional USD per run, per layer
meters = {name: vymodels.Budget(limit) for name, limit in BUDGETS.items()}


def spend(layer, kind="chat"):
    """One metered unit of work for a layer: refuse if the layer is already over budget."""
    meters[layer].check()
    if kind == "chat":
        vymodels.chat("Reply with the single word OK.")
        meters[layer].charge("chat", 120, 40)       # tokens this call used (the simulator reports real usage; fixed here so the lab is deterministic)
    else:
        vymodels.embed("boiler pressure limit")
        meters[layer].charge("embed", 400)


for layer in BUDGETS:                                                    # normal traffic
    spend(layer, "chat" if layer == "model" else "embed")
for _ in range(60):                                                      # a runaway loop in one layer only
    try:
        spend("memory", "embed")
    except vymodels.BudgetExceeded:
        break
assert meters["memory"].spent >= meters["memory"].limit, "the runaway layer must have hit its ceiling"
try:
    spend("memory", "embed")
    raise AssertionError("an over-budget layer must be refused")
except vymodels.BudgetExceeded as e:
    print("memory layer stopped:", e)
spend("model")                                                           # the other layers still work
print("model layer unaffected: %d calls, notional $%.5f of $%.4f" % (meters["model"].calls, meters["model"].spent, meters["model"].limit))

cw.put_metric_data(Namespace="FacilitiesAgent/Cost", MetricData=[
    {"MetricName": "NotionalCostUSD", "Dimensions": [{"Name": "Layer", "Value": layer}], "Value": m.spent, "Unit": "None"} for layer, m in meters.items()])
listed = cw.list_metrics(Namespace="FacilitiesAgent/Cost")["Metrics"]
layers = {d["Value"] for m in listed for d in m["Dimensions"] if d["Name"] == "Layer"}
assert layers == set(BUDGETS), "one cost series per layer expected, found %s" % sorted(layers)
for layer, limit in BUDGETS.items():
    cw.put_metric_alarm(AlarmName="budget-" + layer, Namespace="FacilitiesAgent/Cost", MetricName="NotionalCostUSD",
                        Dimensions=[{"Name": "Layer", "Value": layer}], Statistic="Maximum", Period=60, EvaluationPeriods=1,
                        Threshold=limit, ComparisonOperator="GreaterThanOrEqualToThreshold", TreatMissingData="notBreaching")
alarms = {a["AlarmName"]: a for a in cw.describe_alarms(AlarmNamePrefix="budget-")["MetricAlarms"]}
assert set(alarms) == {"budget-" + l for l in BUDGETS} and all(a["Threshold"] == BUDGETS[a["AlarmName"][7:]] for a in alarms.values())
print("cost series per layer:", sorted(layers), "| budget alarms:", sorted(alarms))
print("cost control verified")
