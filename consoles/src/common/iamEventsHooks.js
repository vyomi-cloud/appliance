/* React glue for common/iamEvents.js. */
import { useMemo } from "react";
import { WIRE_BASE } from "./wire.js";
import { iamBase } from "./iamEnforce.js";
import { eventsApi } from "./iamEvents.js";
import { useAsync } from "./useAsync.js";

export function useIamEvents(cloud, filters, limit = 100) {
  const api = useMemo(() => eventsApi(cloud, { base: iamBase(WIRE_BASE), fetcher: (...a) => (window.__vyomiIamFetch || fetch)(...a) }), [cloud]);
  const key = JSON.stringify(filters || {});
  const st = useAsync(() => api.list(filters, limit), [cloud, key, limit]);
  return { ...st, api };
}
