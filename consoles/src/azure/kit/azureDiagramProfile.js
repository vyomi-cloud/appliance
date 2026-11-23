/* Azure skin of the shared layered diagram (common/infra-diagram): ARM resource types -> layer / inbound-core-outbound. Types are matched lower-cased. */
export const AZURE_PROFILE = {
  cloud: "azure",
  networkIcon: "vnets",
  usersLabel: "Users, browsers & external apps",
  hide: /\/(events|suppressions)$/,
  primary: [
    ["edge", /^microsoft\.(network\/(applicationgateways|frontdoors|loadbalancers|azurefirewalls|networksecuritygroups|publicipaddresses|publicipprefixes|virtualnetworks|routetables|natgateways|privateendpoints|bastionhosts|dnszones|privatednszones|trafficmanagerprofiles|applicationsecuritygroups|networkinterfaces|virtualnetworkgateways|ddosprotectionplans)|cdn|apimanagement)/],
    ["data", /^microsoft\.(sql|documentdb|storage|cache|dbfor[a-z]+|datafactory|synapse|search|keyvault)/],
    ["compute", /^microsoft\.(web|compute|containerservice|containerinstance|app\/|logic|servicebus|eventgrid|eventhub|cognitiveservices|machinelearningservices|streamanalytics|containerregistry)/],
  ],
  fallback: [["data", /^microsoft\.(keyvault|appconfiguration)/]],
  inbound: /^microsoft\.network\/(networksecuritygroups|publicipaddresses|publicipprefixes|routetables|privateendpoints|applicationsecuritygroups|networkinterfaces|ddosprotectionplans|virtualnetworks\/subnets)|\/(firewallrules|authorizationrules|privateendpointconnections)$/,
  outbound: /^microsoft\.(managedidentity|authorization|insights|operationalinsights|operationsmanagement)|\/(diagnosticsettings|roleassignments)$/,
  entry: /^microsoft\.(network\/(applicationgateways|frontdoors|loadbalancers|publicipaddresses|dnszones)|cdn|apimanagement)/,
  iconOf: (n) => {
    const t = n.type;
    if (/network\/virtualnetworks/.test(t)) return "vnets";
    if (/network\/networksecuritygroups/.test(t)) return "nsgs";
    if (/^microsoft\.storage/.test(t)) return "storage";
    if (/^microsoft\.sql/.test(t)) return "sql";
    if (/^microsoft\.documentdb/.test(t)) return "cosmos";
    if (/^microsoft\.keyvault/.test(t)) return "keyvaults";
    if (/^microsoft\.servicebus/.test(t)) return "servicebus";
    if (/^microsoft\.eventgrid/.test(t)) return "eventgrid";
    if (/^microsoft\.web\/sites/.test(t)) return /functionapp/i.test(n.kind || "") ? "functionapp" : "appservices";
    if (/^microsoft\.web/.test(t)) return "appservices";
    if (/^microsoft\.compute/.test(t)) return "vms";
    if (/^microsoft\.containerservice/.test(t)) return "aks";
    if (/^microsoft\.containerregistry/.test(t)) return "acr";
    if (/^microsoft\.apimanagement/.test(t)) return "apim";
    if (/^microsoft\.cognitiveservices/.test(t)) return "cognitiveservices";
    if (/^microsoft\.(insights|operationalinsights)/.test(t)) return /operationalinsights/.test(t) ? "loganalytics" : "monitor";
    if (/^microsoft\.network\/dnszones/.test(t)) return "dns";
    if (/^microsoft\.appconfiguration/.test(t)) return "appconfiguration";
    if (/^microsoft\.app\//.test(t)) return "containerapps";
    if (/^microsoft\.managedidentity/.test(t)) return "entra";
    return "resourcegroups";
  },
  typeLabel: (n) => (n.type || "").replace(/^microsoft\./, ""),
};
