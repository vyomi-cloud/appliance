import { useCallback, useEffect, useRef, useState } from "react";

/** Run an async loader, expose {data, loading, error, reload}. Stale results are dropped. */
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ data: undefined, loading: true, error: null });
  const gen = useRef(0);
  const run = useCallback(async () => {
    const g = ++gen.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fn();
      if (g === gen.current) setState({ data, loading: false, error: null });
    } catch (error) {
      if (g === gen.current) setState({ data: undefined, loading: false, error });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { run(); }, [run]);
  return { ...state, reload: run };
}
