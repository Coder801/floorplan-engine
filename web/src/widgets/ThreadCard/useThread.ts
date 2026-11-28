// One thread of the card: read on open; a write answers with the thread, which replaces it (the
// chain read on open stays); while the AI checks the accepted answer (state checking) it is read
// again every POLL_MS, until it leaves checking. A failed read during the check does not stop the
// polling: the next tick asks again.

import { useCallback, useEffect, useRef, useState } from "react";
import { POLL_MS } from "@/shared/threadList";
import { ThreadError, type Thread, type ThreadDetail, type ThreadsApi } from "@/shared/threads";

export interface ThreadHandle {
  detail: ThreadDetail | null;
  error: string | null;   // a refused read or write, the server's text
  busy: boolean;          // a write is on its way
  run: (write: () => Promise<Thread>) => Promise<boolean>;
  clearError: () => void;
}

const messageOf = (e: unknown) => (e instanceof ThreadError || e instanceof Error ? e.message : String(e));

// onChanged: the thread changed here or by the check — the list reads its rows again
export function useThread(api: ThreadsApi, key: string, id: string, onChanged: () => void): ThreadHandle {
  const [detail, setDetail] = useState<ThreadDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const alive = useRef(true);
  const changed = useRef(onChanged);
  changed.current = onChanged;
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const read = useCallback(async (): Promise<ThreadDetail | null> => {
    try {
      const d = await api.get(key, id);
      if (alive.current) setDetail(d);
      return d;
    } catch (e) {
      if (alive.current) setError(messageOf(e));
      return null;
    }
  }, [api, key, id]);

  useEffect(() => { setDetail(null); setError(null); void read(); }, [read]);

  const checking = detail?.state === "checking";
  useEffect(() => {
    if (!checking) return;
    const timer = setTimeout(() => {
      void read().then((d) => {
        if (!alive.current) return;
        if (d && d.state !== "checking") changed.current();
        else setTick((n) => n + 1);
      });
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [checking, tick, read]);

  const run = useCallback(async (write: () => Promise<Thread>) => {
    setBusy(true);
    setError(null);
    try {
      const t = await write();
      if (alive.current) setDetail((d) => ({ ...t, previous: d?.previous ?? [] }));
      changed.current();
      return true;
    } catch (e) {
      if (alive.current) setError(messageOf(e));
      return false;
    } finally {
      if (alive.current) setBusy(false);
    }
  }, []);

  return { detail, error, busy, run, clearError: () => setError(null) };
}
