import { useCallback, useEffect, useRef, useState } from "react";

export function useMedia(query: string): boolean {
  const get = () => typeof matchMedia !== "undefined" && matchMedia(query).matches;
  const [on, setOn] = useState(get);
  useEffect(() => {
    const mq = matchMedia(query);
    const fn = () => setOn(mq.matches);
    fn();
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, [query]);
  return on;
}
export const useIsMobile = () => useMedia("(max-width: 899px)");

export function useLocalStorage<T>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const [val, setVal] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? { ...initial, ...JSON.parse(raw) } : initial;
    } catch { return initial; }
  });
  const set = useCallback((v: T | ((p: T) => T)) => {
    setVal(prev => {
      const next = typeof v === "function" ? (v as (p: T) => T)(prev) : v;
      try { localStorage.setItem(key, JSON.stringify(next)); } catch { /* quota / private mode */ }
      return next;
    });
  }, [key]);
  return [val, set];
}

export interface Async<T> { data?: T; error?: Error; loading: boolean; reload: () => void; setData: (fn: (d: T) => T) => void }
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): Async<T> {
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: true });
  const [tick, setTick] = useState(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    setState(s => ({ ...s, loading: true, error: undefined }));
    fn().then(data => alive.current && setState({ data, loading: false }))
        .catch((error: Error) => alive.current && setState(s => ({ ...s, error, loading: false })));
    return () => { alive.current = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return {
    ...state,
    reload: useCallback(() => setTick(t => t + 1), []),
    setData: useCallback((upd: (d: T) => T) => setState(s => (s.data === undefined ? s : { ...s, data: upd(s.data) })), []),
  };
}

/** Remember what this browser last had open, for the home page's Continue tile. */
export interface LastOpen { pid: string; id: string; title: string; genre: string; ts: number }
export function rememberLast(p: Omit<LastOpen, "ts">) {
  try { localStorage.setItem("mogi-last", JSON.stringify({ ...p, ts: Date.now() })); } catch { /* ignore */ }
}
export function readLast(): LastOpen | null {
  try { return JSON.parse(localStorage.getItem("mogi-last") || "null"); } catch { return null; }
}
