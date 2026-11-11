// Unresolved questions of the project by weight, for the "Overview" side panel
import type { Question } from "@/shared/types";

export const SEVERITIES = ["critical", "major", "minor"] as const;
export type Severity = (typeof SEVERITIES)[number];

// Unresolved: without an answer, or with a text answer not handled yet (as in the viewer header)
const UNRESOLVED = new Set(["open", "text"]);

export function questionCounts(questions: Question[]): Record<Severity, number> {
  const out: Record<Severity, number> = { critical: 0, major: 0, minor: 0 };
  for (const q of questions) {
    if (!UNRESOLVED.has(q.state)) continue;
    const sev = (SEVERITIES as readonly string[]).includes(q.severity) ? (q.severity as Severity) : "minor";
    out[sev] += 1;
  }
  return out;
}
