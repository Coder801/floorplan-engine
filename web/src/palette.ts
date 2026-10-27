// Цвета темы для холста и 3D — читаются из CSS-переменных один раз за кадр

import { THEMES, type Theme } from "./consts";

export const palette = { ink: "none", paper: "#ffffff", hl: "#d2491a" };

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function refreshPalette() {
  palette.ink = cssVar("--ink"); palette.paper = cssVar("--paper"); palette.hl = cssVar("--hl");
}

export const isDark = () => !!palette.ink && palette.ink !== "none";

// Цвет на экране: в тёмной теме чёрное и тёмно-серое — светлым «чернилом», белое — бумагой
export function screenColor(c: string): string {
  const ink = palette.ink;
  if (!ink || ink === "none" || !c) return c;
  const n = parseInt(c.slice(1, 7), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
  const grey = Math.max(r, g, b) - Math.min(r, g, b) < 24;
  if (grey && r < 128) return ink;
  if (grey && r > 230) return palette.paper;
  return c;
}

// Удобства одного зрителя (тема, вкладка): хранилище может быть недоступно
export function remembered(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
export function remember(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* без запоминания */ }
}

export function savedTheme(): Theme {
  const t = remembered("theme");
  return (THEMES as readonly string[]).includes(t || "") ? (t as Theme) : "light";  // по умолчанию — светлая
}

export function applyTheme(theme: Theme) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}
