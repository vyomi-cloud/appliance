import functions

for name, source in (("facilities-asset-status", "asset_status_fn.py"), ("facilities-approval-decision", "approval_decision_fn.py"),
                     ("facilities-create-work-order", "create_work_order_fn.py")):
    print("deployed", name, functions.deploy(name, source))
