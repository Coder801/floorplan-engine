// The studio profile in the studio card (read only): organization, stage and signatures are the
// stamp data of the sheets. A flat part reads as "key → value" lines, a nested one as JSON.
import type { StudioProfile } from "./types";

export const PROFILE_PARTS: { key: keyof StudioProfile; label: string }[] = [
  { key: "organization", label: "Организация" },
  { key: "stage", label: "Стадия" },
  { key: "signatures", label: "Подписи" },
];

export type ProfileView =
  | { kind: "lines"; lines: [string, string][] }  // key → value
  | { kind: "json"; text: string };                // nested: formatted JSON

const plain = (v: unknown): v is string | number | boolean | null =>
  v === null || ["string", "number", "boolean"].includes(typeof v);

const show = (v: string | number | boolean | null) =>
  v === null || v === "" ? "—" : typeof v === "boolean" ? (v ? "да" : "нет") : String(v);

/** How to show one part: a single value or an object of single values — lines, else JSON. */
export function profileView(value: unknown): ProfileView {
  if (plain(value)) return { kind: "lines", lines: [["", show(value)]] };
  if (typeof value === "object" && !Array.isArray(value) && Object.values(value).every(plain)) {
    return { kind: "lines", lines: Object.entries(value).map(([k, v]) => [k, show(v as string | number | boolean | null)]) };
  }
  return { kind: "json", text: JSON.stringify(value, null, 2) };
}
