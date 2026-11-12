/* CloudFront signing keys: the account's legacy root key pairs, public keys + key groups, and the signed-URL validator
 * (core/cloudfront_keys_core.py; the /vyomi/ routes are Vyomi extensions beside the real 2020-05-31 API). */
import { awsRest } from "../../../common/wire.js";

const x = (op, body = {}) => awsRest("cloudfront", "POST", `/2020-05-31/vyomi/${op}`, { body });
export const listRootKeyPairs = async () => (await x("root-key-pairs", { op: "list" })).keyPairs || [];
export const createRootKeyPair = (publicKey) => x("root-key-pairs", { op: "create", publicKey });
export const setRootKeyPairStatus = (id, active) => x("root-key-pairs", { op: active ? "activate" : "deactivate", id });
export const deleteRootKeyPair = (id) => x("root-key-pairs", { op: "delete", id });
export const overview = () => x("overview");
export const validateSignedUrl = (body) => x("validate-signed-url", body);

const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const pem = (label, buf) => `-----BEGIN ${label}-----\n${b64(buf).match(/.{1,64}/g).join("\n")}\n-----END ${label}-----\n`;
/** Generate an RSA-2048 key pair in the browser; the private key never leaves it. */
export async function generateKeyPair() {
  const kp = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-1" }, true, ["sign", "verify"]);
  return { publicPem: pem("PUBLIC KEY", await crypto.subtle.exportKey("spki", kp.publicKey)), privatePem: pem("PRIVATE KEY", await crypto.subtle.exportKey("pkcs8", kp.privateKey)) };
}
export function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "application/x-pem-file" }));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
