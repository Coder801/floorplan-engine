// Theme colours for the canvas and 3D, read from CSS variables once per frame

import { THEMES, type Theme } from "./consts";

export const palette = { ink: "none", paper: "#ffffff", hl: "#d2491a", pin: "#1f6fb5" };

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function refreshPalette() {
  palette.ink = cssVar("--ink"); palette.paper = cssVar("--paper"); palette.hl = cssVar("--hl");
  palette.pin = cssVar("--pin") || palette.pin;
}

export const isDark = () => !!palette.ink && palette.ink !== "none";

// Screen colour: in the dark theme black and dark grey become light "ink", white becomes paper
export function screenColor(c: string): string {
  const ink = palette.ink;
  if (!ink || ink === "none" || !c) return c;
  const n = parseInt(c.slice(1, 7), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
  const grey = Math.max(r, g, b) - Math.min(r, g, b) < 24;
  const alpha = c.length === 9 && /^#[0-9a-f]{6}$/i.test(ink) ? c.slice(7) : "";  // #rrggbbaa from the sheet
  if (grey && r < 128) return ink + alpha;
  if (grey && r > 230) return palette.paper;
  return c;
}

// Per-viewer conveniences (theme, tab): storage may be unavailable
export function remembered(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
export function remember(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* not remembered */ }
}

export function savedTheme(): Theme {
  const t = remembered("theme");
  return (THEMES as readonly string[]).includes(t || "") ? (t as Theme) : "system";  // "Auto" by default, as in the system
}

export function applyTheme(theme: Theme) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}
