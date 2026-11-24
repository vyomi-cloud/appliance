import boto3

DOCS = {
    "boiler-sop.md": """# SOP-101 Boiler plant operation (Site HQ-1, Building A)

If boiler pressure exceeds 30 psi, close the main steam valve, notify the duty engineer and raise a P1 work order.
The pressure relief valve (PRV) must be inspected every 90 days. Record the inspection in the maintenance log.
Never bypass the low-water cutoff. Boiler B-12 serves floors 1 to 6.
""",
    "elevator-sop.md": """# SOP-215 Elevator faults

An elevator reporting door-zone faults must be taken out of service and tagged. Raise a P2 work order with the vendor.
Passengers trapped in a car: call the vendor emergency line and keep security on the floor until released.
""",
    "fire-safety-sop.md": """# SOP-310 Fire safety and evacuation

Fire alarm panels are tested monthly. When an alarm sounds, security must verify within 2 minutes and start evacuation of the affected zone.
Fire extinguishers are inspected annually. Sprinkler valve closures require a P1 work order and a fire watch until restored.
""",
    "hvac-maintenance-manual.md": """# MM-220 HVAC air handling unit maintenance manual (AHU-7)

Replace the AHU-7 filter every 60 days or when differential pressure exceeds 250 Pa.
Inspect belts and bearings quarterly. A supply air temperature drift greater than 3 degrees C indicates a failing chilled water valve.
Raise a P2 work order for chilled water valve replacement. Spare valves are stocked in store room S-2.
""",
}

s3 = boto3.client("s3")
try:
    s3.create_bucket(Bucket="facilities-docs")
except Exception:
    pass          # already created by chapter 3
for name, text in DOCS.items():
    s3.put_object(Bucket="facilities-docs", Key="docs/" + name, Body=text.encode(), ContentType="text/markdown")
print("uploaded %d documents to s3://facilities-docs/docs/" % len(DOCS))
