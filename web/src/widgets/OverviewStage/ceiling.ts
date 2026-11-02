// Высота потолка, правка из просмотра (мм): от 2 до 4 м — те же границы, что в схеме variant.yaml
// (model/schema.py: CEILING_MIN, CEILING_MAX)

export const CEILING_MIN = 2000;
export const CEILING_MAX = 4000;

// Текст поля → мм или null, если это не число от 2000 до 4000 (запятая как точка допустима)
export function parseCeiling(text: string): number | null {
  const n = Number(text.trim().replace(",", "."));
  return text.trim() && Number.isFinite(n) && n >= CEILING_MIN && n <= CEILING_MAX ? n : null;
}
