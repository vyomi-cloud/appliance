import time

import yaml
from google.cloud import apigateway_v1 as ag

import gcp

ISSUER = "https://securetoken.google.com/facilities-users"
BACKEND = f"https://{gcp.LOCATION}-{gcp.PROJECT}.cloudfunctions.net/facilities-kb-search"
OPENAPI = yaml.safe_dump({
    "swagger": "2.0", "info": {"title": "facilities-api", "version": "1.0.0"}, "schemes": ["https"], "produces": ["application/json"],
    "paths": {"/search": {"post": {"operationId": "search", "x-google-backend": {"address": BACKEND, "path_translation": "CONSTANT_ADDRESS"},
                                   "security": [{"firebase": []}, {"google_id_token": []}], "responses": {"200": {"description": "ok"}}}}},
    "securityDefinitions": {
        "google_id_token": {"authorizationUrl": "", "flow": "implicit", "type": "oauth2", "x-google-issuer": "https://accounts.google.com",
                             "x-google-jwks_uri": "https://www.googleapis.com/oauth2/v3/certs", "x-google-audiences": "https://facilities.example.com"},
        "firebase": {"authorizationUrl": "", "flow": "implicit", "type": "oauth2", "x-google-issuer": ISSUER,
                     "x-google-jwks_uri": "https://www.googleapis.com/service_accounts/v1/metadata/x509/securetoken@system.gserviceaccount.com",
                     "x-google-audiences": "facilities-users"}}})

client = gcp.rest(ag.ApiGatewayServiceClient)
GLOBAL = f"projects/{gcp.PROJECT}/locations/global"


def wait_active(getter, what):
    for _ in range(40):
        resource = getter()
        if resource.state.name == "ACTIVE":
            return resource
        assert resource.state.name != "FAILED", what + " FAILED"
        time.sleep(0.5)
    raise AssertionError(what + " did not become ACTIVE")


client.create_api(request={"parent": GLOBAL, "api_id": "facilities-api", "api": ag.Api(display_name="facilities-api")})
wait_active(lambda: client.get_api(request={"name": f"{GLOBAL}/apis/facilities-api"}), "api")
client.create_api_config(request={"parent": f"{GLOBAL}/apis/facilities-api", "api_config_id": "cfg1", "api_config": ag.ApiConfig(
    display_name="cfg1", openapi_documents=[ag.ApiConfig.OpenApiDocument(document=ag.ApiConfig.File(path="openapi.yaml", contents=OPENAPI.encode()))])})
config = wait_active(lambda: client.get_api_config(request={"name": f"{GLOBAL}/apis/facilities-api/configs/cfg1"}), "api config")
client.create_gateway(request={"parent": gcp.PARENT, "gateway_id": "facilities-api-gw", "gateway": ag.Gateway(api_config=config.name, display_name="facilities-api-gw")})
gateway = wait_active(lambda: client.get_gateway(request={"name": f"{gcp.PARENT}/gateways/facilities-api-gw"}), "gateway")
print("gateway", gateway.name.rsplit("/", 1)[-1], "ACTIVE at", gateway.default_hostname)
