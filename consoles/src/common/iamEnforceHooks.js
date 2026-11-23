/* React glue for common/iamEnforce.js: one hook that loads/saves the enforcement document for a cloud, one for the audit list. */
import { useCallback, useMemo, useState } from "react";
import { WIRE_BASE } from "./wire.js";
import { iamApi, iamBase, resolveMode, withMode } from "./iamEnforce.js";
import { useAsync } from "./useAsync.js";

const apis = {};
/** Per-cloud API client; tests/the visual harness may swap the fetcher with window.__vyomiIamFetch. */
export function useIamApi(cloud) {
  return useMemo(() => apis[cloud] ||= iamApi(cloud, { base: iamBase(WIRE_BASE), fetcher: (...a) => (window.__vyomiIamFetch || fetch)(...a) }), [cloud]);
}

export function useEnforcement(cloud) {
  const api = useIamApi(cloud);
  const st = useAsync(() => api.getEnforcement(), [cloud]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const set = useCallback(async (level, key, mode) => {
    setSaving(true); setSaveError(null);
    try { await api.putEnforcement(withMode(st.data, level, key, mode)); await st.refresh(); }
    catch (e) { setSaveError(e); } finally { setSaving(false); }
  }, [api, st.data]);
  return { settings: st.data, loading: st.loading, error: st.error || saveError, saving, set, reload: st.reload, resolve: (svc, res) => resolveMode(st.data, svc, res), api };
}

export function useAudit(cloud, limit = 100) {
  const api = useIamApi(cloud);
  return useAsync(() => api.audit(limit), [cloud, limit]);
}
