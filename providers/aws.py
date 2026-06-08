from __future__ import annotations

from core.provider_registry import get_provider, provider_matrix
from core.pack_catalog import packs_for_provider


def matrix() -> dict:
    packs = packs_for_provider("aws")
    matrix_data = provider_matrix("aws", packs)
    matrix_data["catalog"] = {
        "service": [pack for pack in packs if pack.get("type") == "service"],
        "tooling": [pack for pack in packs if pack.get("type") == "tooling"],
    }
    return matrix_data


def tool_response(tool: str) -> dict:
    tool = tool.lower()
    provider_info = get_provider("aws")
    endpoint = "http://127.0.0.1:9000"
    if tool == "cli":
        return {
            "provider": "aws",
            "tool": "awscli",
            "status": "integrated",
            "endpoint": endpoint,
            "help": [
                "aws s3 ls --endpoint-url http://127.0.0.1:9000",
                "aws ec2 describe-instances --endpoint-url http://127.0.0.1:9000",
                "aws iam list-users --endpoint-url http://127.0.0.1:9000",
                "aws sqs list-queues --endpoint-url http://127.0.0.1:9000",
                "aws dynamodb list-tables --endpoint-url http://127.0.0.1:9000",
                "aws lambda list-functions --endpoint-url http://127.0.0.1:9000",
                "aws apigateway get-rest-apis --endpoint-url http://127.0.0.1:9000",
            ],
            "notes": "This simulator accepts AWS-style request/response shapes locally across S3, IAM, EC2, Lambda, VPC, RDS, SQS, DynamoDB, and API Gateway.",
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/java":
        return {
            "provider": "aws",
            "tool": "aws-sdk-java",
            "status": "partial",
            "endpoint": endpoint,
            "dependency": "software.amazon.awssdk:*",
            "config": {"endpointOverride": endpoint, "region": "us-east-1", "credentials": "test/test"},
            "help": ["Configure the SDK client with endpointOverride=http://127.0.0.1:9000", "Use the same service names and request models as AWS SDK v2."],
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/go":
        return {
            "provider": "aws",
            "tool": "aws-sdk-go",
            "status": "partial",
            "endpoint": endpoint,
            "dependency": "github.com/aws/aws-sdk-go-v2",
            "config": {"baseEndpoint": endpoint, "region": "us-east-1", "credentials": "test/test"},
            "help": ["Use BaseEndpoint to point the client at the simulator.", "Service request/response bodies stay AWS-shaped."],
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/python":
        return {
            "provider": "aws",
            "tool": "boto3",
            "status": "partial",
            "endpoint": endpoint,
            "dependency": "boto3",
            "config": {"endpoint_url": endpoint, "region_name": "us-east-1", "credentials": "test/test"},
            "help": ["Use endpoint_url to point boto3 clients at the simulator.", "All standard boto3 service clients work with the simulator endpoint."],
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/nodejs":
        return {
            "provider": "aws",
            "tool": "aws-sdk-js-v3",
            "status": "partial",
            "endpoint": endpoint,
            "dependency": "@aws-sdk/client-*",
            "config": {"endpoint": endpoint, "region": "us-east-1", "credentials": "test/test", "forcePathStyle": True},
            "help": ["Pass endpoint to each service client constructor.", "Use forcePathStyle for S3."],
            "provider_surface": provider_info.get("surface", {}),
        }
    raise KeyError(tool)
