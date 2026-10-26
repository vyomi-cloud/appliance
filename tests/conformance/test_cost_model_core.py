"""VMs bill at their instance-type rate on every cloud (Azure ARM kind is
`virtualmachines`, and the size lives in properties.hardwareProfile.vmSize)."""
from core import cost_model as cm


def test_azure_arm_vm_is_billed():
    c = cm.estimate_resource_cost("azure", "vm", "virtualmachines", "Standard_B2s")
    assert c["hourly_usd"] == 0.0416 and c["monthly_usd"] > 30


def test_space_savings_uses_node_instance_type():
    nodes = [{"provider": "azure", "service": "vm", "kind": "virtualmachines", "instance_type": "Standard_D2s_v5"}]
    s = cm.estimate_space_savings(nodes)
    assert s["by_provider"]["azure"] == round(0.096 * 730, 2)
