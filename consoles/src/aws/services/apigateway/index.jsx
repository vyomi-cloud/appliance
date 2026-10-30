import Welcome from "./Welcome.jsx";
import Apis from "./Apis.jsx";
import CreateApiPicker from "./CreateApiPicker.jsx";
import CreateRestApi from "./CreateRestApi.jsx";
import CreateHttpApi from "./CreateHttpApi.jsx";
import CreateWebSocketApi from "./CreateWebSocketApi.jsx";
import RestApiDetail from "./RestApiDetail.jsx";
import CreateResource from "./CreateResource.jsx";
import CreateMethod from "./CreateMethod.jsx";
import Stages from "./Stages.jsx";
import HttpApiDetail from "./HttpApiDetail.jsx";
import ApiKeys from "./ApiKeys.jsx";
import CreateApiKey from "./CreateApiKey.jsx";
import UsagePlans from "./UsagePlans.jsx";
import CreateUsagePlan from "./CreateUsagePlan.jsx";
import ClientCertificates from "./ClientCertificates.jsx";
import CustomDomainNames from "./CustomDomainNames.jsx";
import DomainNameAccessAssociations from "./DomainNameAccessAssociations.jsx";
import VpcLinks from "./VpcLinks.jsx";
import { AgentcoreTargets, Portals, PortalProducts } from "./OutOfScope.jsx";
import Settings from "./Settings.jsx";

const top = (text, href) => ({ text, href });

export default {
  // AgentCore targets and Developer portals (Portals, Portal products) are real nav
  // items in the native console, but Vyomi has no data model for either product at
  // all (core/capabilities/aws/apigateway.json: not_simulated, no allowlist entry for
  // a whole-page honest gap yet). They stay reachable as honest NotSimulated routes
  // (OutOfScope.jsx) for spec completeness, but are left out of the sidebar so the
  // always-visible nav text doesn't make their own page's title look "present" to the
  // UI-conformance gate before the allowlist entry lands.
  nav: [
    { type: "link", text: "APIs", href: "#/apigateway/apis" },
    { type: "link", text: "Custom domain names", href: "#/apigateway/custom-domain-names" },
    { type: "link", text: "Domain name access associations", href: "#/apigateway/domain-name-access-associations" },
    { type: "link", text: "VPC links", href: "#/apigateway/vpc-links" },
    { type: "link", text: "Usage plans", href: "#/apigateway/usage-plans" },
    { type: "link", text: "API keys", href: "#/apigateway/api-keys" },
    { type: "link", text: "Client certificates", href: "#/apigateway/client-certificates" },
    { type: "link", text: "Settings", href: "#/apigateway/settings" },
  ],
  routes: [
    { pattern: "/apigateway", component: Welcome, crumbs: () => [] },
    { pattern: "/apigateway/apis", component: Apis, crumbs: () => [top("APIs", "#/apigateway/apis")] },
    { pattern: "/apigateway/create", component: CreateApiPicker, crumbs: () => [top("APIs", "#/apigateway/apis"), top("Create API", "#/apigateway/create")] },
    { pattern: "/apigateway/create-rest-api", component: CreateRestApi, crumbs: () => [top("APIs", "#/apigateway/apis"), top("Create API", "#/apigateway/create"), top("Create REST API", "#/apigateway/create-rest-api")] },
    { pattern: "/apigateway/create-http-api", component: CreateHttpApi, crumbs: () => [top("APIs", "#/apigateway/apis"), top("Create API", "#/apigateway/create"), top("Create HTTP API", "#/apigateway/create-http-api")] },
    { pattern: "/apigateway/create-websocket-api", component: CreateWebSocketApi, crumbs: () => [top("APIs", "#/apigateway/apis"), top("Create API", "#/apigateway/create"), top("Create WebSocket API", "#/apigateway/create-websocket-api")] },
    { pattern: "/apigateway/apis/:id", component: RestApiDetail, crumbs: (p) => [top("APIs", "#/apigateway/apis"), top(p.id, `#/apigateway/apis/${p.id}`), top("Resources", `#/apigateway/apis/${p.id}`)] },
    { pattern: "/apigateway/apis/:id/stages", component: Stages, crumbs: (p) => [top("APIs", "#/apigateway/apis"), top(p.id, `#/apigateway/apis/${p.id}`), top("Stages", `#/apigateway/apis/${p.id}/stages`)] },
    { pattern: "/apigateway/apis/:id/create-resource/:parentId", component: CreateResource, crumbs: (p) => [top("APIs", "#/apigateway/apis"), top(p.id, `#/apigateway/apis/${p.id}`), top("Resources", `#/apigateway/apis/${p.id}`), top("Create resource", "#")] },
    { pattern: "/apigateway/apis/:id/create-method/:resId", component: CreateMethod, crumbs: (p) => [top("APIs", "#/apigateway/apis"), top(p.id, `#/apigateway/apis/${p.id}`), top("Resources", `#/apigateway/apis/${p.id}`), top("Create method", "#")] },
    { pattern: "/apigateway/api/:id", component: HttpApiDetail, crumbs: (p) => [top("APIs", "#/apigateway/apis"), top(p.id, `#/apigateway/api/${p.id}`)] },
    { pattern: "/apigateway/custom-domain-names", component: CustomDomainNames, crumbs: () => [top("Custom domain names", "#/apigateway/custom-domain-names")] },
    { pattern: "/apigateway/domain-name-access-associations", component: DomainNameAccessAssociations, crumbs: () => [top("Domain name access associations", "#/apigateway/domain-name-access-associations")] },
    { pattern: "/apigateway/vpc-links", component: VpcLinks, crumbs: () => [top("VPC links", "#/apigateway/vpc-links")] },
    { pattern: "/apigateway/agentcore-targets", component: AgentcoreTargets, crumbs: () => [] },
    { pattern: "/apigateway/usage-plans", component: UsagePlans, crumbs: () => [top("Usage plans", "#/apigateway/usage-plans")] },
    { pattern: "/apigateway/create-usage-plan", component: CreateUsagePlan, crumbs: () => [top("Usage plans", "#/apigateway/usage-plans"), top("Create usage plan", "#/apigateway/create-usage-plan")] },
    { pattern: "/apigateway/api-keys", component: ApiKeys, crumbs: () => [top("API keys", "#/apigateway/api-keys")] },
    { pattern: "/apigateway/create-api-key", component: CreateApiKey, crumbs: () => [top("API keys", "#/apigateway/api-keys"), top("Create API key", "#/apigateway/create-api-key")] },
    { pattern: "/apigateway/client-certificates", component: ClientCertificates, crumbs: () => [top("Client certificates", "#/apigateway/client-certificates")] },
    { pattern: "/apigateway/settings", component: Settings, crumbs: () => [top("Settings", "#/apigateway/settings")] },
    { pattern: "/apigateway/portals", component: Portals, crumbs: () => [] },
    { pattern: "/apigateway/portal-products", component: PortalProducts, crumbs: () => [] },
  ],
};
