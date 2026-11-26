"""One place that creates the AWS clients, so every module shares them. On Nano they talk to the simulator inside your browser."""
import boto3

s3 = boto3.client("s3")
ddb = boto3.client("dynamodb")
sqs = boto3.client("sqs")
rt = boto3.client("bedrock-runtime")
