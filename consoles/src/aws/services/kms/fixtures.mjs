/* UI-conformance fixtures for KMS (native TrentService.* JSON). See s3/fixtures.mjs. */
const T = (op) => ({ svc: "kms", target: `TrentService.${op}` });
const b64 = (s) => Buffer.from(s).toString("base64");

export default {
  "live-customer-key": async (wire, uniq) => {
    const r = await wire("POST", "/", { ...T("CreateKey"), body: { Description: `v4 live ${uniq}` } });
    return r.KeyMetadata.KeyId;
  },
  // Liveness for the AWS-managed-key goal: Encrypt against an unseen alias/aws/<service>
  // alias auto-provisions that key, exactly as AWS does on a service's first use.
  "live-aws-managed-key": async (wire, uniq) => {
    await wire("POST", "/", { ...T("Encrypt"), body: { KeyId: `alias/aws/${uniq}`, Plaintext: b64("x") } });
    const d = await wire("POST", "/", { ...T("DescribeKey"), body: { KeyId: `alias/aws/${uniq}` } });
    return d.KeyMetadata.KeyId;
  },
  "live-external-key-store": async (wire, uniq) => {
    await wire("POST", "/", { ...T("CreateCustomKeyStore"), body: {
      CustomKeyStoreName: uniq, CustomKeyStoreType: "EXTERNAL_KEY_STORE",
      XksProxyUriEndpoint: "https://xks.example.com", XksProxyConnectivity: "PUBLIC_ENDPOINT",
    } });
    return uniq;
  },
};
