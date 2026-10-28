// Типы SCSS-модулей: рядом с каждым src/**/*.module.scss — .module.scss.d.ts с именами его
// классов. Имена считает сам Vite (preprocessCSS с конфигом проекта), поэтому они те же, что
// в рантайме, вместе с camelCaseOnly (.row-btns → rowBtns, .layer3d → layer3D). Опечатка
// в css.имя — ошибка tsc, а не пустой класс. Файлы не в git: их пишут check, build и dev.
//
//   node scripts/css-types.mjs          — записать
//   node scripts/css-types.mjs --watch  — и переписывать при правке .scss

import { readdir, readFile, writeFile, unlink } from "node:fs/promises";
import { watch } from "node:fs";
import { join, relative } from "node:path";
import { preprocessCSS, resolveConfig } from "vite";

const root = new URL("..", import.meta.url).pathname;
const src = join(root, "src");
const config = await resolveConfig({ root, logLevel: "silent" }, "build");

async function* modules(dir) {
  for (const e of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) yield* modules(p);
    else if (e.name.endsWith(".module.scss")) yield p;
  }
}

async function write(file) {
  const { modules: names = {} } = await preprocessCSS(await readFile(file, "utf8"), file, config);
  const keys = Object.keys(names).sort();
  const body = keys.map((k) => `  readonly ${JSON.stringify(k)}: string;`).join("\n");
  const out = `// Создано scripts/css-types.mjs — не править\ndeclare const styles: {\n${body}\n};\nexport default styles;\n`;
  const dts = `${file}.d.ts`;
  const old = await readFile(dts, "utf8").catch(() => null);
  if (old !== out) await writeFile(dts, out);
}

async function writeAll() {
  const files = [];
  for await (const f of modules(src)) files.push(f);
  await Promise.all(files.map(write));
  // Модуль удалили — убрать и его типы
  for await (const f of dts(src)) if (!files.includes(f.slice(0, -5))) await unlink(f);
  return files.length;
}

async function* dts(dir) {
  for (const e of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) yield* dts(p);
    else if (e.name.endsWith(".module.scss.d.ts")) yield p;
  }
}

const n = await writeAll();
if (process.argv.includes("--watch")) {
  console.log(`css-types: ${n} модулей, слежу за src/`);
  // Миксины и токены — в любом модуле: правка .scss переписывает все
  let timer = null;
  watch(src, { recursive: true }, (_, name) => {
    if (!name || !name.endsWith(".scss")) return;
    clearTimeout(timer);
    timer = setTimeout(() => writeAll().catch((e) => console.error(`css-types: ${relative(root, e.file ?? "")} ${e.message}`)), 100);
  });
} else {
  process.exit(0);  // компилятор sass-embedded держит процесс — без явного выхода не завершится
}
