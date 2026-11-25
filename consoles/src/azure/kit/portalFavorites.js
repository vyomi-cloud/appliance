/* Portal favorites for the All services blade and the hamburger flyout. Per-viewer convenience kept in
 * localStorage (like the real portal's per-user favorites); both views stay in sync via a window event. */
import { useEffect, useState } from "react";
import { DEFAULT_FAVORITES } from "../services/allServicesCatalog.js";

const KEY = "vyomi.v4.azure.favorites";
const EVT = "vyomi-azure-favorites";

export function getFavorites() {
  try { const v = JSON.parse(localStorage.getItem(KEY)); if (Array.isArray(v)) return v; } catch {}
  return DEFAULT_FAVORITES.slice();
}

export function setFavorites(list) {
  try { localStorage.setItem(KEY, JSON.stringify(list)); } catch {}
  window.dispatchEvent(new Event(EVT));
}

export function toggleFavorite(name) {
  const cur = getFavorites();
  setFavorites(cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name]);
}

export function useFavorites() {
  const [favs, setFavs] = useState(getFavorites);
  useEffect(() => {
    const on = () => setFavs(getFavorites());
    window.addEventListener(EVT, on);
    window.addEventListener("storage", on);
    return () => { window.removeEventListener(EVT, on); window.removeEventListener("storage", on); };
  }, []);
  return favs;
}
