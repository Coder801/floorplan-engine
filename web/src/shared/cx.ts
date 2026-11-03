// Classes joined by spaces: falsy values are skipped; empty means no class attribute
export const cx = (...names: (string | false | null | undefined)[]): string | undefined =>
  names.filter(Boolean).join(" ") || undefined;
