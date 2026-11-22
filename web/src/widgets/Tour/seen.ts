// Whether this browser has already seen the client tour of the viewer (widgets/Tour). Any close
// marks it: "Got it", "Skip", Esc; the "?" button replays it and erases nothing
import { remember, remembered } from "@/shared/palette";

export const TOUR_KEY = "tour:client";
export const tourSeen = () => remembered(TOUR_KEY) === "seen";
export const markTourSeen = () => remember(TOUR_KEY, "seen");

// "?tour" in the address starts the tour once on load, for any role and even when seen: to show
// it or check it without a client login (http://127.0.0.1:5173/?tour#project)
export const TOUR_PARAM = "tour";
export const tourForced = (search: string) => new URLSearchParams(search).has(TOUR_PARAM);

// The address without "?tour" (the hash and other parameters stay): a reload does not repeat it
export function withoutTourParam(href: string): string {
  const url = new URL(href);
  url.searchParams.delete(TOUR_PARAM);
  return url.toString();
}
