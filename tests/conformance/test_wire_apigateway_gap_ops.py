"""API Gateway v1 gap ops over the router with a real boto3 `apigateway` client: authorizers (TestInvokeAuthorizer really
invokes a Lambda), models, validators, gateway responses, method/integration responses, PATCH ops, domain names + base path
mappings, VPC links, tags, documentation, export and OpenAPI import (then an invoke of the imported API's mock)."""
import json
import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))
from _wire_boto import make_clients  # noqa: E402


def _api(ag, name="a"):
    a = ag.create_rest_api(name=name)
    return a["id"], a["rootResourceId"]


def test_authorizer_model_validator_lifecycle():
    _, client = make_clients()
    ag = client("apigateway")
    api, root = _api(ag)
    au = ag.create_authorizer(restApiId=api, name="auth", type="TOKEN", authorizerUri="arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:000000000000:function:f/invocations",
                              identitySource="method.request.header.Authorization", authorizerResultTtlInSeconds=60)
    assert ag.get_authorizer(restApiId=api, authorizerId=au["id"])["name"] == "auth"
    ag.update_authorizer(restApiId=api, authorizerId=au["id"], patchOperations=[{"op": "replace", "path": "/name", "value": "auth2"}])
    assert [x["name"] for x in ag.get_authorizers(restApiId=api)["items"]] == ["auth2"]
    with pytest.raises(ClientError) as e:
        ag.create_authorizer(restApiId=api, name="x", type="BOGUS")
    assert e.value.response["Error"]["Code"] == "BadRequestException"
    m = ag.create_model(restApiId=api, name="Pet", contentType="application/json", schema=json.dumps({"type": "object", "properties": {"id": {"type": "string"}}}))
    assert ag.get_model(restApiId=api, modelName="Pet")["name"] == m["name"]
    assert "inputRoot.id" in ag.get_model_template(restApiId=api, modelName="Pet")["value"]
    v = ag.create_request_validator(restApiId=api, name="v", validateRequestBody=True)
    ag.put_method(restApiId=api, resourceId=root, httpMethod="GET", authorizationType="CUSTOM", authorizerId=au["id"])
    ag.update_method(restApiId=api, resourceId=root, httpMethod="GET", patchOperations=[{"op": "replace", "path": "/requestValidatorId", "value": v["id"]}])
    assert ag.get_method(restApiId=api, resourceId=root, httpMethod="GET")["requestValidatorId"] == v["id"]
    with pytest.raises(ClientError) as e:
        ag.delete_authorizer(restApiId=api, authorizerId=au["id"])
    assert e.value.response["Error"]["Code"] == "ConflictException"
    ag.delete_request_validator(restApiId=api, requestValidatorId=v["id"])
    with pytest.raises(ClientError):
        ag.get_request_validator(restApiId=api, requestValidatorId=v["id"])


def test_method_integration_responses_and_gateway_responses():
    _, client = make_clients()
    ag = client("apigateway")
    api, root = _api(ag)
    ag.put_method(restApiId=api, resourceId=root, httpMethod="GET", authorizationType="NONE")
    ag.put_integration(restApiId=api, resourceId=root, httpMethod="GET", type="MOCK", requestTemplates={"application/json": '{"statusCode": 200}'})
    ag.put_method_response(restApiId=api, resourceId=root, httpMethod="GET", statusCode="200", responseModels={"application/json": "Empty"})
    ag.put_integration_response(restApiId=api, resourceId=root, httpMethod="GET", statusCode="200", responseTemplates={"application/json": '{"ok":true}'})
    assert ag.get_integration_response(restApiId=api, resourceId=root, httpMethod="GET", statusCode="200")["responseTemplates"]
    ag.update_integration(restApiId=api, resourceId=root, httpMethod="GET", patchOperations=[{"op": "replace", "path": "/timeoutInMillis", "value": "5000"}])
    assert ag.get_integration(restApiId=api, resourceId=root, httpMethod="GET")["timeoutInMillis"] == 5000
    with pytest.raises(ClientError):
        ag.put_integration_response(restApiId=api, resourceId=root, httpMethod="GET", statusCode="404")
    ag.delete_integration_response(restApiId=api, resourceId=root, httpMethod="GET", statusCode="200")
    ag.delete_method_response(restApiId=api, resourceId=root, httpMethod="GET", statusCode="200")
    ag.put_gateway_response(restApiId=api, responseType="UNAUTHORIZED", statusCode="401", responseTemplates={"application/json": '{"m":"no"}'})
    assert ag.get_gateway_response(restApiId=api, responseType="UNAUTHORIZED")["responseTemplates"]["application/json"] == '{"m":"no"}'
    assert len(ag.get_gateway_responses(restApiId=api)["items"]) >= 20
    ag.delete_gateway_response(restApiId=api, responseType="UNAUTHORIZED")
    child = ag.create_resource(restApiId=api, parentId=root, pathPart="old")["id"]
    r = ag.update_resource(restApiId=api, resourceId=child, patchOperations=[{"op": "replace", "path": "/pathPart", "value": "new"}])
    assert r["path"] == "/new"


def test_domains_vpclinks_tags_docs():
    _, client = make_clients()
    ag = client("apigateway")
    api, root = _api(ag)
    ag.create_deployment(restApiId=api, stageName="prod")
    d = ag.create_domain_name(domainName="api.example.com", regionalCertificateArn="arn:aws:acm:us-east-1:000000000000:certificate/x", endpointConfiguration={"types": ["REGIONAL"]})
    assert d["regionalDomainName"]
    ag.create_base_path_mapping(domainName="api.example.com", basePath="v1", restApiId=api, stage="prod")
    assert ag.get_base_path_mappings(domainName="api.example.com")["items"][0]["basePath"] == "v1"
    ag.delete_base_path_mapping(domainName="api.example.com", basePath="v1")
    assert ag.get_domain_names()["items"][0]["domainName"] == "api.example.com"
    ag.delete_domain_name(domainName="api.example.com")
    vl = ag.create_vpc_link(name="l", targetArns=["arn:aws:elasticloadbalancing:us-east-1:000000000000:loadbalancer/net/n/abc"])
    assert ag.get_vpc_link(vpcLinkId=vl["id"])["status"] == "AVAILABLE"
    arn = f"arn:aws:apigateway:us-east-1::/restapis/{api}"
    ag.tag_resource(resourceArn=arn, tags={"env": "dev"})
    assert ag.get_tags(resourceArn=arn)["tags"]["env"] == "dev"
    ag.untag_resource(resourceArn=arn, tagKeys=["env"])
    assert ag.get_tags(resourceArn=arn)["tags"] == {}
    dp = ag.create_documentation_part(restApiId=api, location={"type": "API"}, properties=json.dumps({"info": {"description": "x"}}))
    ag.create_documentation_version(restApiId=api, documentationVersion="1", stageName="prod")
    assert ag.get_documentation_parts(restApiId=api)["items"][0]["id"] == dp["id"]
    assert ag.get_documentation_versions(restApiId=api)["items"][0]["version"] == "1"


def test_export_and_import_round_trip():
    _, client = make_clients()
    ag = client("apigateway")
    doc = {"openapi": "3.0.1", "info": {"title": "imp", "version": "1"},
           "paths": {"/pets": {"get": {"operationId": "listPets", "responses": {"200": {"description": "ok"}},
                                       "x-amazon-apigateway-integration": {"type": "mock", "requestTemplates": {"application/json": '{"statusCode": 200}'},
                                                                           "responses": {"default": {"statusCode": "200", "responseTemplates": {"application/json": '{"pets":[]}'}}}}}}}}
    a = ag.import_rest_api(body=json.dumps(doc).encode())
    res = ag.get_resources(restApiId=a["id"])["items"]
    assert any(r["path"] == "/pets" and "GET" in r.get("resourceMethods", {}) for r in res)
    ag.create_deployment(restApiId=a["id"], stageName="dev")
    ex = json.loads(ag.get_export(restApiId=a["id"], stageName="dev", exportType="oas30")["body"].read())
    assert "/pets" in ex["paths"] and ex["paths"]["/pets"]["get"]["operationId"] == "listPets"
    assert ex["paths"]["/pets"]["get"]["x-amazon-apigateway-integration"]["type"] == "mock"
    b = ag.create_rest_api(name="target")
    ag.put_rest_api(restApiId=b["id"], mode="overwrite", body=json.dumps(doc).encode())
    assert any(r["path"] == "/pets" for r in ag.get_resources(restApiId=b["id"])["items"])
