// Фронт просмотра — самостоятельный проект: сборка в web/dist, свои серверы разработки
// и предпросмотра. API — `floorplan-engine view` (по умолчанию порт 8000; другой адрес —
// API_URL=http://127.0.0.1:8765 npm run dev). Запросы /api идут к нему через прокси:
// CORS не нужен; при выкладке так же — обратный прокси (nginx и т. п.).
import { execFile } from "node:child_process";
import { basename, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const api = { "/api": process.env.API_URL || "http://127.0.0.1:8000" };

// Номер сборки: зашит в бандл (__BUILD_ID__) и лежит рядом в dist/version.json. Вкладка,
// открытая до деплоя, сверяет их и показывает «Доступна новая версия» (version.ts)
const BUILD_ID = process.env.BUILD_ID || new Date().toISOString().replace(/[-:.TZ]/g, "");
const version = (): Plugin => ({
  name: "version",
  apply: "build",
  generateBundle() {
    this.emitFile({ type: "asset", fileName: "version.json", source: JSON.stringify({ build: BUILD_ID }) });
  },
});

// Правка .scss в разработке — переписать типы модулей (scripts/css-types.mjs): новый класс
// сразу виден в редакторе, опечатка — ошибкой
const cssTypes = (): Plugin => ({
  name: "css-types",
  apply: "serve",
  handleHotUpdate({ file }) {
    if (file.endsWith(".scss")) execFile("node", ["scripts/css-types.mjs"], (e) => e && console.error(e.message));
  },
});

export default defineConfig({
  plugins: [react(), version(), cssTypes()],
  // @/… — от src: компоненты по группам (pages, widgets, ui), общее (shared), холсты (engine)
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  define: { __BUILD_ID__: JSON.stringify(process.env.NODE_ENV === "production" ? BUILD_ID : "dev") },
  // Стили — SCSS-модули рядом с компонентами: .row-btns в файле → styles.rowBtns в коде
  css: {
    modules: { localsConvention: "camelCaseOnly" },
    preprocessorOptions: { scss: { api: "modern-compiler" } },
  },
  build: {
    chunkSizeWarningLimit: 1500,
    // Компонент — папка с index.tsx: чанк по имени папки (Scene3D-…js), а не «index-…js»
    rollupOptions: {
      output: {
        chunkFileNames: (c) => `assets/${c.name === "index" && c.facadeModuleId
          ? basename(dirname(c.facadeModuleId)) : "[name]"}-[hash].js`,
      },
    },
  },  // 3D (three.js) — отдельный файл, грузится по кнопке
  // 127.0.0.1, как у API: «localhost» Node может отдать только по IPv6 (::1)
  server: { host: "127.0.0.1", port: 5173, proxy: api },
  preview: { host: "127.0.0.1", port: 4173, proxy: api },
});
