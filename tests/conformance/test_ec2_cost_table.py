"""The EC2 dashboard cost widget's price table must stay in sync with core/cost_model.py (single source of truth for list prices).
Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_ec2_cost_table.py"""
import json
from pathlib import Path

from core import cost_model as c

t = json.loads((Path(__file__).resolve().parents[2] / "consoles/src/aws/services/ec2/price-table.json").read_text())
assert t["vmHourly"] == c.AWS_VM_HOURLY, "price-table.json vmHourly drifted from cost_model.AWS_VM_HOURLY — regenerate it"
assert t["defaultVmHourly"] == c._DEFAULT_VM_HOURLY["aws"] and t["hoursPerMonth"] == c.HOURS_PER_MONTH
assert all(v > 0 for v in t["ebsGbMonth"].values()) and t["publicIpv4Hourly"] == 0.005
print("EC2 price table in sync with cost_model: ok")
