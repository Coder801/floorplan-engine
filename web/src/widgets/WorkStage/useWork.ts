// The work state of the "Tasks" tab: loaded when the tab opens, replaced by the answer of every
// write (the API answers with the whole state). One write at a time: busy blocks the buttons.

import { useCallback, useEffect, useRef, useState } from "react";
import { getWork } from "@/shared/api";
import type { WorkRun } from "@/shared/work";
import type { WorkState } from "@/shared/types";

export interface WorkControl {
  state: WorkState | null;
  error: string | null;   // the last refusal or load failure, server text
  busy: boolean;
  run: WorkRun;
  clearError: () => void;
}

export function useWork(key: string | null, active: boolean): WorkControl {
  const [state, setState] = useState<WorkState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const current = useRef(key);
  current.current = key;

  // Another project: nothing of the previous one stays
  useEffect(() => { setState(null); setError(null); }, [key]);

  // Each opening of the tab reads the state again: others may have changed it meanwhile
  useEffect(() => {
    if (!key || !active) return;
    let alive = true;
    getWork(key).then((s) => { if (alive) { setState(s); setError(null); } },
                      (e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, [key, active]);

  const run = useCallback<WorkRun>(async (call) => {
    const k = current.current;
    if (!k) return false;
    setBusy(true);
    try {
      const next = await call(k);
      if (current.current === k) { setState(next); setError(null); }
      return true;
    } catch (e) {
      if (current.current === k) setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);
  return { state, error, busy, run, clearError };
}
