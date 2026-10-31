// Проверка версии: вкладка, открытая до деплоя, со старым бандлом читает новый API и молча
// ломается. Номер сборки зашит в бандл (__BUILD_ID__, vite.config.ts) и лежит в
// /version.json; разошлись — пора перезагрузить страницу. В разработке («dev») не проверяется.

declare const __BUILD_ID__: string;
export const BUILD_ID = __BUILD_ID__;

// Версия формата .epd, которую понимает эта страница (artifact.FORMAT_VERSION)
export const FORMAT_VERSION = 1;

const EVERY_MS = 5 * 60_000;

export async function latestBuild(): Promise<string | null> {
  try {
    const r = await fetch("/version.json", { cache: "no-store" });
    return r.ok ? ((await r.json()) as { build?: string }).build ?? null : null;
  } catch {
    return null;  // нет сети — не повод звать перезагрузку
  }
}

// Следить за выкладкой: раз в 5 минут и когда вкладка снова видна; onStale — один раз
export function watchBuild(onStale: () => void): () => void {
  if (BUILD_ID === "dev") return () => {};
  let done = false;
  const check = async () => {
    if (done || document.hidden) return;
    const b = await latestBuild();
    if (b && b !== BUILD_ID) { done = true; onStale(); }
  };
  const timer = setInterval(check, EVERY_MS);
  document.addEventListener("visibilitychange", check);
  check();
  return () => { clearInterval(timer); document.removeEventListener("visibilitychange", check); };
}
