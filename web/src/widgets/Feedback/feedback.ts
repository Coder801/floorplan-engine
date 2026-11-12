// "Leave feedback" without React (tests next to it): kinds, limits of the text and screenshots, the
// context the page attaches by itself (project, sheet, address, version, screen, browser) and what
// a refused send means in words

import type { FeedbackContext, FeedbackKind } from "@/shared/types";
import { PHOTO_MAX } from "@/shared/work";

export const FEEDBACK_KINDS: FeedbackKind[] = ["bug", "idea", "other"];
export const TEXT_MAX = 4000;     // the server limit of the text (POST /api/feedback)
export const PHOTOS_MAX = 3;      // screenshots in one message
export { PHOTO_MAX };             // the size of one, as for work task photos
export const PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"];

// The text goes trimmed; empty or over the limit — the button is off
export const textOk = (text: string) => {
  const n = text.trim().length;
  return n > 0 && n <= TEXT_MAX;
};

export type PhotoRefusal = "type" | "size" | "count";
export interface PhotoPick { photos: File[]; refused: { name: string; reason: PhotoRefusal }[] }

// Picked files on top of the ones already attached: a wrong type, a big file and anything past the
// third are refused by name (shown under the photos), the rest are added in order
export function addPhotos(current: File[], picked: File[]): PhotoPick {
  const photos = [...current];
  const refused: PhotoPick["refused"] = [];
  for (const f of picked) {
    if (!PHOTO_TYPES.includes(f.type.toLowerCase())) refused.push({ name: f.name, reason: "type" });
    else if (f.size > PHOTO_MAX) refused.push({ name: f.name, reason: "size" });
    else if (photos.length >= PHOTOS_MAX) refused.push({ name: f.name, reason: "count" });
    else photos.push(f);
  }
  return { photos, refused };
}

// Where the user is, from the viewer: a tab that is not a sheet by its word, a sheet by its name,
// an elevation with the open wall
export interface Place {
  info?: boolean;
  estimate?: boolean;
  work?: boolean;
  source?: string | null;    // a source/ file opened instead of a sheet
  sheet?: string | null;     // the name of the open sheet (manifest)
  wall?: string | null;      // the open elevation (wall key)
}

export function sheetOf(p: Place): string | null {
  if (p.source) return `source:${p.source}`;
  if (p.info) return "overview";
  if (p.estimate) return "estimate";
  if (p.work) return "work";
  if (!p.sheet) return null;
  return p.wall ? `${p.sheet} · ${p.wall}` : p.sheet;
}

export interface Where {
  path: string;              // location: pathname + search + hash
  width: number;
  height: number;
  dpr: number;
  userAgent: string;
}

export function contextOf(sheet: string | null, version: string, w: Where): FeedbackContext {
  const dpr = Math.round(w.dpr * 100) / 100;
  return {
    sheet,
    path: w.path,
    version,
    viewport: `${Math.round(w.width)}×${Math.round(w.height)}${dpr !== 1 ? `@${dpr}` : ""}`,
    user_agent: w.userAgent,
  };
}

// The same from the browser
export const browserWhere = (): Where => ({
  path: `${location.pathname}${location.search}${location.hash}`,
  width: window.innerWidth,
  height: window.innerHeight,
  dpr: window.devicePixelRatio || 1,
  userAgent: navigator.userAgent,
});

// A refused send in words: an i18n key under feedback.errors; the server text is kept for 429 (the
// rate limit says when to try again, in Russian) and for anything unexpected
export type SendFailure = "auth" | "rate" | "tooBig" | "type" | "failed";
export function failureOf(status: number | null): SendFailure {
  if (status === 401 || status === 403) return "auth";
  if (status === 429) return "rate";
  if (status === 413) return "tooBig";
  if (status === 415) return "type";
  return "failed";
}
