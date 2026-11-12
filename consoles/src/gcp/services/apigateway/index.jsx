import ApiIcon from "@mui/icons-material/esm/ApiOutlined.js";
import RouterIcon from "@mui/icons-material/esm/RouterOutlined.js";
import KeyIcon from "@mui/icons-material/esm/VpnKeyOutlined.js";
import ApiKeys from "./ApiKeys.jsx";
import Gateways from "./Gateways.jsx";
import CreateGateway from "./CreateGateway.jsx";
import GatewayDetail from "./GatewayDetail.jsx";
import Apis from "./Apis.jsx";
import CreateApi from "./CreateApi.jsx";
import ApiDetail from "./ApiDetail.jsx";

export default {
  nav: [
    { text: "Gateways", href: "#/apigateway", icon: RouterIcon, match: ["#/apigateway/gateways"] },
    { text: "APIs", href: "#/apigateway/apis", icon: ApiIcon, match: ["#/apigateway/apis/"] },
    { text: "API keys", href: "#/apigateway/keys", icon: KeyIcon },
  ],
  routes: [
    { pattern: "/apigateway", component: Gateways },
    { pattern: "/apigateway/gateways", component: Gateways },
    { pattern: "/apigateway/gateways/new", component: CreateGateway },
    { pattern: "/apigateway/gateways/:region/:name", component: GatewayDetail },
    { pattern: "/apigateway/apis", component: Apis },
    { pattern: "/apigateway/keys", component: ApiKeys },
    { pattern: "/apigateway/apis/new", component: CreateApi },
    { pattern: "/apigateway/apis/:api", component: ApiDetail },
  ],
};
