// Ceiling height edited in the viewer (mm): 2 to 4 m, the same limits as in the variant.yaml
// schema (model/schema.py: CEILING_MIN, CEILING_MAX)

export const CEILING_MIN = 2000;
export const CEILING_MAX = 4000;

// Field text → mm, or null if it is not a number from 2000 to 4000 (a comma works as a decimal point)
export function parseCeiling(text: string): number | null {
  const n = Number(text.trim().replace(",", "."));
  return text.trim() && Number.isFinite(n) && n >= CEILING_MIN && n <= CEILING_MAX ? n : null;
}
