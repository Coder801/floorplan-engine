// Проект пересобрали, пока вкладка открыта (build в терминале, правка в другой вкладке):
// листы в памяти страницы — старые. Время сборки (built, out/report.json) сверяется раз в
// EVERY_MS и когда вкладка снова видна; изменилось — onRebuilt (перечитать листы).

const EVERY_MS = 10_000;

// built — время сборки, с которым открыты листы; load — свежее время сборки с API
export function watchRebuild(load: () => Promise<number | null>, built: number | null,
                             onRebuilt: () => void, every = EVERY_MS): () => void {
  let done = false;
  const check = async () => {
    if (done || document.hidden) return;
    let now: number | null;
    try { now = await load(); } catch { return; }  // нет сети — не повод перечитывать
    if (!done && now !== null && now !== built) { done = true; onRebuilt(); }
  };
  const timer = setInterval(check, every);
  document.addEventListener("visibilitychange", check);
  window.addEventListener("focus", check);
  return () => {
    done = true;
    clearInterval(timer);
    document.removeEventListener("visibilitychange", check);
    window.removeEventListener("focus", check);
  };
}
