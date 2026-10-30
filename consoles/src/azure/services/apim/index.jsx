import ApiManagementServices from "./ApiManagementServices.jsx";
import CreateApiManagementService from "./CreateApiManagementService.jsx";
import CreateHttpApi from "./CreateHttpApi.jsx";
import ApimBlade, { LABEL } from "./ApimBlade.jsx";

const service = (p) => ({ text: p.name, href: `#/apim/${encodeURIComponent(p.rg)}/${encodeURIComponent(p.name)}` });

export default {
  routes: [
    { pattern: "/apim", component: ApiManagementServices },
    { pattern: "/apim/create", component: CreateApiManagementService, crumbs: () => [{ text: "Create API Management service", href: "#/apim/create" }] },
    { pattern: "/apim/:rg/:name", component: ApimBlade, crumbs: (p) => [service(p)] },
    { pattern: "/apim/:rg/:name/apis/create", component: CreateHttpApi, crumbs: (p) => [service(p), { text: "APIs", href: `#/apim/${p.rg}/${p.name}/apis` }, { text: "Create an HTTP API", href: `#/apim/${p.rg}/${p.name}/apis/create` }] },
    { pattern: "/apim/:rg/:name/:panel", component: ApimBlade, crumbs: (p) => [service(p), { text: LABEL[p.panel] || p.panel, href: `#/apim/${p.rg}/${p.name}/${p.panel}` }] },
  ],
};
