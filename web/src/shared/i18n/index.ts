// Язык интерфейса (i18next + react-i18next): украинский, русский, английский. Строки — в
// ru.ts (источник ключей), uk.ts, en.ts; компоненты берут t из useTranslation (перерисуются
// при смене языка), код вне React — i18n.t. Выбор — в настройках, запоминается (remember
// "lang"); без выбора — язык браузера, иначе русский. Чертежи, таблицы и карточки — на языке
// проекта (room.yaml: language): их пишет сборка, интерфейс их не переводит.

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { remember, remembered } from "@/shared/palette";
import { en } from "./en";
import { ru, type Messages } from "./ru";
import { uk } from "./uk";

export const LANGUAGES = [
  { code: "uk", name: "Українська" },
  { code: "ru", name: "Русский" },
  { code: "en", name: "English" },
] as const;
export type UiLanguage = (typeof LANGUAGES)[number]["code"];

const known = (c: string | null | undefined): c is UiLanguage => LANGUAGES.some((l) => l.code === c);

// Сохранённый выбор, иначе первый подходящий язык браузера, иначе русский
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
  interpolation: { escapeValue: false },  // React экранирует сам
});
// Язык страницы и заголовок вкладки — вслед за языком интерфейса
const applyDocument = () => {
  if (typeof document === "undefined") return;
  document.documentElement.lang = i18n.language;
  document.title = `Shtroba · ${i18n.t("app.projects").toLowerCase()}`;
};
applyDocument();
i18n.on("languageChanged", applyDocument);

export function setLanguage(code: UiLanguage) {
  remember("lang", code);
  void i18n.changeLanguage(code);
}

// Подпись значения из данных (статус, этап, слой, тип объекта); перевода нет — само значение.
// Компонент, который её показывает, берёт useTranslation — так он перерисуется при смене языка
export type LabelGroup = "status" | "stage" | "views" | "qstate" | "severity" | "layer" | "object";
export function label(group: LabelGroup, key: string): string {
  const k = `${group}.${key}`;
  return i18n.exists(k) ? (i18n.t as (key: string) => string)(k) : key;
}

// Дата и время — на языке интерфейса
export const locale = () => (i18n.language === "uk" ? "uk-UA" : i18n.language === "en" ? "en-GB" : "ru-RU");

export default i18n;
