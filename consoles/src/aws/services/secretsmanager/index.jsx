import Landing from "./Landing.jsx";
import Secrets from "./Secrets.jsx";
import SecretDetail from "./SecretDetail.jsx";
import StoreSecret from "./StoreSecret.jsx";
import EditSecretValuePage from "./EditSecretValuePage.jsx";
import DeleteSecretPage from "./DeleteSecretPage.jsx";

export default {
  nav: [
    { type: "link", text: "Secrets", href: "#/secretsmanager/listsecrets" },
  ],
  routes: [
    { pattern: "/secretsmanager", component: Landing, crumbs: () => [{ text: "AWS Secrets Manager", href: "#/secretsmanager" }] },
    { pattern: "/secretsmanager/home", component: Landing, crumbs: () => [{ text: "AWS Secrets Manager", href: "#/secretsmanager/home" }] },
    { pattern: "/secretsmanager/listsecrets", component: Secrets, crumbs: () => [{ text: "Secrets", href: "#/secretsmanager/listsecrets" }] },
    { pattern: "/secretsmanager/newsecret", component: StoreSecret, crumbs: () => [{ text: "Secrets", href: "#/secretsmanager/listsecrets" }, { text: "Store a new secret", href: "#/secretsmanager/newsecret" }] },
    { pattern: "/secretsmanager/secret/:name", component: SecretDetail, crumbs: (p) => [{ text: "Secrets", href: "#/secretsmanager/listsecrets" }, { text: p.name, href: `#/secretsmanager/secret/${p.name}` }] },
    { pattern: "/secretsmanager/secret/:name/edit-value", component: EditSecretValuePage, crumbs: (p) => [{ text: "Secrets", href: "#/secretsmanager/listsecrets" }, { text: p.name, href: `#/secretsmanager/secret/${p.name}` }, { text: "Edit secret value", href: `#/secretsmanager/secret/${p.name}/edit-value` }] },
    { pattern: "/secretsmanager/secret/:name/delete", component: DeleteSecretPage, crumbs: (p) => [{ text: "Secrets", href: "#/secretsmanager/listsecrets" }, { text: p.name, href: `#/secretsmanager/secret/${p.name}` }, { text: "Schedule secret deletion", href: `#/secretsmanager/secret/${p.name}/delete` }] },
  ],
};
