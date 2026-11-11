// Every story gets the viewer's global styles and dictionaries; the interface language and the
// theme are toolbar switches (the same values as in the viewer settings)
import type { Preview } from "@storybook/react-vite";
import { useEffect } from "react";
import { LANGUAGES, setLanguage, type UiLanguage } from "@/shared/i18n";
import { THEMES, type Theme } from "@/shared/consts";
import { applyTheme, refreshPalette } from "@/shared/palette";
import "@/shared/styles/global.scss";

const preview: Preview = {
  globalTypes: {
    lang: {
      description: "Язык интерфейса",
      toolbar: { title: "Язык", icon: "globe", items: LANGUAGES.map((l) => ({ value: l.code, title: l.name })), dynamicTitle: true },
    },
    theme: {
      description: "Тема",
      toolbar: { title: "Тема", icon: "mirror", items: [...THEMES], dynamicTitle: true },
    },
  },
  initialGlobals: { lang: "ru", theme: "light" },
  decorators: [
    (Story, { globals }) => {
      const lang = globals.lang as UiLanguage, theme = globals.theme as Theme;
      useEffect(() => { setLanguage(lang); }, [lang]);
      useEffect(() => { applyTheme(theme); refreshPalette(); }, [theme]);
      return <Story />;
    },
  ],
  parameters: { layout: "fullscreen" },
};

export default preview;
