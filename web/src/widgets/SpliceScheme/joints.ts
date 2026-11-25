// What the flush box scheme reads from the splice key of a point card (docs/epd-format.md,
// "objects"): which cables out run from the device terminals and how a joint is made. Pure
// functions over the build's data: nothing is counted here

import type { SpliceData, SpliceJoint } from "@/shared/types";

// Cables out whose phase is not in the phase joint: they run on from the device terminals (the
// switched wire to the lights, the travellers to the second pass switch). A cable in no joint at
// all is one of them too
export function offTerminals(s: SpliceData): Set<string> {
  const phase = s.joints.find((j) => j.conductor === "L");
  return new Set(s.out.map((c) => c.key).filter((k) => !phase?.out.includes(k)));
}

// Wago models of a joint, as one string: "413", two clamps with a jumper — "415 + 413"
export const clampModels = (j: SpliceJoint): string => j.clamps.join(" + ");

// Cables of a joint to light on the sheet: the incoming one is always in it
export const jointCables = (s: SpliceData, j: SpliceJoint): string[] =>
  [...(s.in ? [s.in.key] : []), ...j.out];
