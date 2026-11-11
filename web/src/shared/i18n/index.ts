// Interface language (i18next + react-i18next): Ukrainian, Russian, English. Strings live in
// ru.ts (the source of keys), uk.ts, en.ts; components take t from useTranslation (they
// re-render on language change), code outside React uses i18n.t. The choice is in settings and
// is remembered (remember "lang"); without a choice, the browser language, otherwise Russian.
// Drawings, tables and cards are in the project language (room.yaml: language): the build
// writes them and the interface does not translate them.

import i18n, { type TFunction } from "i18next";
import { initReactI18next } from "react-i18next";
import { remember, remembered } from "@/shared/palette";
import { en } from "./en";
import { ru, type Messages } from "./ru";
import { uk } from "./uk";
import { BRAND, STAGE } from "@/shared/version";

export const LANGUAGES = [
  { code: "uk", name: "Українська" },
  { code: "ru", name: "Русский" },
  { code: "en", name: "English" },
] as const;
export type UiLanguage = (typeof LANGUAGES)[number]["code"];

const known = (c: string | null | undefined): c is UiLanguage => LANGUAGES.some((l) => l.code === c);

// The saved choice, otherwise the first matching browser language, otherwise Russian
export function startLanguage(): UiLanguage {
  const saved = remembered("lang");
  if (known(saved)) return saved;
  const browser = typeof navigator === "undefined" ? [] : navigator.languages ?? [navigator.language];
  return browser.map((l) => l.slice(0, 2).toLowerCase()).find(known) ?? "ru";
}

declare module "i18next" {
  interface CustomTypeOptions {
    resources: { translation: Messages };
  }
}

void i18n.use(initReactI18next).init({
  resources: { ru: { translation: ru }, uk: { translation: uk }, en: { translation: en } },
  lng: startLanguage(),
  fallbackLng: "ru",
  interpolation: { escapeValue: false },  // React escapes on its own
});
// Tab title: what is open first (project · sheet), then the brand with the stage in brackets —
// "Квартира · План — Shtroba [альфа]"; nothing open — the brand alone. The viewer sets it for
// the open page (pages/Viewer), here only the start one
export function pageTitle(...parts: (string | null | undefined)[]): string {
  const brand = `${BRAND} [${i18n.t(`app.stages.${STAGE}`)}]`;
  const what = parts.filter((p): p is string => !!p).join(" · ");
  return what ? `${what} — ${brand}` : brand;
}

// The page language follows the interface language
const applyDocument = () => {
  if (typeof document === "undefined") return;
  document.documentElement.lang = i18n.language;
};
applyDocument();
if (typeof document !== "undefined") document.title = pageTitle(i18n.t("app.projects"));
i18n.on("languageChanged", applyDocument);

export function setLanguage(code: UiLanguage) {
  remember("lang", code);
  void i18n.changeLanguage(code);
}

// t for a key built at run time (a wizard step and its values): the typed t does not know it
export const anyKey = (t: TFunction): ((key: string) => string) => t as unknown as (key: string) => string;

// Label for a value from data (status, stage, layer, object type); without a translation, the
// value itself. The component that shows it takes useTranslation so it re-renders on language change
export type LabelGroup = "status" | "stage" | "views" | "severity" | "layer" | "object";
export function label(group: LabelGroup, key: string): string {
  const k = `${group}.${key}`;
  return i18n.exists(k) ? (i18n.t as (key: string) => string)(k) : key;
}

// Date and time in the interface language
export const locale = () => (i18n.language === "uk" ? "uk-UA" : i18n.language === "en" ? "en-GB" : "ru-RU");

export default i18n;
