// Platform admin: a standalone project like web/, served at /admin/ on the viewer's domain, so
// the login session cookie is shared (docs/database.md, "Админка платформы"). The API is the
// same `floorplan-engine view` (port 8000; another address: API_URL=… npm run dev), /api goes
// through a proxy.
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = { "/api": process.env.API_URL || "http://127.0.0.1:8000" };

export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  css: {
    modules: { localsConvention: "camelCaseOnly" },
  },
  // hmr.clientPort: opened through the viewer's proxy (5173/admin/) the page still reloads from
  // this server directly
  server: { host: "127.0.0.1", port: 5174, strictPort: true, proxy: api, hmr: { clientPort: 5174 } },
  preview: { host: "127.0.0.1", port: 4174, proxy: api },
});
