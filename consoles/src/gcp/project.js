/* Current project (the console's project picker). Persisted per browser. Every GCP API
 * call that is project-scoped passes it (e.g. buckets.list?project=…). */
import { useEffect, useState } from "react";

const KEY = "vyomi.v4.gcp.project";
const LIST = "vyomi.v4.gcp.projects";
export const DEFAULT_PROJECT = "vyomi-project";

const read = (k, d) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
const write = (k, v) => { try { localStorage.setItem(k, v); } catch {} };

let current = read(KEY, DEFAULT_PROJECT);
const subs = new Set();

export const getProject = () => current;
export function setProject(p) {
  current = p;
  write(KEY, p);
  const known = knownProjects();
  if (!known.includes(p)) write(LIST, JSON.stringify([...known, p]));
  subs.forEach((f) => f(p));
}
export function knownProjects() {
  let xs = [];
  try { xs = JSON.parse(read(LIST, "[]")); } catch {}
  return [...new Set([DEFAULT_PROJECT, ...xs, current])];
}
export function useProject() {
  const [p, setP] = useState(current);
  useEffect(() => { subs.add(setP); return () => subs.delete(setP); }, []);
  return p;
}
