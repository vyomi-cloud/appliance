/* Per-page fixtures for consoles/tests/ui-conformance.mjs — each creates a resource over
 * the native Resource Manager v3 wire (svc: null → no AWS signature) so "live" pages prove
 * they show real, freshly-created data rather than statics. */
export default {
  "live-project": async (wire, uniq) => {
    await wire("POST", "/v3/projects", { svc: null, body: { projectId: uniq, displayName: uniq } });
    return uniq;
  },
};
