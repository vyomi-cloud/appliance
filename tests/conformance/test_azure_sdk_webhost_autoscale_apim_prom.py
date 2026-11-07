"""Real Azure SDK calls (azure-mgmt-web / -monitor / -apimanagement / -alertsmanagement) against the wire router for the features
made real in this batch: autoscale (instance count changes), site config panels (applied by the app host), APIM fronting a Function
App, self-hosted gateway association, Prometheus rule groups. Skipped cleanly if the SDKs are not installed."""
import json
import pytest

pytest.importorskip("azure.mgmt.web")
pytest.importorskip("azure.mgmt.monitor")
pytest.importorskip("azure.mgmt.apimanagement")
from tests.conformance._azure_sdk_inproc import make, SUB  # noqa: E402
from core.aws_wire_router import AwsWireRouter  # noqa: E402
from azure.mgmt.resource.resources import ResourceManagementClient  # noqa: E402
from azure.mgmt.web import WebSiteManagementClient  # noqa: E402
from azure.mgmt.web.models import SiteConfigResource, ApiManagementConfig, SitePatchResource  # noqa: E402
from azure.mgmt.monitor import MonitorManagementClient  # noqa: E402
from azure.mgmt.apimanagement import ApiManagementClient  # noqa: E402
from azure.core.rest import HttpRequest  # noqa: E402


@pytest.fixture(scope="module")
def env():
    r = AwsWireRouter()
    make(ResourceManagementClient, r).resource_groups.create_or_update("rg1", {"location": "eastus"})
    return r


def _arm(r, tail, body):
    out = r.az_arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Web/{tail}", {"api-version": "2022-09-01"}, body)
    assert out["status"] in (200, 201), out


def _site(r, name):
    return next(x for x in r.az_arm.state.values() if isinstance(x, dict) and x.get("name") == name and str(x.get("type", "")).lower() == "microsoft.web/sites")


def _web(r, path, **h):
    return r.handle("GET", "/azure-data/site/" + path, {}, dict({"host": "x"}, **h), b"")


def test_site_config_panels_applied_by_host_via_sdk(env):
    web = make(WebSiteManagementClient, env)
    _arm(env, "serverfarms/plan1", {"location": "eastus", "sku": {"name": "S1"}})
    plan = web.app_service_plans.get("rg1", "plan1")
    _arm(env, "sites/sdkweb", {"location": "eastus", "kind": "app", "properties": {"serverFarmId": plan.id}})
    env.az_arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Web/sites/sdkweb/kudu/vfs/site/wwwroot/home.html",
                      {"api-version": "2022-09-01"}, {"content": "<i>home</i>"})
    assert _web(env, "sdkweb/")["status"] == 403                    # no default document matches yet
    web.web_apps.update_configuration("rg1", "sdkweb", SiteConfigResource(default_documents=["home.html"], min_tls_version="1.2"))
    r = _web(env, "sdkweb/")
    assert r["status"] == 200 and r["body"] == b"<i>home</i>"        # default documents setting applied
    web.web_apps.update("rg1", "sdkweb", SitePatchResource(https_only=True))
    assert _web(env, "sdkweb/", **{"x-forwarded-proto": "http"})["status"] == 301
    assert _web(env, "sdkweb/", **{"x-vyomi-tls-version": "1.0"})["status"] == 421


def test_autoscale_changes_plan_instances_via_sdk(env):
    web, mon = make(WebSiteManagementClient, env), make(MonitorManagementClient, env)
    plan = web.app_service_plans.get("rg1", "plan1")
    rule = {"metric_trigger": {"metric_name": "Requests", "metric_resource_uri": plan.id, "time_grain": "PT1M", "statistic": "Average",
                               "time_window": "PT5M", "time_aggregation": "Average", "operator": "GreaterThan", "threshold": 10},
            "scale_action": {"direction": "Increase", "type": "ChangeCount", "value": "1", "cooldown": "PT5M"}}
    mon.autoscale_settings.create_or_update("rg1", "as-sdk", {"location": "eastus", "enabled": True, "target_resource_uri": plan.id, "profiles": [
        {"name": "default", "capacity": {"minimum": "1", "maximum": "3", "default": "1"}, "rules": [rule]}]})
    s = mon.autoscale_settings.get("rg1", "as-sdk")
    assert s.enabled and s.profiles[0].rules[0].scale_action.value == "1"
    import time
    site = _site(env, "sdkweb")
    for i in range(300):
        env.handle("GET", "/azure-data/site/sdkweb/home.html", {}, {"host": "x"}, b"")
    assert web.app_service_plans.get("rg1", "plan1").sku.capacity >= 2     # real traffic -> instance count really changed


def test_apim_fronts_function_and_gateway_association_via_sdk(env):
    web, apim = make(WebSiteManagementClient, env), make(ApiManagementClient, env)
    plan = web.app_service_plans.get("rg1", "plan1")
    _arm(env, "sites/sdkfn", {"location": "eastus", "kind": "functionapp", "properties": {"serverFarmId": plan.id, "reserved": True}})
    env.az_arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Web/sites/sdkfn/functions/ping", {"api-version": "2022-09-01"},
                      {"properties": {"files": {"__init__.py": "def main(req):\n    return {'pong': True}\n"}}})
    env.az_arm.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.ApiManagement/service/sdkapim", {"api-version": "2022-08-01"},
                      {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.c", "publisherName": "x"}})
    svc = apim.api_management_service.get("rg1", "sdkapim")
    web.web_apps.update_configuration("rg1", "sdkfn", SiteConfigResource(api_management_config=ApiManagementConfig(id=svc.id)))
    api = apim.api.get("rg1", "sdkapim", "sdkfn")
    assert api.service_url.startswith("vyomi-site://sdkfn")
    sub = apim.subscription.list_secrets("rg1", "sdkapim", "master")
    h = {"host": "x", "ocp-apim-subscription-key": sub.primary_key}
    r = env.handle("GET", "/azure-data/apim/sdkapim/sdkfn/ping", {}, h, b"")
    assert r["status"] == 200 and json.loads(r["body"]) == {"pong": True}
    apim.gateway.create_or_update("rg1", "sdkapim", "onprem", {"location_data": {"name": "dc"}})
    h2 = dict(h, **{"x-vyomi-apim-gateway": "onprem"})
    assert env.handle("GET", "/azure-data/apim/sdkapim/sdkfn/ping", {}, h2, b"")["status"] == 404
    apim.gateway_api.create_or_update("rg1", "sdkapim", "onprem", "sdkfn")
    assert env.handle("GET", "/azure-data/apim/sdkapim/sdkfn/ping", {}, h2, b"")["status"] == 200


def test_prometheus_rule_group_evaluated_via_sdk(env):
    import time
    mon = make(MonitorManagementClient, env)     # no azure-mgmt package ships prometheusRuleGroups yet: use the SDK's own ARM pipeline
    ws = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Monitor/accounts/m1"
    rq = HttpRequest("PUT", f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.AlertsManagement/prometheusRuleGroups/pg-sdk",
                     params={"api-version": "2023-03-01"}, json={"location": "eastus", "properties": {"scopes": [ws], "interval": "PT1M", "rules": [
                         {"record": "job:up:sum", "expression": "sum by (job) (up)"}]}})
    assert mon._client.send_request(rq).status_code == 201
    from core import azure_alerts_core as al
    st = env.az_arm.state
    al.prom_ingest(st, SUB, ws, [{"metric": "up", "labels": {"job": "a", "i": "1"}, "value": 1}, {"metric": "up", "labels": {"job": "a", "i": "2"}, "value": 1}])
    al.evaluate(st, SUB, None, force=True)
    assert al.prom_query(st, SUB, ws, 'job:up:sum{job="a"}')["result"][0]["value"][1] == "2.0"
