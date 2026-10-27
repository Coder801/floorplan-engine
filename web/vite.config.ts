// Фронт просмотра — самостоятельный проект: сборка в web/dist, свои серверы разработки
// и предпросмотра. API — `shtroba view` (по умолчанию порт 8000; другой адрес —
// API_URL=http://127.0.0.1:8765 npm run dev). Запросы /api идут к нему через прокси:
// CORS не нужен; при выкладке так же — обратный прокси (nginx и т. п.).
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = { "/api": process.env.API_URL || "http://127.0.0.1:8000" };

export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 1500 },  // 3D (three.js) — отдельный файл, грузится по кнопке
  // 127.0.0.1, как у API: «localhost» Node может отдать только по IPv6 (::1)
  server: { host: "127.0.0.1", port: 5173, proxy: api },
  preview: { host: "127.0.0.1", port: 4173, proxy: api },
});
