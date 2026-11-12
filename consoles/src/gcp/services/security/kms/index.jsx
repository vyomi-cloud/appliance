import KeyIcon from "@mui/icons-material/esm/VpnKeyOutlined.js";
import InventoryIcon from "@mui/icons-material/esm/FormatListBulletedOutlined.js";
import AutoFixHighIcon from "@mui/icons-material/esm/AutoFixHighOutlined.js";
import KeyManagement from "./KeyManagement.jsx";
import CreateKeyRing from "./CreateKeyRing.jsx";
import CreateKey from "./CreateKey.jsx";
import KeyRingDetail from "./KeyRingDetail.jsx";
import KeyDetail from "./KeyDetail.jsx";

const Rings = () => <KeyManagement tab="rings" />;
const Inventory = () => <KeyManagement tab="inventory" />;
const Autokey = () => <KeyManagement tab="autokey" />;

export default {
  nav: [
    { text: "Key management", href: "#/security/kms/keyrings", icon: KeyIcon, match: ["#/security/kms/keyring", "#/security/kms/key/"] },
    { text: "Key inventory", href: "#/security/kms/key-inventory", icon: InventoryIcon },
    { text: "Autokey", href: "#/security/kms/autokey", icon: AutoFixHighIcon },
  ],
  routes: [
    { pattern: "/security/kms", component: Rings },
    { pattern: "/security/kms/keyrings", component: Rings },
    { pattern: "/security/kms/key-inventory", component: Inventory },
    { pattern: "/security/kms/autokey", component: Autokey },
    { pattern: "/security/kms/keyring/create", component: CreateKeyRing },
    { pattern: "/security/kms/key/create", component: CreateKey },
    { pattern: "/security/kms/keyring/manage/:location/:name", component: KeyRingDetail },
    { pattern: "/security/kms/key/manage/:location/:keyring/:name", component: KeyDetail },
  ],
};
