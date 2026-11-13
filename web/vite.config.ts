// The viewer frontend is a standalone project: it builds into web/dist and has its own dev and
// preview servers. The API is `floorplan-engine view` (port 8000 by default; another address:
// API_URL=http://127.0.0.1:8765 npm run dev). /api requests go to it through a proxy, so no
// CORS is needed; deployment does the same with a reverse proxy (nginx and the like).
import { execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { basename, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { uiNames } from "./scripts/uiNames.ts";

const api = { "/api": process.env.API_URL || "http://127.0.0.1:8000" };

// Build number: baked into the bundle (__BUILD_ID__) and placed next to it in dist/version.json.
// A tab opened before a deploy compares them and shows "A new version is available" (version.ts)
const BUILD_ID = process.env.BUILD_ID || new Date().toISOString().replace(/[-:.TZ]/g, "");
// The product version comes from package.json (the same as the Python package:
// tests/test_version.py); shown in settings (__APP_VERSION__)
const APP_VERSION = (JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")) as { version: string }).version;
// "What's new" (shared/changelog.ts): the repository's CHANGELOG.md, written by `cz bump` on a
// release; the Docker web stage copies it next to web/ (Dockerfile)
const changelogFile = new URL("../CHANGELOG.md", import.meta.url);
const CHANGELOG = existsSync(changelogFile) ? readFileSync(changelogFile, "utf8") : "";
const version = (): Plugin => ({
  name: "version",
  apply: "build",
  generateBundle() {
    this.emitFile({ type: "asset", fileName: "version.json", source: JSON.stringify({ build: BUILD_ID }) });
  },
});

// A .scss change in development rewrites the module types (scripts/css-types.mjs): a new class
// shows up in the editor at once, a typo is an error
const cssTypes = (): Plugin => ({
  name: "css-types",
  apply: "serve",
  handleHotUpdate({ file }) {
    if (file.endsWith(".scss")) execFile("node", ["scripts/css-types.mjs"], (e) => e && console.error(e.message));
  },
});

export default defineConfig({
  // uiNames: data-ui="Компонент" on the root of every block, for debugging (scripts/uiNames.ts)
  plugins: [uiNames(), react(), version(), cssTypes()],
  // @/… is relative to src: components by group (pages, widgets, ui), shared code (shared), canvases (engine)
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  define: {
    __BUILD_ID__: JSON.stringify(process.env.NODE_ENV === "production" ? BUILD_ID : "dev"),
    __APP_VERSION__: JSON.stringify(APP_VERSION),
    __CHANGELOG__: JSON.stringify(CHANGELOG),
  },
  // Styles are SCSS modules next to components: .row-btns in the file → styles.rowBtns in code
  css: {
    modules: { localsConvention: "camelCaseOnly" },
  },
  build: {
    chunkSizeWarningLimit: 1500,
    // A component is a folder with index.tsx: the chunk is named after the folder (Scene3D-…js), not "index-…js"
    rolldownOptions: {
      output: {
        chunkFileNames: (c) => `assets/${c.name === "index" && c.facadeModuleId
          ? basename(dirname(c.facadeModuleId)) : "[name]"}-[hash].js`,
      },
    },
  },  // 3D (three.js) is a separate file, loaded on the button
  // 127.0.0.1, like the API: Node may serve "localhost" only over IPv6 (::1)
  // /admin goes to the admin dev server (admin/, 5174), so both live on one address as behind Caddy
  // and share the login cookie; `floorplan-engine dev` starts both
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { ...api, "/admin": process.env.ADMIN_URL || "http://127.0.0.1:5174" },
  },
  preview: { host: "127.0.0.1", port: 4173, proxy: api },
});
