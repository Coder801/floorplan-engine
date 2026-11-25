// Lighting cables of a scheme on the sheet (BoxScheme, SpliceScheme): a row under the cursor puts
// its cable and target into store.lit; the scheme clears what it lit when it goes away

import { useEffect, useRef, useState } from "react";
import { useView, view } from "@/shared/store";

export function useCableLight() {
  const hover = useView((s) => s.hover);
  const lit = useView((s) => s.lit);
  const [near, setNear] = useState<string | null>(null);  // first key of the row under the cursor
  const ours = useRef(false);  // lit was set here: cleared when the scheme goes away
  useEffect(() => () => { if (ours.current) view.set({ lit: null }); }, []);

  // Light these objects (the first is the row's own cable), or nothing
  const light = (keys: string[] | null) => {
    setNear(keys?.[0] ?? null);
    ours.current = !!keys;
    view.set({ lit: keys ? new Set(keys) : null });
  };
  // A cable is lit: its row is under the cursor, it or its target is under the cursor on the sheet,
  // or something lit it (a table row, a joint of the scheme)
  const on = (cable: string, target: string | null = null) =>
    near === cable || hover === cable || (!!target && hover === target) || !!lit?.has(cable);
  return { light, on };
}
