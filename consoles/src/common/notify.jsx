/* Page-level notifications (the green "Successfully created …" / red error banners). */
import { createContext, useCallback, useContext, useState } from "react";

const Ctx = createContext(null);
let seq = 0;

export function NotifyProvider({ children }) {
  const [items, setItems] = useState([]);
  const [history, setHistory] = useState([]);   // the top bar's notifications panel
  const dismiss = useCallback((id) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const push = useCallback((type, content, header) => {
    const id = `n${++seq}`;
    setItems((xs) => [{ id, type, content, header, dismissible: true, onDismiss: () => dismiss(id) }, ...xs].slice(0, 5));
    setHistory((hs) => [{ id, type, content, header, at: new Date() }, ...hs].slice(0, 30));
    if (type === "success") setTimeout(() => dismiss(id), 8000);
  }, [dismiss]);
  return <Ctx.Provider value={{ items, history, push, dismiss }}>{children}</Ctx.Provider>;
}

export function useNotify() {
  const c = useContext(Ctx);
  return {
    items: c.items,
    history: c.history,
    success: (content, header) => c.push("success", content, header),
    error: (err, header) => c.push("error", err?.message || String(err), header || err?.code),
    info: (content, header) => c.push("info", content, header),
  };
}
