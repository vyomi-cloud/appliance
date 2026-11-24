"""Deploy and call Cloud Run functions (gen2) with the google-cloud-functions client: generateUploadUrl, PUT the zip, CreateFunction.
Shared by chapters 7, 6, 4, 5 and 12."""
import io
import os
import zipfile

import requests
from google.api_core import exceptions as gex
from google.cloud import functions_v2 as f2

import gcp

FIRESTORE_HOST = os.environ["FIRESTORE_EMULATOR_HOST"]


def base_env(extra=None):
    """What every function needs: the project, where Firestore is, where the Vertex REST API is, and the collection names."""
    env = {"GOOGLE_CLOUD_PROJECT": gcp.PROJECT, "GOOGLE_CLOUD_REGION": gcp.LOCATION, "FIRESTORE_EMULATOR_HOST": FIRESTORE_HOST,
           "VERTEX_API_ENDPOINT": gcp.ENDPOINT, "ASSETS_COLLECTION": "assets", "WORK_ORDERS_COLLECTION": "work-orders", "LEDGER_COLLECTION": "approval-ledger"}
    env.update(extra or {})
    return env


def zip_of(source_file):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("main.py", open(source_file).read())
        z.writestr("requirements.txt", "google-cloud-firestore\ngoogle-cloud-aiplatform\ngoogle-cloud-storage\n")
    return buf.getvalue()


def deploy(name, source_file, env=None, cloudevent=False):
    """Create or update the function and return its HTTPS address."""
    client = gcp.rest(f2.FunctionServiceClient)
    upload = client.generate_upload_url(request={"parent": gcp.PARENT})
    requests.put(upload.upload_url, data=zip_of(source_file), headers={"content-type": "application/zip"}, timeout=60).raise_for_status()
    fn = f2.Function(
        name=f"{gcp.PARENT}/functions/{name}",
        build_config=f2.BuildConfig(runtime="python312", entry_point="handler", source=f2.Source(storage_source=upload.storage_source),
                                    environment_variables={"GOOGLE_FUNCTION_SIGNATURE_TYPE": "cloudevent"} if cloudevent else {}),
        service_config=f2.ServiceConfig(environment_variables=base_env(env), available_memory="512M", timeout_seconds=120))
    try:
        client.get_function(request={"name": fn.name})
        result = client.update_function(request={"function": fn}).result(timeout=120)
    except gex.NotFound:
        result = client.create_function(request={"parent": gcp.PARENT, "function": fn, "function_id": name}).result(timeout=120)
    return result.service_config.uri or f"{gcp.ENDPOINT}/gcf/{gcp.PROJECT}/{gcp.LOCATION}/{name}"


def uri_of(name):
    fn = gcp.rest(f2.FunctionServiceClient).get_function(request={"name": f"{gcp.PARENT}/functions/{name}"})
    return fn.service_config.uri or f"{gcp.ENDPOINT}/gcf/{gcp.PROJECT}/{gcp.LOCATION}/{name}"


def call(name_or_uri, payload):
    """HTTPS call to a function. On real Google Cloud the credential is an ID token for the function's audience; the simulator accepts any token."""
    uri = name_or_uri if name_or_uri.startswith("http") else uri_of(name_or_uri)
    r = gcp.authed_session().post(uri, json=payload, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"{uri.rsplit('/', 1)[-1]} HTTP {r.status_code}: {r.text[:300]}")
    return r.json()
