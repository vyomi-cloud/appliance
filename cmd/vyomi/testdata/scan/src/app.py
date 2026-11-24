"""Python: boto3, google-cloud and azure SDK usage."""
import boto3
from google.cloud import storage
from google.cloud import pubsub_v1
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")
secrets = boto3.client("secretsmanager")

buckets = storage.Client()
publisher = pubsub_v1.PublisherClient()
blobs = BlobServiceClient.from_connection_string("UseDevelopmentStorage=true")
cred = DefaultAzureCredential()
llm = AzureOpenAI(api_version="2024-02-01")
