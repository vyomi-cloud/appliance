"""Client factory shared by every chapter. On real Google Cloud you would not need this file: the libraries find their endpoints and your
Application Default Credentials on their own. Here every client is pointed at the Vyomi simulator through VYOMI_ENDPOINT, and nothing else changes."""
import os
import warnings

from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials
from google.oauth2.credentials import Credentials

warnings.filterwarnings("ignore", category=FutureWarning)      # vertexai.Client prints a rename notice (agentplatform.Client); the calls are the same

ENDPOINT = os.environ["VYOMI_ENDPOINT"]
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "vyomi-project")
LOCATION = os.environ.get("GOOGLE_CLOUD_REGION", "us-central1")
PARENT = f"projects/{PROJECT}/locations/{LOCATION}"


def rest(client_class):
    """A google-cloud client on its REST transport, pointed at the simulator. Pub/Sub and Firestore do not use this: they read the standard
    PUBSUB_EMULATOR_HOST and FIRESTORE_EMULATOR_HOST variables, exactly as they do for Google's own emulators."""
    return client_class(credentials=AnonymousCredentials(), transport="rest", client_options=ClientOptions(api_endpoint=ENDPOINT))


def token_credentials():
    return Credentials(token="vyomi-local")        # the simulator accepts any bearer token


def authed_session():
    """google-auth AuthorizedSession: the supported way to call a Google REST API that has no client library."""
    from google.auth.transport.requests import AuthorizedSession
    return AuthorizedSession(token_credentials())


def genai_client():
    from google import genai
    from google.genai import types
    return genai.Client(vertexai=True, project=PROJECT, location=LOCATION, credentials=token_credentials(),
                        http_options=types.HttpOptions(base_url=ENDPOINT, api_version="v1"))


def vertex_client(api_version="v1beta1"):
    import vertexai
    from google.genai import types
    return vertexai.Client(project=PROJECT, location=LOCATION, credentials=token_credentials(),
                           http_options=types.HttpOptions(base_url=ENDPOINT, api_version=api_version))


def storage_client():
    from google.cloud import storage
    return storage.Client(project=PROJECT, credentials=AnonymousCredentials(), client_options=ClientOptions(api_endpoint=ENDPOINT))


def firestore_client():
    from google.cloud import firestore
    return firestore.Client(project=PROJECT)       # FIRESTORE_EMULATOR_HOST decides where it connects


def logging_client():
    """Cloud Logging over the library's documented HTTP mode (_use_grpc=False), pointed at the simulator."""
    from google.cloud import logging as gcl
    client = gcl.Client(project=PROJECT, credentials=AnonymousCredentials(), _use_grpc=False)
    client._connection.API_BASE_URL = ENDPOINT
    return client


def grpc_options():
    """Cloud Monitoring has no REST transport and Cloud Logging's default is gRPC. The simulator's gRPC front door is advertised in
    VYOMI_GCP_GRPC_ENDPOINT (its certificate in GRPC_DEFAULT_SSL_ROOTS_FILE_PATH); on real Google Cloud you pass no options at all."""
    return {"api_endpoint": os.environ["VYOMI_GCP_GRPC_ENDPOINT"]}


def pubsub_clients():
    from google.cloud import pubsub_v1
    return pubsub_v1.PublisherClient(), pubsub_v1.SubscriberClient()      # PUBSUB_EMULATOR_HOST decides where they connect
