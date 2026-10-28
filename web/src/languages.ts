// Языки интерфейса для меню в настройках: код, название на своём языке, флаг
// (country-flag-icons). Переводы подключаются позже через i18n — тогда язык добавляется сюда
// строкой, а выбор (remember("lang")) начинает переключать интерфейс.

import { RU } from "country-flag-icons/react/3x2";

export interface UiLanguage {
  code: string;
  name: string;
  Flag: typeof RU;  // компонент флага (тип пакета не экспортируется — берём у любого флага)
}

export const LANGUAGES: UiLanguage[] = [
  { code: "ru", name: "Русский", Flag: RU },
];
