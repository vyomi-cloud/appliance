from google.api_core import exceptions as gex
from google.cloud import eventarc_v1 as ea

import functions
import gcp
import rag

corpus = rag.corpus_name()
uri = functions.deploy("facilities-ingest-docs", "ingest_docs_fn.py", env={"RAG_CORPUS": corpus}, cloudevent=True)
print("deployed facilities-ingest-docs")

client = gcp.rest(ea.EventarcClient)
trigger = ea.Trigger(
    name=f"{gcp.PARENT}/triggers/facilities-docs-finalized",
    event_filters=[ea.EventFilter(attribute="type", value="google.cloud.storage.object.v1.finalized"), ea.EventFilter(attribute="bucket", value="facilities-docs")],
    destination=ea.Destination(cloud_run=ea.CloudRun(service="facilities-ingest-docs", region=gcp.LOCATION)))
try:
    client.create_trigger(request={"parent": gcp.PARENT, "trigger": trigger, "trigger_id": "facilities-docs-finalized"}).result(timeout=60)
except gex.AlreadyExists:
    pass
print("trigger facilities-docs-finalized created")
