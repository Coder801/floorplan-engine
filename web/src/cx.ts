// Классы через пробел: ложные значения пропускаются; пусто — без атрибута class
export const cx = (...names: (string | false | null | undefined)[]): string | undefined =>
  names.filter(Boolean).join(" ") || undefined;
